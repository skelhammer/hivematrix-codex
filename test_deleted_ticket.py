#!/usr/bin/env python3
"""
Test script to check if Freshservice API returns deleted tickets
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from app.psa import get_provider
import configparser

def test_deleted_ticket(ticket_id):
    """Query Freshservice for a specific ticket to see its status"""

    with app.app_context():
        # Load config
        config_path = os.path.join(app.instance_path, 'codex.conf')
        config = configparser.RawConfigParser()
        config.read(config_path)

        # Get Freshservice provider
        provider = get_provider('freshservice', config)

        print(f"Testing ticket #{ticket_id} with Freshservice API...")
        print("=" * 60)

        # Authenticate
        print("\n1. Authenticating...")
        provider.authenticate()
        print("   ✓ Authenticated")

        # Try to get the ticket
        print(f"\n2. Fetching ticket #{ticket_id}...")
        try:
            ticket = provider.get_ticket(ticket_id)

            if ticket:
                print(f"   ✓ Ticket found!")
                print(f"\n   Ticket Details:")
                print(f"   - ID: {ticket.get('external_id')}")
                print(f"   - Number: {ticket.get('ticket_number')}")
                print(f"   - Subject: {ticket.get('subject')}")
                print(f"   - Status ID: {ticket.get('status_id')}")
                print(f"   - Normalized Status: {ticket.get('status')}")
                print(f"   - Priority ID: {ticket.get('priority_id')}")
                print(f"   - Priority: {ticket.get('priority')}")

                # Check if it's in INVALID_STATUS_NAMES
                from app.psa.mappings import INVALID_STATUS_NAMES
                if ticket.get('status') in INVALID_STATUS_NAMES:
                    print(f"\n   ⚠️  Status '{ticket.get('status')}' is in INVALID_STATUS_NAMES")
                    print(f"   This ticket SHOULD be deleted by sync_psa.py")
                else:
                    print(f"\n   ℹ️  Status '{ticket.get('status')}' is NOT in INVALID_STATUS_NAMES")
                    print(f"   INVALID_STATUS_NAMES = {INVALID_STATUS_NAMES}")

            else:
                print(f"   ✗ Ticket not found (API returned None)")
                print(f"   This could mean:")
                print(f"   - Ticket was permanently deleted")
                print(f"   - API doesn't return deleted tickets")

        except Exception as e:
            print(f"   ✗ Error fetching ticket: {e}")
            print(f"   This likely means the ticket is deleted/inaccessible")

        print("\n" + "=" * 60)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python test_deleted_ticket.py <ticket_id>")
        print("Example: python test_deleted_ticket.py 18262")
        sys.exit(1)

    ticket_id = sys.argv[1]
    test_deleted_ticket(ticket_id)
