#!/usr/bin/env python3
"""
Push Account Numbers to RMM System

This script syncs account numbers from Codex/PSA to RMM sites as site variables.
It matches RMM site names to PSA company names and pushes the AccountNumber variable.

Vendor-agnostic: Works with Datto RMM, SuperOps RMM, etc.

Special cases:
- "Redbarn" in RMM → "Redbarn Cannabis" in PSA

Auto-run: This should run automatically after RMM sync completes.
"""

import sys
import os
import time
import configparser

# Add parent directories to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
codex_root = os.path.dirname(os.path.dirname(script_dir))
sys.path.insert(0, codex_root)

from app import app
from app.rmm import get_provider, get_default_provider
from models import Company
from extensions import db


# Special mapping rules
REDBARN_KEYWORD = "Redbarn"
REDBARN_PSA_TARGET = "Redbarn Cannabis"
RMM_VARIABLE_NAME = "AccountNumber"


def get_config():
    """Load configuration from codex.conf."""
    instance_path = os.path.join(codex_root, 'instance')
    config_path = os.path.join(instance_path, 'codex.conf')
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found at {config_path}")

    config = configparser.RawConfigParser()
    config.read(config_path)
    return config


def push_account_numbers(provider_name=None):
    """
    Main function to push account numbers from Codex to RMM system.

    Args:
        provider_name: Optional RMM provider name (if None, use default from config)
    """
    print("=" * 60)
    print("PUSH ACCOUNT NUMBERS TO RMM SYSTEM")
    print("=" * 60)

    # Load RMM provider
    config = get_config()
    if provider_name:
        print(f"\nUsing specified RMM provider: {provider_name}")
        rmm_provider = get_provider(provider_name, config)
    else:
        print("\nUsing default RMM provider from config")
        rmm_provider = get_default_provider(config)

    print(f"RMM Provider: {rmm_provider.display_name}")

    # Authenticate
    print("\nAuthenticating with RMM system...")
    try:
        rmm_provider.authenticate()
        print(f"✓ Successfully authenticated with {rmm_provider.display_name}")
    except Exception as e:
        print(f"ERROR: Could not authenticate with RMM system: {e}", file=sys.stderr)
        return False

    with app.app_context():
        # Get all companies from Codex database
        print("\n1. Loading companies from Codex database...")
        companies = Company.query.filter(Company.account_number.isnot(None)).all()
        company_map = {c.name.strip(): c.account_number for c in companies if c.name}
        print(f"   Found {len(company_map)} companies with account numbers")

        # Get all sites from RMM system
        print(f"\n2. Fetching sites from {rmm_provider.display_name}...")
        try:
            rmm_sites = rmm_provider.sync_sites()
        except Exception as e:
            print(f"ERROR: Could not fetch sites from RMM system: {e}", file=sys.stderr)
            return False

        if not rmm_sites:
            print("ERROR: No sites returned from RMM system")
            return False

        print(f"   Found {len(rmm_sites)} RMM sites\n")

        # Match RMM sites to PSA companies
        actions = []
        unmapped_sites = []

        print("3. Matching RMM sites to PSA companies...")
        for site in rmm_sites:
            rmm_name = (site.get('name') or '').strip()
            rmm_id = site.get('external_id')
            psa_name_match = None

            # Special case: Redbarn
            if REDBARN_KEYWORD in rmm_name:
                psa_name_match = REDBARN_PSA_TARGET
            else:
                # Find longest matching PSA company name in RMM site name
                # This prevents "A" from matching "A-1 Movers" if both exist
                best_match = ''
                for psa_name in company_map.keys():
                    if psa_name in rmm_name and len(psa_name) > len(best_match):
                        best_match = psa_name
                if best_match:
                    psa_name_match = best_match

            if psa_name_match and psa_name_match in company_map:
                account_number = company_map[psa_name_match]
                actions.append({
                    'rmm_site_name': rmm_name,
                    'rmm_site_id': rmm_id,
                    'account_number': account_number,
                    'psa_company_name': psa_name_match
                })
            else:
                unmapped_sites.append(rmm_name)

        print(f"   Matched {len(actions)} sites")
        print(f"   Unmapped {len(unmapped_sites)} sites\n")

        # Push account numbers to RMM
        print(f"4. Pushing account numbers to {rmm_provider.display_name}...")
        success_count = 0
        fail_count = 0
        already_set_count = 0

        for action in sorted(actions, key=lambda x: x['rmm_site_name']):
            rmm_name = action['rmm_site_name']
            rmm_id = action['rmm_site_id']
            acc_num = action['account_number']
            psa_name = action['psa_company_name']

            print(f"   → {rmm_name} ({psa_name}): {acc_num}")

            # Check if variable already exists
            try:
                current_value = rmm_provider.get_site_variable(rmm_id, RMM_VARIABLE_NAME)
                if current_value == str(acc_num):
                    print("      ℹ  Already set to correct value, skipping")
                    already_set_count += 1
                    continue
            except Exception:
                # Variable doesn't exist or can't check - proceed to set it
                pass

            # Push the variable
            try:
                rmm_provider.set_site_variable(rmm_id, RMM_VARIABLE_NAME, str(acc_num))
                print("      ✓ Success")
                success_count += 1
            except Exception as e:
                print(f"      ✗ Failed: {e}")
                fail_count += 1

            # Be nice to the API
            time.sleep(0.5)

        # Summary
        print("\n" + "=" * 60)
        print(f"✓ Successfully pushed {success_count} account numbers")
        print(f"ℹ  Skipped {already_set_count} sites (already set)")
        if fail_count > 0:
            print(f"✗ Failed to push {fail_count} account numbers")
        print("=" * 60)

        if unmapped_sites:
            print("\nUnmapped RMM Sites (no matching company):")
            for name in sorted(unmapped_sites):
                print(f"  - {name}")

        return fail_count == 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Push account numbers to RMM system')
    parser.add_argument('--provider', type=str, help='RMM provider to use (datto, superops, etc.)')
    args = parser.parse_args()

    success = push_account_numbers(provider_name=args.provider)
    sys.exit(0 if success else 1)
