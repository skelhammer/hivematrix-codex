from datetime import datetime, timezone
from flask import render_template, g, jsonify, request
from app import app, limiter
from .auth import token_required, admin_required
from models import Company, Contact, Asset, Location, TicketDetail, SyncJob, BillingPlan, PlanFeature, FeatureOption, PSAAgent
from extensions import db
import subprocess
import os
import sys
import uuid
import threading
import configparser

# Health check library
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from health_check import HealthChecker


def get_default_psa_provider():
    """Get the default PSA provider from configuration.

    Returns:
        str: Provider name (e.g., 'freshservice', 'superops')
    """
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'instance', 'codex.conf')
    config = configparser.RawConfigParser()
    config.read(config_path)
    return config.get('psa', 'default_provider', fallback='freshservice')


@app.route('/')
@token_required
def index():
    """Main dashboard route."""
    if g.is_service_call:
        return {'error': 'This endpoint is for users only'}, 403

    # Get counts for dashboard
    company_count = Company.query.count()
    contact_count = Contact.query.count()
    asset_count = Asset.query.count()
    # Count unique billing plan categories (plan names)
    billing_plan_count = db.session.query(BillingPlan.plan_name).distinct().count()

    return render_template('dashboard.html',
                         user=g.user,
                         company_count=company_count,
                         contact_count=contact_count,
                         asset_count=asset_count,
                         billing_plan_count=billing_plan_count)

def run_sync_script(job_id, script_path, extra_args=None, follow_up_script=None):
    """Run sync script in background and update job status in database."""
    try:
        # Increase timeout for ticket sync (can take 2+ hours)
        timeout = 7200 if 'ticket' in script_path else 600  # 2 hours for tickets, 10 min for others

        # Build command with optional extra arguments
        cmd = ['python', script_path]
        if extra_args:
            cmd.extend(extra_args)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        # Update job in database
        with app.app_context():
            job = db.session.get(SyncJob, job_id)
            if job:
                job.status = 'completed' if result.returncode == 0 else 'failed'
                job.success = result.returncode == 0
                job.output = result.stdout[-1000:]  # Last 1000 chars
                job.error = result.stderr[-1000:] if result.stderr else None
                job.completed_at = datetime.now(timezone.utc).isoformat()
                db.session.commit()

                # Run follow-up script if main script succeeded
                if result.returncode == 0 and follow_up_script:
                    try:
                        follow_result = subprocess.run(
                            ['python', follow_up_script],
                            capture_output=True,
                            text=True,
                            timeout=300  # 5 min timeout for follow-up
                        )
                        # Append follow-up output to job output
                        follow_output = f"\n\n--- Auto-Run Follow-Up ---\n{follow_result.stdout[-500:]}"
                        job.output = (job.output or '') + follow_output
                        db.session.commit()
                    except Exception as e:
                        app.logger.error(f"Follow-up script failed: {e}")

    except subprocess.TimeoutExpired:
        with app.app_context():
            job = db.session.get(SyncJob, job_id)
            if job:
                job.status = 'failed'
                job.success = False
                job.error = f'Script timed out after {timeout//60} minutes'
                job.completed_at = datetime.now(timezone.utc).isoformat()
                db.session.commit()

    except Exception as e:
        with app.app_context():
            job = db.session.get(SyncJob, job_id)
            if job:
                job.status = 'failed'
                job.success = False
                job.error = str(e)
                job.completed_at = datetime.now(timezone.utc).isoformat()
                db.session.commit()

@app.route('/sync/psa', methods=['POST'])
@admin_required
def sync_psa():
    """Trigger PSA sync script in background for the default provider."""
    try:
        job_id = str(uuid.uuid4())
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'sync_psa.py')
        provider = get_default_psa_provider()

        # Create job entry in database
        job = SyncJob(
            id=job_id,
            script='psa',
            provider=provider,
            sync_type='base',
            status='running',
            started_at=datetime.now(timezone.utc).isoformat()
        )
        db.session.add(job)
        db.session.commit()

        # Start background thread with provider arguments (base = companies, contacts, agents only)
        thread = threading.Thread(
            target=run_sync_script,
            args=(job_id, script_path, ['--provider', provider, '--type', 'base'])
        )
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': f'{provider.title()} sync started in background'
        })
    except Exception as e:
        app.logger.error(f"PSA sync failed: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500


@app.route('/sync/datto', methods=['POST'])
@admin_required
def sync_datto():
    """Trigger RMM sync script in background."""
    try:
        job_id = str(uuid.uuid4())
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'sync_rmm.py')
        follow_up_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app', 'rmm', 'push_account_numbers.py')

        # Create job entry in database
        job = SyncJob(
            id=job_id,
            script='datto',
            status='running',
            started_at=datetime.now(timezone.utc).isoformat()
        )
        db.session.add(job)
        db.session.commit()

        # Start background thread with auto-run of push to datto
        thread = threading.Thread(target=run_sync_script, args=(job_id, script_path, None, follow_up_script))
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': 'RMM sync started in background (will auto-push account numbers)'
        })
    except Exception as e:
        app.logger.error(f"Datto sync failed: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/sync/status/<job_id>', methods=['GET'])
@admin_required
def sync_status(job_id):
    """Check status of a background sync job with live progress."""
    job = db.session.get(SyncJob, job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    job_data = {
        'id': job.id,
        'script': job.script,
        'status': job.status,
        'started_at': job.started_at,
        'completed_at': job.completed_at,
        'output': job.output,
        'error': job.error,
        'success': job.success
    }

    # Add current ticket count for ticket syncs to show progress
    if job.script == 'tickets' and job.status == 'running':
        job_data['current_tickets'] = TicketDetail.query.count()

    return jsonify(job_data)

@app.route('/sync/create-account-numbers', methods=['POST'])
@admin_required
def sync_create_account_numbers():
    """Create account numbers for companies that don't have them."""
    try:
        job_id = str(uuid.uuid4())
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app', 'psa', 'create_account_numbers.py')

        # Create job entry in database
        job = SyncJob(
            id=job_id,
            script='create-account-numbers',
            status='running',
            started_at=datetime.now(timezone.utc).isoformat()
        )
        db.session.add(job)
        db.session.commit()

        # Start background thread
        thread = threading.Thread(target=run_sync_script, args=(job_id, script_path))
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': 'Account number creation started in background'
        })
    except Exception as e:
        app.logger.error(f"Account number creation failed: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/sync/push-to-datto', methods=['POST'])
@admin_required
def sync_push_to_datto():
    """Push account numbers to Datto RMM sites."""
    try:
        job_id = str(uuid.uuid4())
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'push_account_nums_to_datto.py')

        # Create job entry in database
        job = SyncJob(
            id=job_id,
            script='push-to-datto',
            status='running',
            started_at=datetime.now(timezone.utc).isoformat()
        )
        db.session.add(job)
        db.session.commit()

        # Start background thread
        thread = threading.Thread(target=run_sync_script, args=(job_id, script_path))
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': 'Push to Datto started in background'
        })
    except Exception as e:
        app.logger.error(f"Push to Datto failed: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500


# --- API Endpoints for Service-to-Service Communication ---

@app.route('/api/companies')
@token_required
def api_get_all_companies():
    """Get all companies - used by Ledger service.
    ---
    tags:
      - Companies
    summary: List all companies
    description: Returns a list of all companies with their billing information
    security:
      - Bearer: []
    responses:
      200:
        description: List of companies retrieved successfully
        schema:
          type: array
          items:
            type: object
            properties:
              account_number:
                type: string
                example: "12345"
              name:
                type: string
                example: "Acme Corporation"
              description:
                type: string
                example: "Technology company"
              billing_plan:
                type: string
                example: "Enterprise"
              contract_term_length:
                type: integer
                example: 12
              contract_start_date:
                type: string
                format: date
                example: "2024-01-01"
              contract_end_date:
                type: string
                format: date
                example: "2024-12-31"
              support_level:
                type: string
                example: "Premium"
              profit_or_non_profit:
                type: string
                example: "Profit"
              company_main_number:
                type: string
                example: "+1-555-0123"
              company_start_date:
                type: string
                format: date
                example: "2020-01-01"
              domains:
                type: string
                example: "acme.com, acmecorp.com"
              phone_system:
                type: string
                example: "VoIP"
              email_system:
                type: string
                example: "Microsoft 365"
      401:
        description: Unauthorized - missing or invalid JWT token
        schema:
          type: object
          properties:
            error:
              type: string
              example: "Unauthorized"
    """
    companies = Company.query.all()
    return jsonify([{
        'account_number': c.account_number,
        'name': c.name,
        'description': c.description,
        'billing_plan': c.plan_selected,
        'contract_term_length': c.contract_term_length,
        'contract_start_date': c.contract_start_date,
        'contract_end_date': c.contract_end_date,
        'support_level': c.support_level,
        'profit_or_non_profit': c.profit_or_non_profit,
        'company_main_number': c.company_main_number,
        'company_start_date': c.company_start_date,
        'domains': c.domains,
        'phone_system': c.phone_system,
        'email_system': c.email_system
    } for c in companies])


@app.route('/api/companies/bulk')
@token_required
def api_get_all_companies_bulk():
    """Get all companies with their assets, contacts, locations, and tickets in one call - optimized for Ledger."""
    import json

    # Get optional query parameters
    include_tickets = request.args.get('include_tickets', 'false').lower() == 'true'
    year = request.args.get('year', type=int)

    companies = Company.query.all()
    result = []

    for company in companies:
        assets = Asset.query.filter_by(company_account_number=company.account_number).all()

        company_data = {
            'company': {
                'account_number': company.account_number,
                'name': company.name,
                'description': company.description,
                'billing_plan': company.plan_selected,
                'contract_term_length': company.contract_term_length,
                'contract_start_date': company.contract_start_date,
                'contract_end_date': company.contract_end_date,
                'support_level': company.support_level,
                'profit_or_non_profit': company.profit_or_non_profit,
                'company_main_number': company.company_main_number,
                'company_start_date': company.company_start_date,
                'domains': company.domains,
                'phone_system': company.phone_system,
                'email_system': company.email_system
            },
            'assets': [{
                'id': a.id,
                'hostname': a.hostname,
                'hardware_type': a.hardware_type,
                'operating_system': a.operating_system,
                'device_type': a.device_type,
                'last_logged_in_user': a.last_logged_in_user,
                'antivirus_product': a.antivirus_product,
                'ext_ip_address': a.ext_ip_address,
                'int_ip_address': a.int_ip_address,
                'domain': a.domain,
                'online': a.online,
                'last_seen': a.last_seen,
                'backup_usage_tb': a.backup_usage_tb,
                'backup_data_bytes': int(float(a.backup_usage_tb or 0) * 1099511627776) if a.backup_usage_tb else 0
            } for a in assets],
            'contacts': [{
                'id': c.id,
                'name': c.name,
                'email': c.email,
                'title': c.title,
                'employment_type': c.employment_type,
                'active': c.active,
                'mobile_phone_number': c.mobile_phone_number,
                'work_phone_number': c.work_phone_number,
                'secondary_emails': c.secondary_emails
            } for c in company.contacts],
            'locations': [{
                'id': l.id,
                'name': l.name,
                'address': l.address,
                'phone_number': l.phone_number
            } for l in company.locations]
        }

        # Optionally include tickets (disabled by default for performance)
        if include_tickets:
            query = TicketDetail.query.filter_by(company_account_number=company.account_number)

            if year:
                tickets = [t for t in query.all() if t.last_updated_at and t.last_updated_at.startswith(str(year))]
            else:
                tickets = query.all()

            company_data['tickets'] = [{
                'ticket_id': t.id,
                'ticket_number': t.ticket_number,
                'subject': t.subject,
                'description': t.description,
                'description_text': t.description_text,
                'status': t.status,
                'priority': t.priority,
                'requester_email': t.requester_email,
                'requester_name': t.requester_name,
                'created_at': t.created_at,
                'last_updated_at': t.last_updated_at,
                'closed_at': t.closed_at,
                'total_hours_spent': float(t.total_hours_spent or 0),
                'conversations': json.loads(t.conversations) if t.conversations else [],
                'notes': json.loads(t.notes) if t.notes else []
            } for t in tickets]

        result.append(company_data)

    return jsonify(result)


@app.route('/api/companies/<account_number>')
@token_required
def api_get_company(account_number):
    """Get single company by account number - used by Ledger service.
    ---
    tags:
      - Companies
    summary: Get company by account number
    description: |
      Retrieves detailed information for a single company identified by account number.
      Used by Ledger service for billing operations and by other services for company lookups.
    security:
      - Bearer: []
    parameters:
      - name: account_number
        in: path
        type: string
        required: true
        description: The company's account number (primary key)
        example: "12345"
    responses:
      200:
        description: Company details retrieved successfully
        schema:
          type: object
          properties:
            account_number:
              type: string
              example: "12345"
            name:
              type: string
              example: "Acme Corporation"
            description:
              type: string
              example: "Technology consulting firm"
            billing_plan:
              type: string
              example: "per_user"
            contract_term_length:
              type: integer
              example: 12
            contract_start_date:
              type: string
              format: date
              example: "2024-01-01"
            contract_end_date:
              type: string
              format: date
              example: "2024-12-31"
            support_level:
              type: string
              example: "Standard"
            profit_or_non_profit:
              type: string
              example: "profit"
            company_main_number:
              type: string
              example: "+1-555-123-4567"
            company_start_date:
              type: string
              format: date
              example: "2024-01-01"
            domains:
              type: string
              example: "acme.com, acmecorp.net"
            phone_system:
              type: string
              example: "VoIP"
            email_system:
              type: string
              example: "Microsoft 365"
      404:
        description: Company not found
        schema:
          type: object
          properties:
            error:
              type: string
              example: "Company not found"
      401:
        description: Unauthorized - Invalid or missing JWT token
    """
    company = Company.query.get(account_number)
    if not company:
        return {'error': 'Company not found'}, 404

    return jsonify({
        'account_number': company.account_number,
        'name': company.name,
        'description': company.description,
        'billing_plan': company.plan_selected,
        'contract_term_length': company.contract_term_length,
        'contract_start_date': company.contract_start_date,
        'contract_end_date': company.contract_end_date,
        'support_level': company.support_level,
        'profit_or_non_profit': company.profit_or_non_profit,
        'company_main_number': company.company_main_number,
        'company_start_date': company.company_start_date,
        'domains': company.domains,
        'phone_system': company.phone_system,
        'email_system': company.email_system
    })


@app.route('/api/companies/<account_number>/assets')
@token_required
def api_get_company_assets(account_number):
    """Get all assets for a company - used by Ledger service.
    ---
    tags:
      - Companies
      - Assets
    summary: Get all assets for a company
    description: |
      Retrieves all assets (computers, devices) associated with a specific company.
      Used by Ledger for user count billing and by other services for asset management.

      Assets are synced from RMM systems (Datto) and include hardware/software inventory.
    security:
      - Bearer: []
    parameters:
      - name: account_number
        in: path
        type: string
        required: true
        description: The company's account number
        example: "12345"
    responses:
      200:
        description: List of assets retrieved successfully
        schema:
          type: array
          items:
            type: object
            properties:
              id:
                type: integer
                example: 42
              hostname:
                type: string
                example: "DESKTOP-ABC123"
              hardware_type:
                type: string
                example: "Desktop"
              operating_system:
                type: string
                example: "Windows 11 Pro"
              device_type:
                type: string
                example: "Workstation"
              last_logged_in_user:
                type: string
                example: "jsmith"
              antivirus_product:
                type: string
                example: "Windows Defender"
              ext_ip_address:
                type: string
                example: "203.0.113.45"
              int_ip_address:
                type: string
                example: "192.168.1.100"
              domain:
                type: string
                example: "ACME"
              online:
                type: boolean
                example: true
              last_seen:
                type: string
                format: date-time
                example: "2025-11-22T10:30:00Z"
              backup_usage_tb:
                type: number
                format: float
                example: 0.5
              backup_data_bytes:
                type: integer
                example: 549755813888
      404:
        description: Company not found
        schema:
          type: object
          properties:
            error:
              type: string
              example: "Company not found"
      401:
        description: Unauthorized - Invalid or missing JWT token
    """
    company = Company.query.get(account_number)
    if not company:
        return {'error': 'Company not found'}, 404

    assets = Asset.query.filter_by(company_account_number=account_number).all()
    return jsonify([{
        'id': a.id,
        'hostname': a.hostname,
        'hardware_type': a.hardware_type,
        'operating_system': a.operating_system,
        'device_type': a.device_type,
        'last_logged_in_user': a.last_logged_in_user,
        'antivirus_product': a.antivirus_product,
        'ext_ip_address': a.ext_ip_address,
        'int_ip_address': a.int_ip_address,
        'domain': a.domain,
        'online': a.online,
        'last_seen': a.last_seen,
        'backup_usage_tb': a.backup_usage_tb,
        'backup_data_bytes': int(float(a.backup_usage_tb or 0) * 1099511627776) if a.backup_usage_tb else 0
    } for a in assets])


@app.route('/api/companies/<account_number>/contacts')
@token_required
def api_get_company_contacts(account_number):
    """Get all contacts for a company - used by Ledger service.
    ---
    tags:
      - Companies
      - Contacts
    summary: Get all contacts for a company
    description: |
      Retrieves all contacts (employees, users) associated with a specific company.
      Used by Ledger for per-user billing calculations and by other services for contact lookups.

      Contacts are synced from PSA systems and include employment information.
    security:
      - Bearer: []
    parameters:
      - name: account_number
        in: path
        type: string
        required: true
        description: The company's account number
        example: "12345"
    responses:
      200:
        description: List of contacts retrieved successfully
        schema:
          type: array
          items:
            type: object
            properties:
              id:
                type: integer
                example: 42
              name:
                type: string
                example: "John Smith"
              email:
                type: string
                format: email
                example: "jsmith@acme.com"
              title:
                type: string
                example: "IT Manager"
              employment_type:
                type: string
                example: "Full Time"
              active:
                type: boolean
                example: true
              mobile_phone_number:
                type: string
                example: "+1-555-123-4567"
              work_phone_number:
                type: string
                example: "+1-555-987-6543"
              secondary_emails:
                type: string
                example: "john.smith@acme.com, j.smith@acme.com"
      404:
        description: Company not found
        schema:
          type: object
          properties:
            error:
              type: string
              example: "Company not found"
      401:
        description: Unauthorized - Invalid or missing JWT token
    """
    company = Company.query.get(account_number)
    if not company:
        return {'error': 'Company not found'}, 404

    return jsonify([{
        'id': c.id,
        'name': c.name,
        'email': c.email,
        'title': c.title,
        'employment_type': c.employment_type,
        'active': c.active,
        'mobile_phone_number': c.mobile_phone_number,
        'work_phone_number': c.work_phone_number,
        'secondary_emails': c.secondary_emails
    } for c in company.contacts])


@app.route('/api/companies/<account_number>/users')
@token_required
def api_get_company_users(account_number):
    """Alias for api_get_company_contacts - 'users' is more intuitive for KnowledgeTree."""
    return api_get_company_contacts(account_number)


@app.route('/api/companies/<account_number>/locations')
@token_required
def api_get_company_locations(account_number):
    """Get all locations for a company - used by Ledger service."""
    company = Company.query.get(account_number)
    if not company:
        return {'error': 'Company not found'}, 404

    return jsonify([{
        'id': l.id,
        'name': l.name,
        'address': l.address,
        'phone_number': l.phone_number
    } for l in company.locations])


@app.route('/api/companies/<account_number>/tickets')
@token_required
def api_get_company_tickets(account_number):
    """Get all tickets for a company - used by Ledger service."""
    company = Company.query.get(account_number)
    if not company:
        return {'error': 'Company not found'}, 404

    # Get optional year filter
    year = request.args.get('year', type=int)

    query = TicketDetail.query.filter_by(company_account_number=account_number)

    if year:
        # Filter by year using string substring matching (since last_updated_at is stored as string)
        tickets = [t for t in query.all() if t.last_updated_at and t.last_updated_at.startswith(str(year))]
    else:
        tickets = query.all()

    import json
    return jsonify([{
        'ticket_id': t.id,
        'ticket_number': t.ticket_number,
        'subject': t.subject,
        'description': t.description,
        'description_text': t.description_text,
        'status': t.status,
        'priority': t.priority,
        'requester_email': t.requester_email,
        'requester_name': t.requester_name,
        'created_at': t.created_at,
        'last_updated_at': t.last_updated_at,
        'closed_at': t.closed_at,
        'total_hours_spent': float(t.total_hours_spent or 0),
        'conversations': json.loads(t.conversations) if t.conversations else [],
        'notes': json.loads(t.notes) if t.notes else []
    } for t in tickets])


@app.route('/sync/tickets', methods=['POST'])
@admin_required
def sync_tickets():
    """Trigger PSA ticket sync script in background."""
    try:
        job_id = str(uuid.uuid4())
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'sync_psa.py')
        provider = get_default_psa_provider()

        # Create job entry in database
        job = SyncJob(
            id=job_id,
            script='psa',
            provider=provider,
            sync_type='tickets',
            status='running',
            started_at=datetime.now(timezone.utc).isoformat()
        )
        db.session.add(job)
        db.session.commit()

        # Start background thread
        thread = threading.Thread(
            target=run_sync_script,
            args=(job_id, script_path, ['--provider', provider, '--type', 'tickets'])
        )
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': f'{provider.title()} ticket sync started in background'
        })
    except Exception as e:
        app.logger.error(f"Ticket sync failed: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500


@app.route('/sync/tickets/full-history', methods=['POST'])
@admin_required
def sync_tickets_full_history():
    """Trigger full history ticket sync in background."""
    try:
        job_id = str(uuid.uuid4())
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'sync_psa.py')
        provider = get_default_psa_provider()

        # Create job entry in database
        job = SyncJob(
            id=job_id,
            script='psa',
            provider=provider,
            sync_type='tickets',
            status='running',
            started_at=datetime.now(timezone.utc).isoformat()
        )
        db.session.add(job)
        db.session.commit()

        # Start background thread with --full-history flag
        thread = threading.Thread(
            target=run_sync_script,
            args=(job_id, script_path, ['--provider', provider, '--type', 'tickets', '--full-history'])
        )
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': f'{provider.title()} full history ticket sync started in background'
        })
    except Exception as e:
        app.logger.error(f"Full history ticket sync failed: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500


@app.route('/sync/agents', methods=['POST'])
@admin_required
def sync_keycloak_agents():
    """Trigger Keycloak agent sync in background."""
    import requests as http_requests

    def run_agent_sync(job_id):
        """Background function to sync agents from Keycloak."""
        with app.app_context():
            from models import Agent

            try:
                # Get Keycloak admin token
                # Use KEYCLOAK_BACKEND_URL for direct server-to-server communication
                keycloak_url = app.config.get('KEYCLOAK_BACKEND_URL', 'http://localhost:8080')
                admin_user = app.config.get('KEYCLOAK_ADMIN_USER', 'admin')
                admin_pass = app.config.get('KEYCLOAK_ADMIN_PASS', 'admin')
                realm = app.config.get('KEYCLOAK_REALM', 'hivematrix')

                # Get SSL verification setting (for development with self-signed certs)
                verify_ssl = app.config.get('VERIFY_SSL', True)

                token_url = f"{keycloak_url}/realms/master/protocol/openid-connect/token"

                output_lines = ["Starting Keycloak agent sync...\n"]

                # Get admin token
                response = http_requests.post(token_url, data={
                    'client_id': 'admin-cli',
                    'username': admin_user,
                    'password': admin_pass,
                    'grant_type': 'password'
                }, verify=verify_ssl, timeout=5)

                if response.status_code != 200:
                    raise Exception(f"Failed to get Keycloak admin token: {response.status_code}")

                token = response.json().get('access_token')
                output_lines.append("Got Keycloak admin token\n")

                # Get users from Keycloak
                users_url = f"{keycloak_url}/admin/realms/{realm}/users"
                headers = {'Authorization': f'Bearer {token}'}

                response = http_requests.get(users_url, headers=headers, verify=verify_ssl, timeout=10)

                if response.status_code != 200:
                    raise Exception(f"Failed to fetch users from Keycloak: {response.status_code}")

                keycloak_users = response.json()
                output_lines.append(f"Found {len(keycloak_users)} users in Keycloak\n")

                # Sync users to database
                synced = 0
                created = 0
                updated = 0
                errors = []

                now = datetime.now().isoformat()

                for kc_user in keycloak_users:
                    try:
                        agent = Agent.query.filter_by(keycloak_id=kc_user['id']).first()

                        if agent:
                            agent.username = kc_user.get('username', agent.username)
                            agent.email = kc_user.get('email', agent.email)
                            agent.first_name = kc_user.get('firstName', '')
                            agent.last_name = kc_user.get('lastName', '')
                            agent.enabled = kc_user.get('enabled', True)
                            agent.updated_at = now
                            agent.last_synced_at = now
                            updated += 1
                        else:
                            agent = Agent(
                                keycloak_id=kc_user['id'],
                                username=kc_user.get('username', ''),
                                email=kc_user.get('email', ''),
                                first_name=kc_user.get('firstName', ''),
                                last_name=kc_user.get('lastName', ''),
                                enabled=kc_user.get('enabled', True),
                                theme_preference='light',
                                created_at=now,
                                updated_at=now,
                                last_synced_at=now
                            )
                            db.session.add(agent)
                            created += 1

                        synced += 1
                    except Exception as e:
                        errors.append(f"Error syncing {kc_user.get('username')}: {str(e)}")

                db.session.commit()

                output_lines.append(f"\nSync complete:\n")
                output_lines.append(f"  Synced: {synced}\n")
                output_lines.append(f"  Created: {created}\n")
                output_lines.append(f"  Updated: {updated}\n")

                if errors:
                    output_lines.append(f"\nErrors ({len(errors)}):\n")
                    for err in errors:
                        output_lines.append(f"  - {err}\n")

                # Update job status
                job = db.session.get(SyncJob, job_id)
                if job:
                    job.status = 'completed'
                    job.completed_at = datetime.now(timezone.utc).isoformat()
                    job.output = ''.join(output_lines)
                    job.success = len(errors) == 0
                    db.session.commit()

            except Exception as e:
                job = db.session.get(SyncJob, job_id)
                if job:
                    job.status = 'failed'
                    job.completed_at = datetime.now(timezone.utc).isoformat()
                    job.error = str(e)
                    job.success = False
                    db.session.commit()

    try:
        job_id = str(uuid.uuid4())

        # Create job entry in database
        job = SyncJob(
            id=job_id,
            script='keycloak_agents',
            status='running',
            started_at=datetime.now(timezone.utc).isoformat()
        )
        db.session.add(job)
        db.session.commit()

        # Start background thread
        thread = threading.Thread(target=run_agent_sync, args=(job_id,))
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': 'Keycloak agent sync started in background'
        })
    except Exception as e:
        app.logger.error(f"Keycloak agent sync failed: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500


@app.route('/sync/last/<script_name>', methods=['GET'])
@token_required
def get_last_sync(script_name):
    """Get the last sync job for a specific script (persists across page loads)."""
    job = SyncJob.query.filter_by(script=script_name).order_by(SyncJob.started_at.desc()).first()

    if not job:
        return jsonify({'error': 'No sync found for this script'}), 404

    return jsonify({
        'id': job.id,
        'script': job.script,
        'status': job.status,
        'started_at': job.started_at,
        'completed_at': job.completed_at,
        'output': job.output,
        'error': job.error,
        'success': job.success
    })

@app.route('/api/tickets', methods=['GET'])
@token_required
def api_list_tickets():
    """List all tickets with optional filtering - used by Beacon dashboard.
    ---
    tags:
      - Tickets
    summary: List all tickets with filtering and pagination
    description: |
      Retrieves tickets from PSA system with optional filtering by company, status, and priority.
      Used by Beacon service for real-time ticket dashboard display.

      Tickets are synced from PSA systems and updated periodically.
    security:
      - Bearer: []
    parameters:
      - name: company_id
        in: query
        type: string
        required: false
        description: Filter by company account number
        example: "12345"
      - name: status
        in: query
        type: string
        required: false
        description: Filter by ticket status
        example: "Open"
      - name: priority
        in: query
        type: string
        required: false
        description: Filter by ticket priority
        example: "High"
      - name: limit
        in: query
        type: integer
        required: false
        default: 50
        description: Maximum number of tickets to return
        example: 50
      - name: offset
        in: query
        type: integer
        required: false
        default: 0
        description: Number of tickets to skip for pagination
        example: 0
    responses:
      200:
        description: List of tickets retrieved successfully
        schema:
          type: object
          properties:
            tickets:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                    example: 42
                  ticket_number:
                    type: string
                    example: "TKT-12345"
                  subject:
                    type: string
                    example: "Cannot access email"
                  description_text:
                    type: string
                    example: "User reports unable to login to Outlook"
                  status:
                    type: string
                    example: "Open"
                  priority:
                    type: string
                    example: "Medium"
                  company_id:
                    type: string
                    example: "12345"
                  requester_email:
                    type: string
                    format: email
                    example: "jsmith@acme.com"
                  requester_name:
                    type: string
                    example: "John Smith"
                  created_at:
                    type: string
                    format: date-time
                    example: "2025-11-22T09:00:00Z"
                  last_updated_at:
                    type: string
                    format: date-time
                    example: "2025-11-22T10:30:00Z"
                  closed_at:
                    type: string
                    format: date-time
                    example: null
                  total_hours_spent:
                    type: number
                    format: float
                    example: 1.5
            count:
              type: integer
              description: Number of tickets returned in this response
              example: 10
            total:
              type: integer
              description: Total number of tickets matching the filter
              example: 145
            offset:
              type: integer
              example: 0
            limit:
              type: integer
              example: 50
      401:
        description: Unauthorized - Invalid or missing JWT token
    """
    import json

    # Get query parameters
    company_id = request.args.get('company_id')
    status = request.args.get('status')
    priority = request.args.get('priority')
    limit = request.args.get('limit', type=int, default=50)
    offset = request.args.get('offset', type=int, default=0)

    # Build query
    query = TicketDetail.query

    if company_id:
        query = query.filter_by(company_account_number=company_id)
    if status:
        query = query.filter_by(status=status)
    if priority:
        query = query.filter_by(priority=priority)

    # Order by last updated (most recent first)
    query = query.order_by(TicketDetail.last_updated_at.desc())

    # Get total count
    total_count = query.count()

    # Apply pagination
    tickets = query.offset(offset).limit(limit).all()

    return jsonify({
        'tickets': [{
            'id': t.id,
            'ticket_number': t.ticket_number,
            'subject': t.subject,
            'description_text': t.description_text,
            'status': t.status,
            'priority': t.priority,
            'company_id': t.company_account_number,
            'requester_email': t.requester_email,
            'requester_name': t.requester_name,
            'created_at': t.created_at,
            'last_updated_at': t.last_updated_at,
            'closed_at': t.closed_at,
            'total_hours_spent': float(t.total_hours_spent or 0)
        } for t in tickets],
        'count': len(tickets),
        'total': total_count,
        'offset': offset,
        'limit': limit
    })


@app.route('/api/tickets/active', methods=['GET'])
@token_required
def api_active_tickets():
    """
    Get all active (non-closed) tickets for the Beacon dashboard.

    Query parameters:
        group_id: Filter by group/department ID
        responder_id: Filter by assigned agent ID

    Returns tickets organized into 4 sections with full SLA processing:
        section1: Needs first response or further action
        section2: Waiting on agent (customer replied)
        section3: Update overdue
        section4: Other active (on hold, waiting customer, etc.)
    """
    import json
    from datetime import datetime, timezone, timedelta

    # Get query parameters
    group_id = request.args.get('group_id', type=int)
    responder_id = request.args.get('responder_id', type=int)

    # Import PSA mappings for display names
    from app.psa.mappings import get_status_display_name, get_priority_display_name

    # SLA thresholds by normalized priority (time since last update)
    SLA_UPDATE_THRESHOLDS = {
        'urgent': timedelta(minutes=30),
        'high': timedelta(days=2),
        'medium': timedelta(days=3),
        'low': timedelta(days=4)
    }

    # FR SLA thresholds
    FR_SLA_CRITICAL_HOURS = 4
    FR_SLA_WARNING_HOURS = 12

    # Closed/resolved statuses to exclude from active tickets
    # Includes spam/deleted tickets that may still be in database
    CLOSED_STATUSES = ['closed', 'resolved', 'job_complete_bill', 'billing_complete', 'spam', 'trash', 'deleted']

    # Load agent mapping from database (all providers)
    agent_mapping = {}
    agents = PSAAgent.query.filter_by(active=True).all()
    for agent in agents:
        agent_mapping[agent.external_id] = agent.name

    # Load requester mapping from contacts
    requester_mapping = {}
    contacts = Contact.query.all()
    for contact in contacts:
        if contact.external_id:
            requester_mapping[contact.external_id] = contact.name

    # Build base query - all non-closed tickets using normalized status
    query = TicketDetail.query.filter(
        TicketDetail.status.notin_(CLOSED_STATUSES)
    )

    if group_id:
        query = query.filter_by(group_id=group_id)
    if responder_id:
        query = query.filter_by(responder_id=responder_id)

    tickets = query.all()
    now = datetime.now(timezone.utc)

    def parse_datetime(dt_str):
        """Parse datetime string to datetime object."""
        if not dt_str:
            return None
        try:
            if dt_str.endswith('Z'):
                dt_str = dt_str[:-1] + '+00:00'
            return datetime.fromisoformat(dt_str)
        except (ValueError, TypeError):
            return None

    def time_since(dt_obj):
        """Get friendly time since string."""
        if not dt_obj:
            return 'N/A'
        diff = now - dt_obj
        seconds = diff.total_seconds()
        days = diff.days

        if days < 0:
            return 'in the future'
        if days >= 1:
            return f'{days}d ago'
        if seconds >= 3600:
            return f'{int(seconds // 3600)}h ago'
        if seconds >= 60:
            return f'{int(seconds // 60)}m ago'
        return 'Just now'

    def days_since(dt_obj):
        """Get days old string."""
        if not dt_obj:
            return 'N/A'
        diff_days = (now.date() - dt_obj.date()).days

        if diff_days < 0:
            return 'Future Date'
        if diff_days == 0:
            return 'Today'
        if diff_days == 1:
            return '1 day old'
        return f'{diff_days} days old'

    def get_fr_sla_details(ticket_type, target_due_dt):
        """Calculate FR SLA status."""
        sla_prefix = 'Due' if ticket_type == 'Service Request' else 'FR'

        if not target_due_dt:
            return f'No {sla_prefix} Due Date', 'sla-none', float('inf')

        time_diff_seconds = (target_due_dt - now).total_seconds()
        hours_remaining = time_diff_seconds / 3600.0

        # Format time remaining
        if abs(time_diff_seconds) >= (2 * 24 * 60 * 60):
            formatted = f'{hours_remaining / 24.0:.1f} days'
        elif abs(time_diff_seconds) >= 3600:
            formatted = f'{hours_remaining:.1f} hours'
        elif abs(time_diff_seconds) >= 60:
            formatted = f'{time_diff_seconds / 60.0:.0f} min'
        else:
            formatted = f'{time_diff_seconds:.0f} sec'

        if hours_remaining < 0:
            return f'{sla_prefix} Overdue by {formatted.lstrip("-")}', 'sla-overdue', hours_remaining
        elif hours_remaining < FR_SLA_CRITICAL_HOURS:
            return f'{formatted} for {sla_prefix}', 'sla-critical', hours_remaining
        elif hours_remaining < FR_SLA_WARNING_HOURS:
            return f'{formatted} for {sla_prefix}', 'sla-warning', hours_remaining
        else:
            return f'{formatted} for {sla_prefix}', 'sla-normal', hours_remaining

    def serialize_ticket(t, sla_text, sla_class):
        """Serialize ticket with all processed fields."""
        updated_dt = parse_datetime(t.last_updated_at)
        created_dt = parse_datetime(t.created_at)
        agent_responded_dt = parse_datetime(t.agent_responded_at)

        # Get agent name from mapping or use ID fallback
        agent_name = 'Unassigned'
        if t.responder_id:
            agent_name = agent_mapping.get(t.responder_id, f'Agent {t.responder_id}')

        # Get requester name from ticket or lookup from contacts
        requester_name = t.requester_name
        if not requester_name and t.requester_id:
            requester_name = requester_mapping.get(t.requester_id, f'Requester {t.requester_id}')
        elif not requester_name:
            requester_name = 'N/A'

        # Get display names using PSA mappings
        source = getattr(t, 'external_source', None) or get_default_psa_provider()
        status_text = get_status_display_name(t.status, source)
        priority_text = get_priority_display_name(t.priority, source)

        return {
            'id': t.external_id,  # Use external_id as the ticket ID
            'ticket_number': t.ticket_number,
            'subject': t.subject,
            'description_text': t.description_text,
            'status': t.status,
            'status_id': t.status_id,  # Keep for backward compatibility
            'status_text': status_text,
            'priority': t.priority,
            'priority_id': t.priority_id,  # Keep for backward compatibility
            'priority_raw': t.priority_id,
            'priority_text': priority_text,
            'type': t.ticket_type,
            'ticket_type': t.ticket_type,
            'company_id': t.company_account_number,
            'requester_id': t.requester_id,
            'requester_email': t.requester_email,
            'requester_name': requester_name,
            'responder_id': t.responder_id,
            'agent_name': agent_name,
            'group_id': t.group_id,
            'source': source,  # Add PSA source
            'created_at_str': t.created_at,
            'updated_at_str': t.last_updated_at,
            'fr_due_by_str': t.fr_due_by,
            'due_by_str': t.due_by,
            'first_responded_at_iso': t.first_responded_at,
            'agent_responded_at': t.agent_responded_at,
            'updated_friendly': time_since(updated_dt),
            'created_days_old': days_since(created_dt),
            'agent_responded_friendly': time_since(agent_responded_dt),
            'sla_text': sla_text,
            'sla_class': sla_class,
            'total_hours_spent': float(t.total_hours_spent or 0)
        }

    # Categorize tickets into sections
    section1 = []  # Needs first response or action
    section2 = []  # Waiting on agent (customer replied)
    section3 = []  # Update overdue
    section4 = []  # Other active

    for ticket in tickets:
        updated_dt = parse_datetime(ticket.last_updated_at)
        source = getattr(ticket, 'external_source', None) or get_default_psa_provider()
        status_text = get_status_display_name(ticket.status, source)
        updated_friendly = time_since(updated_dt)

        # Check if update is overdue based on normalized priority
        is_update_overdue = False
        if updated_dt and ticket.priority:
            threshold = SLA_UPDATE_THRESHOLDS.get(ticket.priority, timedelta(days=3))
            is_update_overdue = (now - updated_dt) > threshold

        # Section 2: Customer Replied (Waiting on Agent)
        if ticket.status == 'customer_replied':
            sla_text = f'Customer Replied ({updated_friendly})'
            sla_class = 'sla-warning'
            section2.append(serialize_ticket(ticket, sla_text, sla_class))
            continue

        # Section 4: Pending Hubspot (special status)
        if ticket.status == 'pending_hubspot':
            sla_text = f'Pending Hubspot ({updated_friendly})'
            sla_class = 'sla-none'
            section4.append(serialize_ticket(ticket, sla_text, sla_class))
            continue

        # Section 3: Update overdue (but not for Pending Hubspot)
        if is_update_overdue and ticket.status != 'pending_hubspot':
            sla_text = f'Update Overdue ({status_text}, {updated_friendly})'
            sla_class = 'sla-critical'
            section3.append(serialize_ticket(ticket, sla_text, sla_class))
            continue

        # Section 1: Open tickets needing first response or action
        if ticket.status in ['open', 'update_needed', 'pending']:
            needs_fr = not ticket.first_responded_at

            if needs_fr:
                # Calculate FR SLA
                sla_target = ticket.due_by if ticket.ticket_type == 'Service Request' else ticket.fr_due_by
                sla_target_dt = parse_datetime(sla_target)
                sla_text, sla_class, _ = get_fr_sla_details(ticket.ticket_type, sla_target_dt)
            else:
                sla_text = f'{status_text} (FR Met)'
                sla_class = 'sla-responded'

            section1.append(serialize_ticket(ticket, sla_text, sla_class))
            continue

        # Section 4: Other active (Waiting on Customer, On Hold, etc.)
        if ticket.status == 'waiting_customer':
            agent_responded_dt = parse_datetime(ticket.agent_responded_at)
            agent_responded_friendly = time_since(agent_responded_dt)
            sla_text = 'Waiting on Customer'
            if agent_responded_friendly != 'N/A':
                sla_text += f' (Agent: {agent_responded_friendly})'
            sla_class = 'sla-responded'
        elif ticket.status == 'on_hold':
            sla_text = f'On Hold ({updated_friendly})'
            sla_class = 'sla-none'
        else:
            sla_text = f'{status_text} ({updated_friendly})'
            sla_class = 'sla-in-progress'

        section4.append(serialize_ticket(ticket, sla_text, sla_class))

    # Sort sections by priority (urgent first) then by updated time
    def sort_key(t):
        priority = t.get('priority_raw', 1) or 1
        # For section 1, also consider FR SLA urgency
        updated = t.get('updated_at_str', '') or ''
        return (-(priority or 1), updated)

    section1.sort(key=sort_key)
    section2.sort(key=sort_key)
    section3.sort(key=sort_key)
    section4.sort(key=sort_key)

    # Get the last successful ticket sync time (check both old and new formats)
    last_sync = SyncJob.query.filter(
        db.or_(
            db.and_(SyncJob.script == 'tickets', SyncJob.status == 'completed'),
            db.and_(SyncJob.script == 'psa', SyncJob.sync_type == 'tickets', SyncJob.status == 'completed')
        )
    ).order_by(SyncJob.completed_at.desc()).first()

    last_sync_time = last_sync.completed_at if last_sync else None

    return jsonify({
        'section1': section1,
        'section2': section2,
        'section3': section3,
        'section4': section4,
        'total_active': len(tickets),
        'last_updated': now.isoformat(),
        'last_sync_time': last_sync_time
    })


@app.route('/api/ticket/<int:ticket_id>', methods=['GET'])
@token_required
def api_get_ticket(ticket_id):
    """
    Get detailed information about a specific ticket.

    Includes conversations and notes.
    If ticket is not in local database, fetches from configured PSA provider.
    """
    import json
    import configparser
    import os
    from app.psa import get_provider
    from app.psa.mappings import get_status_display_name, get_priority_display_name

    # First, try to get from local database by external_id
    ticket = TicketDetail.query.filter_by(external_id=ticket_id).first()
    if ticket:
        # Get company info
        company = Company.query.get(ticket.company_account_number)
        source = ticket.external_source or get_default_psa_provider()

        return jsonify({
            'id': ticket.external_id,
            'ticket_number': ticket.ticket_number,
            'subject': ticket.subject,
            'description': ticket.description,
            'description_text': ticket.description_text,
            'status': ticket.status,
            'status_text': get_status_display_name(ticket.status, source),
            'priority': ticket.priority,
            'priority_text': get_priority_display_name(ticket.priority, source),
            'company_id': ticket.company_account_number,
            'company_name': company.name if company else None,
            'requester_email': ticket.requester_email,
            'requester_name': ticket.requester_name,
            'created_at': ticket.created_at,
            'last_updated_at': ticket.last_updated_at,
            'closed_at': ticket.closed_at,
            'total_hours_spent': float(ticket.total_hours_spent or 0),
            'conversations': json.loads(ticket.conversations) if ticket.conversations else [],
            'notes': json.loads(ticket.notes) if ticket.notes else [],
            'source': source
        })

    # Ticket not in local database - fetch from PSA provider
    app.logger.info(f"Ticket {ticket_id} not found locally, fetching from PSA provider...")

    # Load config and get default provider
    config_path = os.path.join(app.instance_path, 'codex.conf')
    config = configparser.RawConfigParser()
    config.read(config_path)

    # Use configured default provider (fallback to freshservice)
    default_provider = config.get('psa', 'default_provider', fallback='freshservice')

    try:
        provider = get_provider(default_provider, config)
        ticket_data = provider.get_ticket(ticket_id)

        if not ticket_data:
            return {'error': 'Ticket not found'}, 404

        # Return normalized ticket data
        return jsonify(ticket_data)
    except Exception as e:
        app.logger.error(f"Error fetching ticket from provider: {e}")
        return {'error': 'Failed to fetch ticket from PSA'}, 500


@app.route('/api/ticket/<int:ticket_id>/update', methods=['POST'])
@token_required
def api_update_ticket(ticket_id):
    """
    Update a ticket.

    Request body:
        status: New status (optional)
        notes: Note to add (optional)
        assigned_to: Assign to user (optional) - Note: Not stored in current schema
    """
    import json

    ticket = TicketDetail.query.get(ticket_id)
    if not ticket:
        return {'error': 'Ticket not found'}, 404

    data = request.get_json() or {}

    # Update status if provided
    if 'status' in data:
        ticket.status = data['status']
        ticket.last_updated_at = datetime.now().isoformat()

    # Add note if provided
    if 'notes' in data and data['notes']:
        current_notes = json.loads(ticket.notes) if ticket.notes else []
        new_note = {
            'created_at': datetime.now().isoformat(),
            'text': data['notes'],
            'user': g.user.get('preferred_username', 'unknown') if hasattr(g, 'user') and g.user else 'system'
        }
        current_notes.append(new_note)
        ticket.notes = json.dumps(current_notes)
        ticket.last_updated_at = datetime.now().isoformat()

    # Commit changes
    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'ticket_id': ticket_id,
            'message': 'Ticket updated successfully'
        })
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Failed to update ticket: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500


@app.route('/api/datto/devices', methods=['GET'])
@token_required
def api_list_devices():
    """
    List all devices from Datto RMM (currently uses Asset data).

    Query parameters:
        company_id: Filter by company account number
        status: Filter by status ('online', 'offline')
        limit: Maximum number of devices to return (default 100)
    """
    # Get query parameters
    company_id = request.args.get('company_id')
    status = request.args.get('status')
    limit = request.args.get('limit', type=int, default=100)

    # Build query
    query = Asset.query

    if company_id:
        query = query.filter_by(company_account_number=company_id)

    if status:
        if status.lower() == 'online':
            query = query.filter_by(online=True)
        elif status.lower() == 'offline':
            query = query.filter_by(online=False)

    # Get devices
    assets = query.limit(limit).all()

    return jsonify({
        'devices': [{
            'id': f"device-{a.id}",
            'name': a.hostname,
            'company_id': a.company_account_number,
            'company_name': a.company.name if a.company else None,
            'status': 'online' if a.online else 'offline',
            'os': a.operating_system,
            'device_type': a.device_type or a.hardware_type,
            'ip_address': a.ext_ip_address or a.int_ip_address,
            'last_seen': a.last_seen,
            'last_logged_in_user': a.last_logged_in_user
        } for a in assets],
        'count': len(assets)
    })


@app.route('/api/datto/device/<device_id>', methods=['GET'])
@token_required
def api_get_device(device_id):
    """
    Get detailed information about a specific device.

    Device ID format: "device-{asset_id}"
    """
    # Extract asset ID from device ID
    if not device_id.startswith('device-'):
        return {'error': 'Invalid device ID format'}, 400

    try:
        asset_id = int(device_id.replace('device-', ''))
    except ValueError:
        return {'error': 'Invalid device ID'}, 400

    asset = Asset.query.get(asset_id)
    if not asset:
        return {'error': 'Device not found'}, 404

    # Get company info
    company = asset.company

    # Simulate health metrics (will be replaced with real Datto data)
    import random
    random.seed(asset_id)  # Consistent values for same device

    return jsonify({
        'id': device_id,
        'name': asset.hostname,
        'company_id': asset.company_account_number,
        'company_name': company.name if company else None,
        'status': 'online' if asset.online else 'offline',
        'os': asset.operating_system,
        'os_version': '10.0.19045' if asset.operating_system and 'Windows' in asset.operating_system else 'Unknown',
        'device_type': asset.device_type or asset.hardware_type,
        'ip_address': asset.ext_ip_address or asset.int_ip_address,
        'mac_address': 'XX:XX:XX:XX:XX:XX',  # Masked for PHI
        'last_seen': asset.last_seen,
        'last_logged_in_user': asset.last_logged_in_user,
        'domain': asset.domain,
        'antivirus': asset.antivirus_product,
        'patch_status': asset.patch_status,
        'last_reboot': asset.last_reboot,
        'installed_software': [
            # Simulated - will be replaced with real data
            {'name': 'Microsoft Office', 'version': '16.0'},
            {'name': 'Google Chrome', 'version': '120.0'}
        ],
        'hardware': {
            'cpu': 'Intel Core i7' if asset.device_type != 'Server' else 'Intel Xeon',
            'ram_gb': random.choice([8, 16, 32, 64]),
            'disk_gb': random.choice([256, 512, 1024, 2048])
        },
        'health': {
            'cpu_usage': random.randint(10, 90) if asset.online else 0,
            'ram_usage': random.randint(30, 85) if asset.online else 0,
            'disk_usage': random.randint(40, 95) if asset.online else 0
        }
    })


@app.route('/health', methods=['GET'])
@app.route('/api/health', methods=['GET'])
@limiter.exempt
def health_check():
    """
    Comprehensive health check endpoint.

    Checks:
    - PostgreSQL database connectivity
    - Disk space
    - Core service availability

    Returns:
        JSON: Detailed health status with HTTP 200 (healthy) or 503 (unhealthy/degraded)
    """
    # Initialize health checker
    health_checker = HealthChecker(
        service_name='codex',
        db=db,
        dependencies=[
            ('core', 'http://localhost:5000')
        ]
    )

    return health_checker.get_health()


# ===== GENERIC PSA ENDPOINTS =====

@app.route('/api/psa/agents', methods=['GET'])
@token_required
def api_get_psa_agents():
    """
    Get list of PSA agents (technicians) from all or specific provider.

    Query params:
        provider: Filter by provider name (e.g., 'freshservice', 'superops')

    Returns list of agents with id, name, email, source, and active status.
    """
    provider = request.args.get('provider')

    query = PSAAgent.query
    if provider:
        query = query.filter_by(external_source=provider)

    agents = query.all()

    result = [
        {
            'id': agent.id,
            'external_id': agent.external_id,
            'source': agent.external_source,
            'name': agent.name,
            'email': agent.email,
            'job_title': agent.job_title,
            'active': agent.active
        }
        for agent in agents
    ]

    # Sort by active status first (active first), then by name
    result.sort(key=lambda a: (not a['active'], a['name']))

    return jsonify(result)


@app.route('/api/psa/config', methods=['GET'])
@token_required
def api_get_psa_config():
    """
    Get PSA configuration for all providers.

    Returns ticket URL templates and other provider-specific config.
    """
    import configparser
    import os

    config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'instance', 'codex.conf')

    providers = {}
    default_provider = None

    try:
        config = configparser.ConfigParser()
        config.read(config_file)

        # Get default provider from PSA section
        if config.has_section('psa'):
            default_provider = config.get('psa', 'default_provider', fallback='freshservice')

        # Freshservice config
        if config.has_section('freshservice'):
            web_domain = config.get('freshservice', 'web_domain', fallback=None)
            if not web_domain:
                web_domain = config.get('freshservice', 'domain', fallback='freshservice.com')
            providers['freshservice'] = {
                'name': 'Freshservice',
                'ticket_url_template': f'https://{web_domain}/a/tickets/{{ticket_id}}',
                'company_url_template': f'https://{web_domain}/a/admin/departments/{{company_id}}',
                'contact_url_template': f'https://{web_domain}/a/requesters/{{contact_id}}'
            }

        # Superops config (when available)
        if config.has_section('psa.superops'):
            providers['superops'] = {
                'name': 'SuperOps',
                'ticket_url_template': 'https://app.superops.com/tickets/{ticket_id}',
                'company_url_template': 'https://app.superops.com/companies/{company_id}',
                'contact_url_template': 'https://app.superops.com/contacts/{contact_id}'
            }

    except Exception as e:
        app.logger.error(f"Failed to get PSA config: {e}")
        return jsonify({'providers': {}, 'error': 'Internal server error'})

    return jsonify({'providers': providers, 'default_provider': default_provider})


@app.route('/api/psa/tickets', methods=['GET'])
@token_required
def api_get_psa_tickets():
    """
    Get tickets from all or specific PSA provider.

    Query params:
        provider: Filter by provider name
        status: Filter by normalized status ('open', 'pending', 'closed', etc.)
        company: Filter by company account number
        limit: Max results (default 100)

    Returns list of tickets with normalized fields.
    """
    provider = request.args.get('provider')
    status = request.args.get('status')
    company = request.args.get('company')
    limit = request.args.get('limit', 100, type=int)

    query = TicketDetail.query

    if provider:
        query = query.filter_by(external_source=provider)
    if status:
        query = query.filter_by(status=status)
    if company:
        query = query.filter_by(company_account_number=company)

    # Order by last updated, most recent first
    query = query.order_by(TicketDetail.last_updated_at.desc())

    tickets = query.limit(limit).all()

    # Get company names for display
    company_map = {}
    if tickets:
        account_numbers = list(set(t.company_account_number for t in tickets if t.company_account_number))
        companies = Company.query.filter(Company.account_number.in_(account_numbers)).all()
        company_map = {c.account_number: c.name for c in companies}

    result = [
        {
            'id': t.id,
            'external_id': t.external_id,
            'source': t.external_source,
            'ticket_number': t.ticket_number,
            'subject': t.subject,
            'status': t.status,
            'priority': t.priority,
            'company_id': t.company_account_number,
            'company_name': company_map.get(t.company_account_number, 'Unknown'),
            'requester_name': t.requester_name,
            'requester_email': t.requester_email,
            'responder_id': t.responder_id,
            'group_id': t.group_id,
            'created_at': t.created_at,
            'updated_at': t.last_updated_at,
            'total_hours': t.total_hours_spent
        }
        for t in tickets
    ]

    return jsonify(result)


@app.route('/api/psa/tickets/active', methods=['GET'])
@token_required
def api_get_psa_active_tickets():
    """
    Get active (open/pending) tickets from all providers.

    Query params:
        provider: Filter by provider name

    Returns list of active tickets.
    """
    provider = request.args.get('provider')

    # Active statuses
    active_statuses = ['open', 'pending', 'waiting_customer', 'on_hold']

    query = TicketDetail.query.filter(TicketDetail.status.in_(active_statuses))

    if provider:
        query = query.filter_by(external_source=provider)

    # Order by priority (urgent first) then by last updated
    query = query.order_by(
        TicketDetail.priority_id.desc(),
        TicketDetail.last_updated_at.desc()
    )

    tickets = query.all()

    # Get company names and agent names for display
    company_map = {}
    if tickets:
        account_numbers = list(set(t.company_account_number for t in tickets if t.company_account_number))
        companies = Company.query.filter(Company.account_number.in_(account_numbers)).all()
        company_map = {c.account_number: c.name for c in companies}

    # Get agent names
    agent_map = {}
    responder_ids = list(set(t.responder_id for t in tickets if t.responder_id))
    if responder_ids:
        agents = PSAAgent.query.filter(PSAAgent.external_id.in_(responder_ids)).all()
        agent_map = {a.external_id: a.name for a in agents}

    result = [
        {
            'id': t.id,
            'external_id': t.external_id,
            'source': t.external_source,
            'ticket_number': t.ticket_number,
            'subject': t.subject,
            'status': t.status,
            'priority': t.priority,
            'company_id': t.company_account_number,
            'company_name': company_map.get(t.company_account_number, 'Unknown'),
            'requester_name': t.requester_name,
            'responder_id': t.responder_id,
            'responder_name': agent_map.get(t.responder_id, 'Unassigned'),
            'group_id': t.group_id,
            'created_at': t.created_at,
            'updated_at': t.last_updated_at,
            'fr_due_by': t.fr_due_by,
            'due_by': t.due_by
        }
        for t in tickets
    ]

    return jsonify(result)


# ===== BILLING PLAN ENDPOINTS =====

@app.route('/api/billing-plans', methods=['GET'])
@token_required
def get_billing_plans():
    """Get all billing plans"""
    plan_name = request.args.get('plan_name')
    term_length = request.args.get('term_length')

    query = BillingPlan.query

    if plan_name:
        query = query.filter_by(plan_name=plan_name)
    if term_length:
        query = query.filter_by(term_length=term_length)

    plans = query.all()

    return jsonify([{
        'id': p.id,
        'plan_name': p.plan_name,
        'billing_plan': p.plan_name,  # Alias for compatibility
        'term_length': p.term_length,
        'support_level': p.support_level,
        'per_user_cost': float(p.per_user_cost),
        'per_workstation_cost': float(p.per_workstation_cost),
        'per_server_cost': float(p.per_server_cost),
        'per_vm_cost': float(p.per_vm_cost),
        'per_switch_cost': float(p.per_switch_cost),
        'per_firewall_cost': float(p.per_firewall_cost),
        'per_hour_ticket_cost': float(p.per_hour_ticket_cost),
        'backup_base_fee_workstation': float(p.backup_base_fee_workstation),
        'backup_base_fee_server': float(p.backup_base_fee_server),
        'backup_included_tb': float(p.backup_included_tb),
        'backup_per_tb_fee': float(p.backup_per_tb_fee),
        'antivirus': p.antivirus,
        'soc': p.soc,
        'password_manager': p.password_manager,
        'sat': p.sat,
        'email_security': p.email_security,
        'network_management': p.network_management
    } for p in plans])


@app.route('/api/billing-plans/<int:plan_id>', methods=['GET'])
@token_required
def get_billing_plan(plan_id):
    """Get specific billing plan"""
    plan = BillingPlan.query.get(plan_id)
    if not plan:
        return jsonify({'error': 'Plan not found'}), 404

    return jsonify({
        'id': plan.id,
        'plan_name': plan.plan_name,
        'billing_plan': plan.plan_name,  # Alias for compatibility
        'term_length': plan.term_length,
        'support_level': plan.support_level,
        'per_user_cost': float(plan.per_user_cost),
        'per_workstation_cost': float(plan.per_workstation_cost),
        'per_server_cost': float(plan.per_server_cost),
        'per_vm_cost': float(plan.per_vm_cost),
        'per_switch_cost': float(plan.per_switch_cost),
        'per_firewall_cost': float(plan.per_firewall_cost),
        'per_hour_ticket_cost': float(plan.per_hour_ticket_cost),
        'backup_base_fee_workstation': float(plan.backup_base_fee_workstation),
        'backup_base_fee_server': float(plan.backup_base_fee_server),
        'backup_included_tb': float(plan.backup_included_tb),
        'backup_per_tb_fee': float(plan.backup_per_tb_fee),
        'antivirus': plan.antivirus,
        'soc': plan.soc,
        'password_manager': plan.password_manager,
        'sat': plan.sat,
        'email_security': plan.email_security,
        'network_management': plan.network_management
    })


@app.route('/api/billing-plans', methods=['POST'])
@token_required
def create_billing_plan():
    """Create a new billing plan"""
    data = request.get_json()

    # Validate required fields
    if not data.get('plan_name') or not data.get('term_length'):
        return jsonify({'error': 'plan_name and term_length are required'}), 400

    # Check if plan already exists
    existing = BillingPlan.query.filter_by(
        plan_name=data['plan_name'],
        term_length=data['term_length']
    ).first()

    if existing:
        return jsonify({'error': 'Plan with this name and term already exists'}), 409

    # Create new plan
    plan = BillingPlan(
        plan_name=data.get('plan_name') or data.get('billing_plan'),
        term_length=data['term_length'],
        support_level=data.get('support_level', 'Billed Hourly'),
        per_user_cost=data.get('per_user_cost', 0.0),
        per_workstation_cost=data.get('per_workstation_cost', 0.0),
        per_server_cost=data.get('per_server_cost', 0.0),
        per_vm_cost=data.get('per_vm_cost', 0.0),
        per_switch_cost=data.get('per_switch_cost', 0.0),
        per_firewall_cost=data.get('per_firewall_cost', 0.0),
        per_hour_ticket_cost=data.get('per_hour_ticket_cost', 0.0),
        backup_base_fee_workstation=data.get('backup_base_fee_workstation', 0.0),
        backup_base_fee_server=data.get('backup_base_fee_server', 0.0),
        backup_included_tb=data.get('backup_included_tb', 1.0),
        backup_per_tb_fee=data.get('backup_per_tb_fee', 0.0),
        antivirus=data.get('antivirus', 'Not Included'),
        soc=data.get('soc', 'Not Included'),
        password_manager=data.get('password_manager', 'Not Included'),
        sat=data.get('sat', 'Not Included'),
        email_security=data.get('email_security', 'Not Included'),
        network_management=data.get('network_management', 'Not Included')
    )

    db.session.add(plan)
    db.session.commit()

    return jsonify({'id': plan.id, 'message': 'Billing plan created'}), 201


@app.route('/api/billing-plans/<int:plan_id>', methods=['PUT'])
@token_required
def update_billing_plan(plan_id):
    """Update an existing billing plan"""
    plan = BillingPlan.query.get(plan_id)
    if not plan:
        return jsonify({'error': 'Plan not found'}), 404

    data = request.get_json()

    # Update fields (support both plan_name and billing_plan for compatibility)
    if 'plan_name' in data or 'billing_plan' in data:
        plan.plan_name = data.get('plan_name') or data.get('billing_plan')
    if 'term_length' in data:
        plan.term_length = data['term_length']
    if 'support_level' in data:
        plan.support_level = data['support_level']
    if 'per_user_cost' in data:
        plan.per_user_cost = data['per_user_cost']
    if 'per_workstation_cost' in data:
        plan.per_workstation_cost = data['per_workstation_cost']
    if 'per_server_cost' in data:
        plan.per_server_cost = data['per_server_cost']
    if 'per_vm_cost' in data:
        plan.per_vm_cost = data['per_vm_cost']
    if 'per_switch_cost' in data:
        plan.per_switch_cost = data['per_switch_cost']
    if 'per_firewall_cost' in data:
        plan.per_firewall_cost = data['per_firewall_cost']
    if 'per_hour_ticket_cost' in data:
        plan.per_hour_ticket_cost = data['per_hour_ticket_cost']
    if 'backup_base_fee_workstation' in data:
        plan.backup_base_fee_workstation = data['backup_base_fee_workstation']
    if 'backup_base_fee_server' in data:
        plan.backup_base_fee_server = data['backup_base_fee_server']
    if 'backup_included_tb' in data:
        plan.backup_included_tb = data['backup_included_tb']
    if 'backup_per_tb_fee' in data:
        plan.backup_per_tb_fee = data['backup_per_tb_fee']
    if 'antivirus' in data:
        plan.antivirus = data['antivirus']
    if 'soc' in data:
        plan.soc = data['soc']
    if 'password_manager' in data:
        plan.password_manager = data['password_manager']
    if 'sat' in data:
        plan.sat = data['sat']
    if 'email_security' in data:
        plan.email_security = data['email_security']
    if 'network_management' in data:
        plan.network_management = data['network_management']

    db.session.commit()

    return jsonify({'id': plan.id, 'message': 'Billing plan updated'}), 200


@app.route('/api/feature-options', methods=['GET'])
@token_required
def get_feature_options():
    """Get all feature options"""
    feature_type = request.args.get('feature_type') or request.args.get('category')

    query = FeatureOption.query

    if feature_type:
        query = query.filter_by(feature_type=feature_type)

    features = query.all()

    return jsonify([{
        'id': f.id,
        'feature_type': f.feature_type,
        'feature_category': f.feature_type,  # Alias for compatibility
        'display_name': f.display_name,
        'option_value': f.display_name,  # Alias for compatibility
        'description': f.description
    } for f in features])


@app.route('/api/feature-options', methods=['POST'])
@token_required
def create_feature_option():
    """Create a new feature option"""
    data = request.get_json()

    # Validate required fields (support both old and new field names)
    feature_type = data.get('feature_type') or data.get('category')
    display_name = data.get('display_name') or data.get('value')

    if not feature_type or not display_name:
        return jsonify({'error': 'feature_type and display_name are required'}), 400

    # Check if feature already exists
    existing = FeatureOption.query.filter_by(
        feature_type=feature_type,
        display_name=display_name
    ).first()

    if existing:
        return jsonify({'message': 'Feature already exists', 'id': existing.id}), 200

    # Create new feature
    feature = FeatureOption(
        feature_type=feature_type,
        display_name=display_name,
        description=data.get('description')
    )

    db.session.add(feature)
    db.session.commit()

    return jsonify({'id': feature.id, 'message': 'Feature option created'}), 201


@app.route('/api/billing-plans/<string:plan_name>/<string:term_length>', methods=['GET'])
@token_required
def get_plan_by_name_and_term(plan_name, term_length):
    """Get billing plan details by plan name and term length with dynamic features"""
    plan = BillingPlan.query.filter_by(
        plan_name=plan_name,
        term_length=term_length
    ).first()

    if not plan:
        return jsonify({'error': 'Plan not found'}), 404

    # Build features dictionary from PlanFeature table
    features = {}
    for plan_feature in plan.features:
        features[plan_feature.feature_type] = plan_feature.feature_value

    return jsonify({
        'id': plan.id,
        'plan_name': plan.plan_name,
        'term_length': plan.term_length,
        'support_level': plan.support_level,
        'features': features
    })
