#!/usr/bin/env python3
"""
One-Time Migration: Fix Support Levels for All Companies

This script updates all existing companies in Codex to have the correct
support_level pulled from their billing plan instead of Freshservice.

Usage:
    python fix_support_levels.py [--dry-run]
"""

import sys
import os
import argparse

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, Company, BillingPlan

def fix_support_levels(dry_run=False):
    """Update all companies to have support_level from their billing plan and fix term format."""
    print("=" * 80)
    print("FIXING SUPPORT LEVELS AND CONTRACT TERMS FOR ALL COMPANIES")
    print("=" * 80)

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be saved\n")

    with app.app_context():
        # Get all companies
        companies = Company.query.all()
        print(f"\nFound {len(companies)} companies in database\n")

        updated_count = 0
        skipped_count = 0
        no_plan_count = 0
        term_fixed_count = 0

        for company in companies:
            print(f"Processing: {company.name} ({company.account_number})")
            print(f"  Current support level: {company.support_level or 'None'}")
            print(f"  Billing plan: {company.billing_plan or 'None'}")
            print(f"  Contract term: {company.contract_term_length or 'None'}")

            # Normalize contract term format
            if company.contract_term_length:
                term_map = {
                    '1 year': '1-Year',
                    '2 years': '2-Year',
                    '2 year': '2-Year',
                    '3 years': '3-Year',
                    '3 year': '3-Year',
                    'month to month': 'Month to Month',
                    'monthly': 'Month to Month'
                }
                normalized_term = term_map.get(company.contract_term_length.lower(), company.contract_term_length)
                if normalized_term != company.contract_term_length:
                    print(f"  → Normalizing term: '{company.contract_term_length}' → '{normalized_term}'")
                    company.contract_term_length = normalized_term
                    term_fixed_count += 1

            # Check if company has a billing plan assigned
            if not company.billing_plan or not company.contract_term_length:
                print(f"  → Skipped: No billing plan assigned")
                no_plan_count += 1
                print()
                continue

            # Look up the billing plan
            billing_plan = BillingPlan.query.filter_by(
                plan_name=company.billing_plan,
                term_length=company.contract_term_length
            ).first()

            if not billing_plan:
                print(f"  → Warning: Billing plan '{company.billing_plan}' ({company.contract_term_length}) not found in database")
                no_plan_count += 1
                print()
                continue

            print(f"  → Found billing plan with support level: {billing_plan.support_level}")

            # Check if update is needed
            if company.support_level == billing_plan.support_level:
                print(f"  → Already correct, no update needed")
                skipped_count += 1
            else:
                old_value = company.support_level
                company.support_level = billing_plan.support_level
                print(f"  → Updated: '{old_value}' → '{billing_plan.support_level}'")
                updated_count += 1

            print()

        # Commit changes
        if not dry_run and updated_count > 0:
            db.session.commit()
            print("✓ Changes committed to database")
        elif dry_run:
            print("ℹ Dry run complete - no changes saved")
        else:
            print("ℹ No updates needed")

        # Summary
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total companies: {len(companies)}")
        print(f"Support levels updated: {updated_count}")
        print(f"Contract terms normalized: {term_fixed_count}")
        print(f"Already correct: {skipped_count}")
        print(f"No billing plan: {no_plan_count}")
        print("=" * 80)

        return updated_count


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Fix support levels for all companies',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be changed without saving'
    )

    args = parser.parse_args()

    try:
        updated = fix_support_levels(dry_run=args.dry_run)

        if args.dry_run:
            print("\nRun without --dry-run to apply changes:")
            print("  python fix_support_levels.py")
        else:
            print(f"\n✓ Successfully updated {updated} companies")

        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
