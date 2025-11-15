#!/usr/bin/env python3
"""
Calculate contract end dates for all companies based on start date and term length.
"""

import sys
import os
from datetime import datetime, timedelta

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, Company

def calculate_end_dates():
    """Calculate contract end dates for all companies."""
    print("=" * 80)
    print("CALCULATING CONTRACT END DATES FOR ALL COMPANIES")
    print("=" * 80)

    with app.app_context():
        companies = Company.query.all()
        print(f"\nFound {len(companies)} companies in database\n")

        updated_count = 0
        skipped_count = 0

        for company in companies:
            print(f"Processing: {company.name} ({company.account_number})")
            print(f"  Contract Start: {company.contract_start_date}")
            print(f"  Contract Term: {company.contract_term_length}")
            print(f"  Current End Date: {company.contract_end_date}")

            if not company.contract_start_date or not company.contract_term_length:
                print(f"  → Skipped: Missing start date or term length")
                skipped_count += 1
                print()
                continue

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
                    calculated_end_date = end_date.strftime('%Y-%m-%d')

                    if company.contract_end_date != calculated_end_date:
                        company.contract_end_date = calculated_end_date
                        print(f"  → Updated end date to: {calculated_end_date}")
                        updated_count += 1
                    else:
                        print(f"  → Already correct: {calculated_end_date}")
                else:
                    # Month to Month or other - no end date
                    if company.contract_end_date is not None:
                        company.contract_end_date = None
                        print(f"  → Cleared end date (Month to Month)")
                        updated_count += 1
                    else:
                        print(f"  → No end date needed (Month to Month)")

            except (ValueError, AttributeError) as e:
                print(f"  → Error: Could not calculate contract end date: {e}")
                skipped_count += 1

            print()

        # Commit changes
        db.session.commit()
        print("✓ Changes committed to database")

        # Summary
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total companies: {len(companies)}")
        print(f"End dates calculated/updated: {updated_count}")
        print(f"Skipped: {skipped_count}")
        print("=" * 80)

        return updated_count


if __name__ == '__main__':
    try:
        updated = calculate_end_dates()
        print(f"\n✓ Successfully processed companies")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
