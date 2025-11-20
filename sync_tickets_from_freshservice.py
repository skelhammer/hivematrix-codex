#!/usr/bin/env python3
"""
Sync Ticket Details from Freshservice to Codex Database

This script fetches all tickets (open, pending, closed, etc.) from Freshservice and stores
them in the Codex database. It tracks the last sync timestamp to only pull new/updated
tickets on subsequent runs. This provides ticket data for the Beacon dashboard.
"""

import requests
import base64
import os
import sys
import time
import argparse
import configparser
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add the parent directory to the path so we can import from app
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables from .flaskenv before importing app
from dotenv import load_dotenv
dotenv_path = Path(__file__).parent / '.flaskenv'
load_dotenv(dotenv_path)

from app import app
from extensions import db
from models import Company, TicketDetail

# Configuration
ACCOUNT_NUMBER_FIELD = "account_number"
MAX_RETRIES = 3
DEFAULT_TICKET_HOURS = 0  # No default time


def get_freshservice_credentials():
    """
    Load Freshservice API credentials from config file.

    Returns:
        tuple: (base_url, api_key)
    """
    config_path = os.path.join(app.instance_path, 'codex.conf')
    if not os.path.exists(config_path):
        raise ValueError(f"Config file not found: {config_path}")

    config = configparser.RawConfigParser()
    config.read(config_path)

    if not config.has_section('freshservice'):
        raise ValueError("Freshservice configuration not found in codex.conf")

    domain = config.get('freshservice', 'domain', fallback='')
    api_key = config.get('freshservice', 'api_key', fallback='')

    if not domain or not api_key:
        raise ValueError("Freshservice domain and API key must be configured")

    # Ensure domain has https:// prefix
    if not domain.startswith('http'):
        base_url = f"https://{domain}"
    else:
        base_url = domain

    return base_url, api_key


def get_latest_ticket_timestamp(full_history=False):
    """Gets the timestamp of the most recently updated ticket in the database."""
    latest = db.session.query(db.func.max(TicketDetail.last_updated_at)).scalar()

    if latest:
        try:
            dt = datetime.fromisoformat(latest.replace('Z', '+00:00'))
            return dt + timedelta(seconds=1)
        except:
            pass

    # No existing tickets - determine initial sync range
    if full_history:
        print("No existing tickets found. Performing FULL HISTORY sync (all time).")
        # Use year 2000 as a safe starting point to get all tickets
        return datetime(2000, 1, 1, tzinfo=timezone.utc)
    else:
        print("No existing tickets found. Performing initial sync for the past 3 months.")
        print("(Use --full-history for complete ticket history)")
        return datetime.now(timezone.utc) - timedelta(days=90)


def get_last_sync_time():
    """Gets the timestamp of the last successful ticket sync from SyncJob table."""
    from models import SyncJob
    last_sync = SyncJob.query.filter_by(
        script='tickets',
        status='completed'
    ).order_by(SyncJob.completed_at.desc()).first()

    if last_sync and last_sync.started_at:
        try:
            # Use started_at to ensure we don't miss any tickets
            dt = datetime.fromisoformat(last_sync.started_at.replace('Z', '+00:00'))
            return dt
        except:
            pass

    return None


def get_company_map_from_api(base_url, headers):
    """Fetches all companies from Freshservice and returns a map of fs_id to account_number."""
    all_companies = []
    page = 1
    print("Fetching company map from Freshservice API...")

    while True:
        params = {'page': page, 'per_page': 100}
        try:
            response = requests.get(
                f"{base_url}/api/v2/departments",
                headers=headers,
                params=params,
                timeout=90
            )

            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 10))
                print(f"  -> Rate limit hit, waiting {retry_after}s...")
                time.sleep(retry_after)
                continue

            response.raise_for_status()
            data = response.json()
            companies_on_page = data.get('departments', [])

            if not companies_on_page:
                break

            all_companies.extend(companies_on_page)
            page += 1
            time.sleep(0.5)

        except requests.exceptions.RequestException as e:
            print(f"ERROR fetching companies: {e}", file=sys.stderr)
            return None

    # Build the mapping
    fs_id_to_account_map = {}
    for company in all_companies:
        fs_id = company.get('id')
        custom_fields = company.get('custom_fields', {}) or {}
        account_number = custom_fields.get(ACCOUNT_NUMBER_FIELD)

        if fs_id and account_number:
            fs_id_to_account_map[fs_id] = str(account_number)

    print(f"Successfully mapped {len(fs_id_to_account_map)} companies with account numbers.")
    return fs_id_to_account_map


def get_updated_tickets(base_url, headers, since_timestamp=None, open_only=True):
    """Fetch tickets from Freshservice.

    Args:
        base_url: Freshservice API base URL
        headers: API headers with auth
        since_timestamp: Only fetch tickets updated after this time (optional)
        open_only: If True, only fetch open tickets (excludes closed/resolved)
    """
    all_tickets = []
    page = 1

    # Build query based on parameters
    if open_only:
        # Fetch all non-closed tickets using known active statuses
        # These are the statuses we want to show in Beacon
        active_statuses = [2, 3, 8, 9, 10, 13, 19, 23, 26, 27]
        status_conditions = [f"status:{s}" for s in active_statuses]
        query = f"({' OR '.join(status_conditions)})"
        print(f"Fetching ALL open tickets (excluding closed/resolved)...")
    elif since_timestamp:
        since_str = since_timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')
        query = f"updated_at:>'{since_str}'"
        print(f"Fetching ALL tickets updated since {since_str}...")
    else:
        # Fetch everything from the beginning
        query = "updated_at:>'2000-01-01T00:00:00Z'"
        print(f"Fetching ALL tickets (full history)...")

    while True:
        params = {'query': f'"{query}"', 'page': page, 'per_page': 100}
        try:
            response = requests.get(
                f"{base_url}/api/v2/tickets/filter",
                headers=headers,
                params=params,
                timeout=90
            )

            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 10))
                print(f"  -> Rate limit hit, waiting {retry_after}s...")
                time.sleep(retry_after)
                continue

            response.raise_for_status()
            data = response.json()
            tickets_on_page = data.get('tickets', [])

            if not tickets_on_page:
                break

            all_tickets.extend(tickets_on_page)
            print(f"  -> Fetched page {page}, total tickets: {len(all_tickets)}")
            page += 1
            time.sleep(1)

        except requests.exceptions.RequestException as e:
            print(f"ERROR fetching tickets: {e}", file=sys.stderr)
            return None

    return all_tickets


def get_time_entries_for_ticket(base_url, headers, ticket_id):
    """Fetch total hours logged for a specific ticket."""
    total_hours = 0
    endpoint = f"{base_url}/api/v2/tickets/{ticket_id}/time_entries"
    retries = 0

    while retries < MAX_RETRIES:
        try:
            response = requests.get(endpoint, headers=headers, timeout=60)

            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 10))
                print(f"    [!] Rate limit on ticket #{ticket_id}. Retrying in {retry_after}s...")
                time.sleep(retry_after)
                retries += 1
                continue

            if response.status_code == 404:
                return 0

            response.raise_for_status()
            data = response.json()
            time_entries = data.get('time_entries', [])

            for entry in time_entries:
                time_str = entry.get('time_spent', '00:00')
                try:
                    parts = time_str.split(':')
                    if len(parts) == 2:
                        h, m = map(int, parts)
                        total_hours += h + (m / 60.0)
                    elif len(parts) == 3:
                        h, m, s = map(int, parts)
                        total_hours += h + (m / 60.0) + (s / 3600.0)
                except ValueError:
                    pass

            return total_hours

        except requests.exceptions.RequestException as e:
            print(f"  -> WARN: Could not fetch time for ticket {ticket_id}: {e}", file=sys.stderr)
            retries += 1
            time.sleep(5)

    print(f"  -> ERROR: Failed to fetch time for ticket {ticket_id} after {MAX_RETRIES} retries.", file=sys.stderr)
    return 0


def get_ticket_conversations(base_url, headers, ticket_id):
    """Fetch conversation history for a ticket."""
    endpoint = f"{base_url}/api/v2/tickets/{ticket_id}/conversations"
    retries = 0

    while retries < MAX_RETRIES:
        try:
            response = requests.get(endpoint, headers=headers, timeout=60)

            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 10))
                time.sleep(retry_after)
                retries += 1
                continue

            if response.status_code == 404:
                return []

            response.raise_for_status()
            data = response.json()
            return data.get('conversations', [])

        except requests.exceptions.RequestException as e:
            print(f"  -> WARN: Could not fetch conversations for ticket {ticket_id}: {e}", file=sys.stderr)
            retries += 1
            time.sleep(5)

    print(f"  -> ERROR: Failed to fetch conversations for ticket {ticket_id} after {MAX_RETRIES} retries.", file=sys.stderr)
    return []


def get_ticket_details(base_url, headers, ticket_id):
    """Fetch ticket details with stats and conversations in one API call.

    This is optimized to reduce API calls - combines stats and conversations fetch.
    Returns: (stats_dict, conversations_list)
    """
    endpoint = f"{base_url}/api/v2/tickets/{ticket_id}?include=stats,conversations"
    retries = 0

    while retries < MAX_RETRIES:
        try:
            response = requests.get(endpoint, headers=headers, timeout=60)

            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 10))
                time.sleep(retry_after)
                retries += 1
                continue

            if response.status_code == 404:
                return {}, []

            response.raise_for_status()
            data = response.json()
            ticket_data = data.get('ticket', {})
            stats = ticket_data.get('stats', {}) or {}
            conversations = ticket_data.get('conversations', []) or []
            return stats, conversations

        except requests.exceptions.RequestException as e:
            print(f"  -> WARN: Could not fetch details for ticket {ticket_id}: {e}", file=sys.stderr)
            retries += 1
            time.sleep(5)

    print(f"  -> ERROR: Failed to fetch details for ticket {ticket_id} after {MAX_RETRIES} retries.", file=sys.stderr)
    return {}, []


def strip_html(html_content):
    """Remove HTML tags and return plain text."""
    if not html_content:
        return ""
    import re
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', html_content)
    # Decode HTML entities
    import html
    text = html.unescape(text)
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def sync_tickets(full_sync=False, full_history=False):
    """Main sync function.

    Args:
        full_sync: Clear all tickets and re-sync from scratch
        full_history: For initial sync, pull 2 years instead of 30 days
    """
    with app.app_context():
        # Get Freshservice credentials and domain
        try:
            base_url, api_key = get_freshservice_credentials()
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            print("\nPlease ensure Freshservice domain and API key are configured in instance/codex.conf", file=sys.stderr)
            print("Add a section like:\n[freshservice]\ndomain = your-domain.freshservice.com\napi_key = your_api_key_here", file=sys.stderr)
            return 1

        # Setup API authentication
        auth_str = f"{api_key}:X"
        encoded_auth = base64.b64encode(auth_str.encode()).decode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {encoded_auth}"
        }

        # Get company mapping
        fs_id_to_account_map = get_company_map_from_api(base_url, headers)
        if not fs_id_to_account_map:
            print("ERROR: Could not build company map. Aborting.", file=sys.stderr)
            return 1

        # Determine what to fetch
        if full_sync:
            print("Full sync requested. Clearing existing ticket data...")
            TicketDetail.query.delete()
            db.session.commit()
            # Fetch ALL tickets (including closed) from all time
            tickets = get_updated_tickets(base_url, headers, open_only=False)
        elif full_history:
            # Fetch ALL tickets (including closed) from all time
            tickets = get_updated_tickets(base_url, headers, open_only=False)
        else:
            # Regular sync: Fetch all tickets updated since last sync
            # This includes closed tickets so their status gets updated in the database
            last_sync = get_last_sync_time()
            if last_sync:
                print(f"Last sync was at {last_sync.isoformat()}")
                tickets = get_updated_tickets(base_url, headers, since_timestamp=last_sync, open_only=False)
            else:
                # No previous sync - fetch all open tickets for initial load
                print("No previous sync found, fetching all open tickets...")
                tickets = get_updated_tickets(base_url, headers, open_only=True)
        if tickets is None:
            print("ERROR: Failed to fetch tickets. Aborting.", file=sys.stderr)
            return 1

        if not tickets:
            print("\nNo new or updated tickets found.")
            return 0

        # Log all fetched ticket IDs for debugging
        fetched_ids = sorted([t['id'] for t in tickets])
        print(f"\nFetched ticket IDs from Freshservice: {fetched_ids}")

        # Process tickets
        print(f"\nProcessing {len(tickets)} tickets and fetching time entries...")
        processed = 0
        failed = 0
        failed_tickets = []

        for ticket in tickets:
            department_id = ticket.get('department_id')
            account_number = fs_id_to_account_map.get(department_id)

            ticket_id = ticket['id']

            if not account_number:
                print(f"  -> Processing Ticket #{ticket_id}... (no department mapping)")
            else:
                print(f"  -> Processing Ticket #{ticket_id}...")

            try:
                # Fetch time entries
                total_hours = get_time_entries_for_ticket(base_url, headers, ticket_id)

                # Fetch ticket details (stats + conversations) in one optimized API call
                print(f"    -> Fetching ticket details (stats + conversations)...")
                stats, conversations = get_ticket_details(base_url, headers, ticket_id)

                # Create or update ticket record
                ticket_record = TicketDetail.query.get(ticket_id)
                if not ticket_record:
                    ticket_record = TicketDetail(ticket_id=ticket_id)

                ticket_record.company_account_number = account_number
                ticket_record.ticket_number = str(ticket_id)
                ticket_record.subject = ticket.get('subject', 'No Subject')
                ticket_record.description = ticket.get('description', '')
                ticket_record.description_text = strip_html(ticket.get('description_text') or ticket.get('description', ''))

                # Status mapping
                status_map = {2: 'Open', 3: 'Pending', 4: 'Resolved', 5: 'Closed',
                             9: 'Waiting on Customer', 23: 'On Hold', 26: 'Waiting on Agent',
                             19: 'Update Needed', 27: 'Pending Hubspot'}
                status_id = ticket.get('status')
                ticket_record.status_id = status_id
                ticket_record.status = status_map.get(status_id, ticket.get('status_name', 'Unknown'))

                # Priority mapping
                priority_map = {1: 'Low', 2: 'Medium', 3: 'High', 4: 'Urgent'}
                priority_id = ticket.get('priority')
                ticket_record.priority_id = priority_id
                ticket_record.priority = priority_map.get(priority_id, ticket.get('priority_name', 'Medium'))

                # Ticket type
                ticket_record.ticket_type = ticket.get('type', 'Incident')

                # Requester info
                requester = ticket.get('requester', {})
                if isinstance(requester, dict):
                    ticket_record.requester_email = requester.get('email')
                    ticket_record.requester_name = requester.get('name')
                ticket_record.requester_id = ticket.get('requester_id')

                # Assignment info
                ticket_record.responder_id = ticket.get('responder_id')
                ticket_record.group_id = ticket.get('group_id')

                # Timestamps
                ticket_record.created_at = ticket.get('created_at')
                ticket_record.last_updated_at = ticket.get('updated_at')

                # Only set closed_at if ticket is actually closed
                if status_id == 5:
                    ticket_record.closed_at = ticket.get('updated_at')
                else:
                    ticket_record.closed_at = None

                # SLA fields
                ticket_record.fr_due_by = ticket.get('fr_due_by')
                ticket_record.due_by = ticket.get('due_by')

                # Stats (first response times) - already fetched with get_ticket_details
                ticket_record.first_responded_at = stats.get('first_responded_at')
                ticket_record.agent_responded_at = stats.get('agent_responded_at')

                ticket_record.total_hours_spent = total_hours

                # Store conversations as JSON
                import json
                conversation_data = []
                note_data = []

                for conv in conversations:
                    conv_entry = {
                        'id': conv.get('id'),
                        'body': strip_html(conv.get('body', '')),
                        'body_html': conv.get('body', ''),
                        'from_email': conv.get('from_email'),
                        'to_emails': conv.get('to_emails', []),
                        'created_at': conv.get('created_at'),
                        'updated_at': conv.get('updated_at'),
                        'incoming': conv.get('incoming', False),
                        'private': conv.get('private', False),
                        'user_id': conv.get('user_id'),
                        'support_email': conv.get('support_email')
                    }

                    # Separate private notes from public conversations
                    if conv.get('private'):
                        note_data.append(conv_entry)
                    else:
                        conversation_data.append(conv_entry)

                ticket_record.conversations = json.dumps(conversation_data) if conversation_data else None
                ticket_record.notes = json.dumps(note_data) if note_data else None

                print(f"    -> Stored {len(conversation_data)} conversations and {len(note_data)} notes")

                db.session.add(ticket_record)
                processed += 1

                # Commit in batches
                if processed % 50 == 0:
                    try:
                        db.session.commit()
                        print(f"  -> Committed {processed} tickets so far...")
                    except Exception as commit_error:
                        db.session.rollback()
                        print(f"    ✗ Batch commit failed: {commit_error}")
                        # The failed ticket is still in the session, so we continue

            except Exception as e:
                db.session.rollback()
                failed += 1
                failed_tickets.append(ticket_id)
                print(f"    ✗ Failed to process ticket #{ticket_id}: {e}")
                continue

        # Final commit
        try:
            db.session.commit()
            print(f"\n✓ Successfully synced {processed} tickets.")
            if failed > 0:
                print(f"✗ Failed to sync {failed} tickets: {failed_tickets}")
        except Exception as e:
            db.session.rollback()
            print(f"\n✗ Final commit failed: {e}")
            return 1

        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync ticket details from Freshservice to Codex.")
    parser.add_argument('--full-sync', action='store_true',
                       help="Clear all tickets and re-sync from scratch (2 years of history)")
    parser.add_argument('--full-history', action='store_true',
                       help="For initial sync, pull 2 years of history instead of 30 days")
    args = parser.parse_args()

    print("--- Codex Ticket Sync Script ---")
    exit_code = sync_tickets(full_sync=args.full_sync, full_history=args.full_history)
    sys.exit(exit_code)
