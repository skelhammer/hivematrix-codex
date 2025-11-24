#!/usr/bin/env python3
"""
Unified PSA Sync Script

Syncs data from PSA systems (Freshservice, Superops, etc.) into HiveMatrix.

Usage:
    python sync_psa.py --provider freshservice --type companies
    python sync_psa.py --provider freshservice --type contacts
    python sync_psa.py --provider freshservice --type agents
    python sync_psa.py --provider freshservice --type tickets
    python sync_psa.py --provider freshservice --type tickets --full-history
    python sync_psa.py --provider freshservice --type all
    python sync_psa.py --all-providers  # Sync all enabled providers

Environment:
    Requires Flask app context for database access.
    Configuration loaded from instance/codex.conf
"""

import argparse
import sys
import json
from datetime import datetime, timedelta

# Add parent directory to path for imports
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import app
from extensions import db
from models import Company, Contact, PSAAgent, TicketDetail, SyncJob, BillingPlan
from app.psa import get_provider, list_providers, PSAProviderError


def get_last_ticket_sync_time(provider_name: str):
    """
    Get the timestamp of the last successful ticket sync for a provider.

    Args:
        provider_name: PSA provider name

    Returns:
        ISO timestamp string or None if no previous sync
    """
    last_sync = SyncJob.query.filter_by(
        script='psa',
        provider=provider_name,
        sync_type='tickets',
        status='completed'
    ).order_by(SyncJob.completed_at.desc()).first()

    if last_sync and last_sync.started_at:
        return last_sync.started_at

    return None


def log(message: str):
    """Print timestamped log message."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {message}")


def save_companies(companies: list, provider_name: str) -> int:
    """
    Save normalized company data to database.

    Args:
        companies: List of normalized company dicts from provider
        provider_name: Name of the PSA provider

    Returns:
        Number of companies saved/updated
    """
    count = 0

    for company_data in companies:
        external_id = company_data.get('external_id')
        custom_fields = company_data.get('custom_fields', {})
        account_number = custom_fields.get('account_number') if custom_fields else None

        if not external_id:
            continue

        # Skip companies without account number (like original script)
        if not account_number:
            log(f"  Skipping company '{company_data.get('name')}' - no account number")
            continue

        account_number_str = str(account_number)

        # Find existing company by account_number (primary key)
        company = db.session.get(Company, account_number_str)

        if not company:
            # Create new company
            log(f"  Creating new company: {company_data.get('name')}")
            company = Company(account_number=account_number_str)
            db.session.add(company)
        else:
            log(f"  Updating company: {company_data.get('name')}")

        # Core fields
        company.external_id = external_id
        company.external_source = provider_name
        company.psa_provider = provider_name
        company.name = company_data.get('name')
        company.description = company_data.get('description')
        company.created_at = company_data.get('created_at')
        company.updated_at = company_data.get('updated_at')

        # Head/prime user info
        company.head_user_id = company_data.get('head_user_id')
        company.head_name = company_data.get('head_name')
        company.prime_user_id = company_data.get('prime_user_id')
        company.prime_user_name = company_data.get('prime_user_name')

        # Workspace
        company.workspace_id = company_data.get('workspace_id')

        # Handle domains
        domains = company_data.get('domains', [])
        company.domains = json.dumps(domains) if domains else None

        # Custom fields
        if custom_fields:
            company.plan_selected = custom_fields.get('plan_selected')
            company.managed_users = custom_fields.get('managed_users')
            company.managed_devices = custom_fields.get('managed_devices')
            company.managed_network = custom_fields.get('managed_network')
            company.contract_term = custom_fields.get('contract_term')
            company.contract_start_date = custom_fields.get('contract_start_date')
            company.profit_or_non_profit = custom_fields.get('profit_or_non_profit')
            company.company_main_number = custom_fields.get('company_main_number')
            company.address = custom_fields.get('address')
            company.company_start_date = custom_fields.get('company_start_date')
            company.phone_system = custom_fields.get('phone_system')
            company.email_system = custom_fields.get('email_system')
            company.datto_portal_url = custom_fields.get('datto_portal_url')

            # Billing plan alias
            company.billing_plan = custom_fields.get('plan_selected') or custom_fields.get('billing_plan')

            # Contract term normalization
            raw_term = custom_fields.get('contract_term')
            if raw_term:
                term_normalized = raw_term.lower()
                if term_normalized in ['1 year']:
                    company.contract_term_length = '1 Year'
                elif term_normalized in ['2 year', '2 years']:
                    company.contract_term_length = '2 Year'
                elif term_normalized in ['3 year', '3 years']:
                    company.contract_term_length = '3 Year'
                elif term_normalized in ['month to month', 'monthly']:
                    company.contract_term_length = 'Month to Month'
                else:
                    company.contract_term_length = raw_term
            else:
                company.contract_term_length = None

            # Support level lookup from BillingPlan table
            if company.billing_plan and company.contract_term_length:
                billing_plan = BillingPlan.query.filter_by(
                    plan_name=company.billing_plan,
                    term_length=company.contract_term_length
                ).first()

                if billing_plan and billing_plan.support_level:
                    company.support_level = billing_plan.support_level
                else:
                    company.support_level = 'Billed Hourly'
            else:
                company.support_level = None

            # Calculate contract_end_date from start date and term length
            if company.contract_start_date and company.contract_term_length:
                try:
                    # Parse the contract start date
                    if isinstance(company.contract_start_date, str):
                        start_date_str = company.contract_start_date.split('T')[0]
                        start_date = datetime.fromisoformat(start_date_str)
                    else:
                        start_date = company.contract_start_date

                    # Calculate end date based on term length
                    term = company.contract_term_length
                    years_to_add = {'1 Year': 1, '2 Year': 2, '3 Year': 3}.get(term, 0)

                    if years_to_add > 0:
                        end_date = start_date.replace(year=start_date.year + years_to_add) - timedelta(days=1)
                        company.contract_end_date = end_date.strftime('%Y-%m-%d')
                    else:
                        company.contract_end_date = None
                except (ValueError, AttributeError) as e:
                    log(f"    Warning: Could not calculate contract end date: {e}")
                    company.contract_end_date = None
            else:
                company.contract_end_date = None

        # Commit after each company like original script
        db.session.commit()
        count += 1

    # Delete companies that no longer exist in PSA system
    log("  Checking for deleted companies...")

    # Get all external IDs from the fetched data
    fetched_external_ids = set()
    for company_data in companies:
        custom_fields = company_data.get('custom_fields', {})
        account_number = custom_fields.get('account_number') if custom_fields else None
        if account_number:
            fetched_external_ids.add(company_data.get('external_id'))

    # Get all companies from this provider
    all_codex_companies = Company.query.filter_by(external_source=provider_name).all()

    companies_to_delete = []
    for company in all_codex_companies:
        if company.external_id not in fetched_external_ids:
            companies_to_delete.append(company)

    if companies_to_delete:
        log(f"  Found {len(companies_to_delete)} companies to delete:")
        for company in companies_to_delete:
            log(f"    - Deleting: {company.name} (Account: {company.account_number})")
            db.session.delete(company)

        db.session.commit()
        log(f"  Deleted {len(companies_to_delete)} companies from Codex")
    else:
        log("  No companies to delete")

    return count


def generate_account_number(company_name: str) -> str:
    """
    Generate a unique account number from company name.

    Args:
        company_name: Company name

    Returns:
        Unique account number (e.g., 'ACME001')
    """
    if not company_name:
        company_name = "UNKNOWN"

    # Create base from first 4 chars of name (uppercase, alphanumeric only)
    base = ''.join(c for c in company_name.upper() if c.isalnum())[:4]
    if not base:
        base = "COMP"

    # Find next available number
    existing = Company.query.filter(
        Company.account_number.like(f"{base}%")
    ).all()

    if not existing:
        return f"{base}001"

    # Find highest number
    max_num = 0
    for comp in existing:
        try:
            num = int(comp.account_number[len(base):])
            max_num = max(max_num, num)
        except (ValueError, IndexError):
            pass

    return f"{base}{max_num + 1:03d}"


def save_contacts(contacts: list, provider_name: str) -> int:
    """
    Save normalized contact data to database.

    Args:
        contacts: List of normalized contact dicts from provider
        provider_name: Name of the PSA provider

    Returns:
        Number of contacts saved/updated
    """
    # Build mapping from PSA department ID to account number
    fs_dept_id_to_account_number = {}
    companies = Company.query.filter_by(external_source=provider_name).all()
    for company in companies:
        if company.external_id:
            fs_dept_id_to_account_number[company.external_id] = company.account_number

    count = 0
    for contact_data in contacts:
        fs_user_id = contact_data.get('external_id')  # The PSA requester ID
        email = contact_data.get('email')

        if not email:
            continue

        try:
            # Check if contact exists by external_id
            existing_contact = Contact.query.filter_by(
                external_id=fs_user_id,
                external_source=provider_name
            ).first()

            # Get company account numbers from department IDs
            dept_ids = contact_data.get('department_ids', [])
            fs_company_account_numbers = {
                fs_dept_id_to_account_number.get(dept_id)
                for dept_id in dept_ids
                if fs_dept_id_to_account_number.get(dept_id)
            }

            # Prepare full name
            full_name = contact_data.get('name', '')
            if not full_name:
                first = contact_data.get('first_name', '')
                last = contact_data.get('last_name', '')
                full_name = f"{first} {last}".strip()
            if not full_name:
                full_name = email.split('@')[0]

            # Custom fields
            custom_fields = contact_data.get('custom_fields', {})

            if not existing_contact:
                # Create new contact - set all fields in constructor like original
                contact = Contact(
                    external_id=fs_user_id,
                    external_source=provider_name,
                    first_name=contact_data.get('first_name'),
                    last_name=contact_data.get('last_name'),
                    name=full_name,
                    primary_email=email,
                    email=email,
                    active=contact_data.get('active', True),
                    is_agent=contact_data.get('is_agent', False),
                    vip_user=contact_data.get('vip_user', False),
                    has_logged_in=contact_data.get('has_logged_in', False),
                    mobile_phone_number=contact_data.get('mobile_phone_number'),
                    work_phone_number=contact_data.get('work_phone_number'),
                    address=contact_data.get('address'),
                    secondary_emails=json.dumps(contact_data.get('secondary_emails', [])),
                    job_title=contact_data.get('job_title'),
                    title=contact_data.get('job_title'),
                    department_ids=json.dumps(dept_ids) if dept_ids else None,
                    department_names=contact_data.get('department_names'),
                    reporting_manager_id=contact_data.get('reporting_manager_id'),
                    location_id=contact_data.get('location_id'),
                    location_name=contact_data.get('location_name'),
                    language=contact_data.get('language', 'en'),
                    time_zone=contact_data.get('time_zone'),
                    time_format=contact_data.get('time_format'),
                    can_see_all_tickets_from_associated_departments=contact_data.get(
                        'can_see_all_tickets_from_associated_departments', False
                    ),
                    can_see_all_changes_from_associated_departments=contact_data.get(
                        'can_see_all_changes_from_associated_departments', False
                    ),
                    created_at=contact_data.get('created_at'),
                    updated_at=contact_data.get('updated_at'),
                    background_information=contact_data.get('background_information'),
                    work_schedule_id=contact_data.get('work_schedule_id'),
                    user_number=custom_fields.get('user_number')
                )
                db.session.add(contact)
                db.session.flush()  # Get the contact ID

                # Add company associations
                for account_number in fs_company_account_numbers:
                    company = db.session.get(Company, account_number)
                    if company:
                        contact.companies.append(company)

                log(f"  Created contact: {contact.name} ({email})")
            else:
                # Update existing contact
                existing_contact.first_name = contact_data.get('first_name')
                existing_contact.last_name = contact_data.get('last_name')
                existing_contact.name = full_name
                existing_contact.primary_email = email
                existing_contact.email = email
                existing_contact.active = contact_data.get('active', True)
                existing_contact.is_agent = contact_data.get('is_agent', False)
                existing_contact.vip_user = contact_data.get('vip_user', False)
                existing_contact.has_logged_in = contact_data.get('has_logged_in', False)
                existing_contact.mobile_phone_number = contact_data.get('mobile_phone_number')
                existing_contact.work_phone_number = contact_data.get('work_phone_number')
                existing_contact.address = contact_data.get('address')
                existing_contact.secondary_emails = json.dumps(contact_data.get('secondary_emails', []))
                existing_contact.job_title = contact_data.get('job_title')
                existing_contact.title = contact_data.get('job_title')
                existing_contact.department_ids = json.dumps(dept_ids) if dept_ids else None
                existing_contact.department_names = contact_data.get('department_names')
                existing_contact.reporting_manager_id = contact_data.get('reporting_manager_id')
                existing_contact.location_id = contact_data.get('location_id')
                existing_contact.location_name = contact_data.get('location_name')
                existing_contact.language = contact_data.get('language', 'en')
                existing_contact.time_zone = contact_data.get('time_zone')
                existing_contact.time_format = contact_data.get('time_format')
                existing_contact.can_see_all_tickets_from_associated_departments = contact_data.get(
                    'can_see_all_tickets_from_associated_departments', False
                )
                existing_contact.can_see_all_changes_from_associated_departments = contact_data.get(
                    'can_see_all_changes_from_associated_departments', False
                )
                existing_contact.updated_at = contact_data.get('updated_at')
                existing_contact.background_information = contact_data.get('background_information')
                existing_contact.work_schedule_id = contact_data.get('work_schedule_id')
                existing_contact.user_number = custom_fields.get('user_number')

                # Merge company associations (keep existing, add new from FS)
                existing_account_numbers = {c.account_number for c in existing_contact.companies}
                all_account_numbers = existing_account_numbers.union(fs_company_account_numbers)

                # Update company associations
                existing_contact.companies = []
                for account_number in all_account_numbers:
                    company = db.session.get(Company, account_number)
                    if company:
                        existing_contact.companies.append(company)

                log(f"  Updated contact: {existing_contact.name} ({email})")

            # Commit after each contact like original script
            db.session.commit()
            count += 1

        except Exception as e:
            log(f"  ERROR processing contact {email}: {e}")
            db.session.rollback()

    # Delete contacts that no longer exist in PSA system
    log("  Checking for deleted contacts...")

    # Get all external IDs from the fetched data
    fetched_external_ids = {
        contact_data.get('external_id')
        for contact_data in contacts
        if contact_data.get('email')
    }

    # Get all contacts from this provider
    all_codex_contacts = Contact.query.filter_by(external_source=provider_name).all()

    contacts_to_delete = []
    for contact in all_codex_contacts:
        if contact.external_id not in fetched_external_ids:
            contacts_to_delete.append(contact)

    if contacts_to_delete:
        log(f"  Found {len(contacts_to_delete)} contacts to delete:")
        for contact in contacts_to_delete:
            log(f"    - Deleting: {contact.name} ({contact.email})")
            db.session.delete(contact)

        db.session.commit()
        log(f"  Deleted {len(contacts_to_delete)} contacts from Codex")
    else:
        log("  No contacts to delete")

    return count


def save_agents(agents: list, provider_name: str) -> int:
    """
    Save normalized agent data to database.
    Also deletes agents that no longer exist in the PSA system.

    Args:
        agents: List of normalized agent dicts from provider
        provider_name: Name of the PSA provider

    Returns:
        Number of agents saved/updated
    """
    count = 0
    synced_external_ids = set()

    for agent_data in agents:
        external_id = agent_data.get('external_id')
        if not external_id:
            continue

        synced_external_ids.add(external_id)

        # Find existing agent
        agent = PSAAgent.query.filter_by(
            external_id=external_id,
            external_source=provider_name
        ).first()

        if not agent:
            agent = PSAAgent()
            db.session.add(agent)

        # Update fields
        agent.external_id = external_id
        agent.external_source = provider_name
        agent.email = agent_data.get('email')
        agent.first_name = agent_data.get('first_name')
        agent.last_name = agent_data.get('last_name')
        agent.job_title = agent_data.get('job_title')
        agent.active = agent_data.get('active', True)
        agent.created_at = agent_data.get('created_at')
        agent.updated_at = agent_data.get('updated_at')

        # Handle group_ids and department_ids
        group_ids = agent_data.get('group_ids', [])
        agent.group_ids = json.dumps(group_ids) if group_ids else None

        department_ids = agent_data.get('department_ids', [])
        agent.department_ids = json.dumps(department_ids) if department_ids else None

        count += 1

    # Delete agents that no longer exist in the PSA system
    deleted_count = 0
    existing_agents = PSAAgent.query.filter_by(external_source=provider_name).all()
    for existing_agent in existing_agents:
        if existing_agent.external_id not in synced_external_ids:
            print(f"Deleting agent {existing_agent.name} (ID: {existing_agent.external_id}) - no longer exists in {provider_name}")
            db.session.delete(existing_agent)
            deleted_count += 1

    if deleted_count > 0:
        print(f"Deleted {deleted_count} agents that no longer exist in {provider_name}")

    db.session.commit()
    return count


def save_tickets(tickets: list, provider_name: str) -> int:
    """
    Save normalized ticket data to database.
    Deletes tickets with spam/deleted/trash status.

    Args:
        tickets: List of normalized ticket dicts from provider
        provider_name: Name of the PSA provider

    Returns:
        Number of tickets saved/updated
    """
    from app.psa.mappings import INVALID_STATUS_NAMES

    # Build company mapping (external_id -> account_number)
    company_map = {}
    companies = Company.query.filter_by(external_source=provider_name).all()
    for company in companies:
        if company.external_id:
            company_map[company.external_id] = company.account_number

    count = 0
    deleted_count = 0

    for ticket_data in tickets:
        external_id = ticket_data.get('external_id')
        if not external_id:
            continue

        # Get normalized status (mapped from status_id by provider)
        status = ticket_data.get('status', '').lower()

        # Find existing ticket
        ticket = TicketDetail.query.filter_by(
            external_id=external_id,
            external_source=provider_name
        ).first()

        # If ticket is spam/deleted/trash, delete it from Codex
        # The status is already normalized from status_id by the provider
        if status in INVALID_STATUS_NAMES:
            if ticket:
                log(f"  Deleting ticket #{ticket_data.get('ticket_number')} - status: {status} (status_id: {ticket_data.get('status_id')})")
                db.session.delete(ticket)
                deleted_count += 1
            # Skip creating/updating this ticket
            continue

        # Create or update valid ticket
        if not ticket:
            ticket = TicketDetail()
            db.session.add(ticket)

        # Update fields
        ticket.external_id = external_id
        ticket.external_source = provider_name
        ticket.ticket_number = ticket_data.get('ticket_number')
        ticket.subject = ticket_data.get('subject')
        ticket.description = ticket_data.get('description')
        ticket.description_text = ticket_data.get('description_text')

        # Normalized status/priority
        ticket.status = ticket_data.get('status')
        ticket.priority = ticket_data.get('priority')

        # Original PSA values
        ticket.status_id = ticket_data.get('status_id')
        ticket.priority_id = ticket_data.get('priority_id')

        ticket.ticket_type = ticket_data.get('ticket_type')
        ticket.requester_id = ticket_data.get('requester_id')
        ticket.requester_email = ticket_data.get('requester_email')
        ticket.requester_name = ticket_data.get('requester_name')
        ticket.responder_id = ticket_data.get('responder_id')
        ticket.group_id = ticket_data.get('group_id')

        # Map company
        company_external_id = ticket_data.get('company_id')
        if company_external_id and company_external_id in company_map:
            ticket.company_account_number = company_map[company_external_id]

        # Timestamps
        ticket.created_at = ticket_data.get('created_at')
        ticket.last_updated_at = ticket_data.get('updated_at')
        ticket.closed_at = ticket_data.get('closed_at')

        # SLA fields
        ticket.fr_due_by = ticket_data.get('fr_due_by')
        ticket.due_by = ticket_data.get('due_by')
        ticket.first_responded_at = ticket_data.get('first_responded_at')
        ticket.agent_responded_at = ticket_data.get('agent_responded_at')

        # Time tracking
        ticket.total_hours_spent = ticket_data.get('total_hours_spent', 0)

        # Conversations and notes as JSON
        conversations = ticket_data.get('conversations', [])
        ticket.conversations = json.dumps(conversations) if conversations else None

        notes = ticket_data.get('notes', [])
        ticket.notes = json.dumps(notes) if notes else None

        count += 1

    db.session.commit()

    if deleted_count > 0:
        log(f"  Deleted {deleted_count} spam/deleted/trash tickets from Codex")

    return count


def reconcile_deleted_tickets(provider, provider_name: str) -> dict:
    """
    Reconcile tickets by doing a full query of active tickets from PSA.

    This works like the old ticket-dash system:
    1. Query PSA for ALL tickets with active status IDs
    2. Save/update all those tickets in the database (updates statuses!)
    3. Mark any database ticket NOT in the API results as 'deleted'

    This is the only reliable way to detect deleted/spam tickets since Freshservice
    doesn't return them in incremental syncs - they just disappear.

    Args:
        provider: PSA provider instance (already authenticated)
        provider_name: PSA provider name (e.g., 'freshservice')

    Returns:
        Dict with 'updated' and 'deleted' counts
    """
    from app.psa.mappings import INVALID_STATUS_NAMES

    log("  Running full reconciliation to detect deleted tickets...")

    # Get ALL active tickets from PSA (no 'since' parameter = full active query)
    # This queries for status:[2,3,8,9,10,13,19,23,26,27] - all active statuses
    active_tickets_from_psa = provider.sync_tickets()

    # Save all active tickets - this updates their statuses!
    log(f"  Updating {len(active_tickets_from_psa)} active tickets from PSA...")
    updated_count = save_tickets(active_tickets_from_psa, provider_name)

    # Build set of ticket IDs that PSA says are currently active
    psa_active_ticket_ids = {ticket.get('external_id') for ticket in active_tickets_from_psa if ticket.get('external_id')}
    log(f"  PSA reports {len(psa_active_ticket_ids)} active tickets")

    # Get all tickets from our database that should be active (not already closed/deleted)
    CLOSED_STATUSES = ['closed', 'resolved', 'job_complete_bill', 'billing_complete'] + INVALID_STATUS_NAMES
    db_active_tickets = TicketDetail.query.filter(
        TicketDetail.external_source == provider_name,
        TicketDetail.status.notin_(CLOSED_STATUSES)
    ).all()

    log(f"  Database has {len(db_active_tickets)} tickets in active statuses")

    # Find tickets in database that are NOT in PSA results = deleted/spam tickets
    deleted_count = 0
    for ticket in db_active_tickets:
        if ticket.external_id not in psa_active_ticket_ids:
            log(f"  Marking ticket #{ticket.ticket_number} as deleted (not in PSA active query)")
            ticket.status = 'deleted'
            deleted_count += 1

    if deleted_count > 0:
        db.session.commit()
        log(f"  Marked {deleted_count} tickets as deleted")
    else:
        log("  No deleted tickets found")

    return {'updated': updated_count, 'deleted': deleted_count}


def sync_provider(provider_name: str, sync_type: str, config, full_history: bool = False, force_reconcile: bool = False) -> dict:
    """
    Sync data from a PSA provider.

    Args:
        provider_name: Name of the provider ('freshservice', 'superops')
        sync_type: Type of sync ('companies', 'contacts', 'agents', 'tickets', 'all')
        config: ConfigParser with provider credentials
        full_history: For tickets, fetch all history instead of recent
        force_reconcile: For tickets, always run full reconciliation regardless of sync counter

    Returns:
        Dict with sync results
    """
    results = {
        'provider': provider_name,
        'sync_type': sync_type,
        'success': False,
        'counts': {},
        'errors': []
    }

    try:
        # Get provider
        provider = get_provider(provider_name, config)

        # Authenticate
        log(f"Authenticating with {provider.display_name}...")
        provider.authenticate()
        log("Authentication successful")

        # Determine what to sync
        if sync_type == 'all':
            sync_types = ['companies', 'contacts', 'agents', 'tickets']
        elif sync_type == 'base':
            # Base sync: companies, contacts, agents (no tickets)
            sync_types = ['companies', 'contacts', 'agents']
        else:
            sync_types = [sync_type]

        for st in sync_types:
            log(f"Syncing {st} from {provider.display_name}...")

            try:
                if st == 'companies':
                    data = provider.sync_companies()
                    count = save_companies(data, provider_name)
                    results['counts']['companies'] = count
                    log(f"  Synced {count} companies")

                elif st == 'contacts':
                    data = provider.sync_contacts()
                    count = save_contacts(data, provider_name)
                    results['counts']['contacts'] = count
                    log(f"  Synced {count} contacts")

                elif st == 'agents':
                    data = provider.sync_agents()
                    count = save_agents(data, provider_name)
                    results['counts']['agents'] = count
                    log(f"  Synced {count} agents")

                elif st == 'tickets':
                    # Incremental sync: only fetch tickets updated since last sync
                    if full_history:
                        log("  Full history sync requested")
                        data = provider.sync_tickets(full_history=True)
                    else:
                        # Get last successful sync time
                        last_sync_time = get_last_ticket_sync_time(provider_name)
                        if last_sync_time:
                            log(f"  Incremental sync since {last_sync_time}")
                            data = provider.sync_tickets(since=last_sync_time)
                        else:
                            # No previous sync - fetch all open tickets
                            log("  No previous sync, fetching all open tickets")
                            data = provider.sync_tickets()

                    count = save_tickets(data, provider_name)
                    results['counts']['tickets'] = count
                    log(f"  Synced {count} tickets")

                    # Reconcile deleted tickets - either forced or alternating pattern
                    # Force reconcile = always run (manual GUI button clicks)
                    # Alternating = every other sync for scheduled syncs (detects deletes every 6 min)
                    import os

                    if force_reconcile:
                        # Manual sync from GUI - always run full reconciliation
                        log("  Running full reconciliation (forced by manual sync)")
                        reconcile_results = reconcile_deleted_tickets(provider, provider_name)
                        results['counts']['tickets_reconciled'] = reconcile_results['updated']
                        results['counts']['tickets_cleaned'] = reconcile_results['deleted']
                    else:
                        # Scheduled sync - use alternating pattern to avoid rate limiting
                        # Track sync count using a simple counter file
                        sync_counter_file = os.path.join(app.instance_path, f'{provider_name}_sync_counter.txt')

                        try:
                            if os.path.exists(sync_counter_file):
                                with open(sync_counter_file, 'r') as f:
                                    sync_count = int(f.read().strip())
                            else:
                                sync_count = 0

                            # Increment counter
                            sync_count += 1

                            # Save updated counter
                            with open(sync_counter_file, 'w') as f:
                                f.write(str(sync_count))

                            # Run reconciliation every other sync (even numbers)
                            if sync_count % 2 == 0:
                                log(f"  Running full reconciliation (sync #{sync_count})")
                                reconcile_results = reconcile_deleted_tickets(provider, provider_name)
                                results['counts']['tickets_reconciled'] = reconcile_results['updated']
                                results['counts']['tickets_cleaned'] = reconcile_results['deleted']
                            else:
                                log(f"  Skipping reconciliation (sync #{sync_count}, will run on next sync)")
                                results['counts']['tickets_reconciled'] = 0
                                results['counts']['tickets_cleaned'] = 0

                        except (ValueError, IOError) as e:
                            log(f"  Warning: Could not read sync counter, running reconciliation: {e}")
                            # On error, just run reconciliation to be safe
                            reconcile_results = reconcile_deleted_tickets(provider, provider_name)
                            results['counts']['tickets_reconciled'] = reconcile_results['updated']
                            results['counts']['tickets_cleaned'] = reconcile_results['deleted']

            except Exception as e:
                error_msg = f"Error syncing {st}: {e}"
                log(f"  ERROR: {error_msg}")
                results['errors'].append(error_msg)

        results['success'] = len(results['errors']) == 0

    except PSAProviderError as e:
        error_msg = f"Provider error: {e}"
        log(f"ERROR: {error_msg}")
        results['errors'].append(error_msg)

    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        log(f"ERROR: {error_msg}")
        results['errors'].append(error_msg)

    return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Sync data from PSA systems')
    parser.add_argument('--provider', type=str, help='PSA provider name (freshservice, superops)')
    parser.add_argument('--type', type=str, default='all',
                       choices=['companies', 'contacts', 'agents', 'tickets', 'base', 'all'],
                       help='Type of data to sync (base = companies, contacts, agents without tickets)')
    parser.add_argument('--full-history', action='store_true',
                       help='For tickets, fetch all history instead of recent')
    parser.add_argument('--force-reconcile', action='store_true',
                       help='For tickets, always run full reconciliation to detect deleted tickets')
    parser.add_argument('--all-providers', action='store_true',
                       help='Sync all enabled providers')
    parser.add_argument('--list-providers', action='store_true',
                       help='List available providers')

    args = parser.parse_args()

    with app.app_context():
        # List providers
        if args.list_providers:
            print("Available PSA providers:")
            for provider in list_providers():
                print(f"  - {provider}")
            return 0

        # Load config
        config = app.config.get('CODEX_CONFIG')
        if not config:
            log("ERROR: No configuration found")
            return 1

        # Determine providers to sync
        if args.all_providers:
            # Get enabled providers from config
            providers = config.get('psa', 'enabled_providers', fallback='freshservice').split(',')
            providers = [p.strip() for p in providers]
        elif args.provider:
            providers = [args.provider]
        else:
            log("ERROR: Must specify --provider or --all-providers")
            return 1

        # Run sync for each provider
        all_results = []
        for provider_name in providers:
            log(f"\n{'='*50}")
            log(f"Starting sync for {provider_name}")
            log(f"{'='*50}")

            results = sync_provider(
                provider_name,
                args.type,
                config,
                full_history=args.full_history,
                force_reconcile=args.force_reconcile
            )
            all_results.append(results)

            # Print summary
            log(f"\nSync complete for {provider_name}:")
            for data_type, count in results['counts'].items():
                log(f"  {data_type}: {count}")
            if results['errors']:
                log(f"  Errors: {len(results['errors'])}")

        # Overall status
        success = all(r['success'] for r in all_results)
        return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
