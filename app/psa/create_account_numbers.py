#!/usr/bin/env python3
"""
Create Account Numbers for PSA Companies

This script assigns unique 6-digit account numbers to companies in the PSA system
that don't already have one. It uses the PSA provider API and updates
the Codex database after successful assignments.

Auto-run: This should run automatically after PSA sync completes.
"""

import sys
import os
import random
import time
import configparser

# Add app directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from app.psa import get_provider
from models import Company
from extensions import db


def get_existing_account_numbers():
    """Get all existing account numbers from database."""
    with app.app_context():
        companies = Company.query.filter(Company.account_number.isnot(None)).all()
        return {int(c.account_number) for c in companies if c.account_number}


def create_account_numbers():
    """Main function to create account numbers for companies that need them."""
    print("=" * 60)
    print("CREATE ACCOUNT NUMBERS FOR PSA COMPANIES")
    print("=" * 60)

    with app.app_context():
        # Load config to get PSA provider
        config_path = os.path.join(app.instance_path, 'codex.conf')
        config = configparser.RawConfigParser()
        config.read(config_path)

        # Get the default provider
        default_provider = config.get('psa', 'default_provider', fallback='freshservice')

        # Initialize PSA provider
        try:
            provider = get_provider(default_provider, config)
        except Exception as e:
            print(f"ERROR: Could not initialize PSA provider: {e}")
            return False

        # Get all companies from PSA
        print(f"\n1. Fetching companies from {provider.display_name}...")

        # Use get_companies_raw to get the raw API response with custom_fields
        if hasattr(provider, 'get_companies_raw'):
            psa_companies = provider.get_companies_raw()
        else:
            print(f"ERROR: Provider {default_provider} does not support raw company fetch")
            return False

        if not psa_companies:
            print(f"ERROR: Could not fetch companies from {provider.display_name}")
            return False

        print(f"   Found {len(psa_companies)} total companies")

        # Get existing account numbers
        existing_numbers = get_existing_account_numbers()
        print(f"   Found {len(existing_numbers)} existing account numbers")

        # Find companies that need account numbers
        companies_to_update = []
        for company in psa_companies:
            custom_fields = company.get('custom_fields', {})
            acc_num = custom_fields.get('account_number')
            if not acc_num:
                companies_to_update.append(company)

        print(f"   Found {len(companies_to_update)} companies needing account numbers\n")

        if not companies_to_update:
            print("✓ All companies already have account numbers!")
            return True

        # Assign new account numbers
        print("2. Assigning new account numbers...")
        updated_count = 0
        failed_count = 0

        for company in companies_to_update:
            company_id = company['id']
            company_name = company['name']

            # Generate unique 6-digit number
            new_number = None
            while new_number is None or new_number in existing_numbers:
                new_number = random.randint(100000, 999999)

            print(f"   → {company_name}: {new_number}")

            # Update in PSA (send as integer, not string)
            success = provider.update_company(
                company_id,
                {'account_number': new_number}
            )

            if success:
                existing_numbers.add(new_number)
                updated_count += 1

                # Update in Codex database
                db_company = Company.query.filter_by(name=company_name).first()
                if db_company:
                    db_company.account_number = str(new_number)
                    try:
                        db.session.commit()
                    except Exception as e:
                        print(f"      Warning: Failed to update database: {e}")
                        db.session.rollback()

                # Be nice to the API
                time.sleep(0.5)
            else:
                print(f"      ERROR: Failed to update {company_name}")
                failed_count += 1

        # Summary
        print("\n" + "=" * 60)
        print(f"✓ Successfully assigned {updated_count} account numbers")
        if failed_count > 0:
            print(f"✗ Failed to assign {failed_count} account numbers")
        print("=" * 60)

        return failed_count == 0


if __name__ == "__main__":
    success = create_account_numbers()
    sys.exit(0 if success else 1)
