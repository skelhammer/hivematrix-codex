"""
RMM Data Sync Script

Syncs devices and sites from RMM system (Datto, SuperOps, etc.) to Codex.
Uses pluggable RMM provider pattern for vendor-agnostic data sync.

Usage:
    python sync_rmm.py                      # Use default provider from config
    python sync_rmm.py --provider datto     # Use specific provider
    python sync_rmm.py --test-connection    # Test connection only
"""

import sys
import os
import argparse
import configparser
from datetime import datetime

# Add the project root to the path so we can import models
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import db, Company, Asset, RMMSiteLink
from app import app
from app.rmm import get_provider, get_default_provider

# The site variable name used for linking RMM sites to companies
ACCOUNT_NUMBER_VARIABLE = "AccountNumber"


def get_config():
    """Load configuration from codex.conf."""
    instance_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
    config_path = os.path.join(instance_path, 'codex.conf')
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found at {config_path}")

    print(f"Loading configuration from: {config_path}")
    config = configparser.RawConfigParser()
    config.read(config_path)
    return config


def sync_rmm_data(provider_name=None):
    """
    Sync data from RMM system to Codex.

    Args:
        provider_name: Optional provider name (if None, use default from config)
    """
    config = get_config()

    # Load RMM provider
    if provider_name:
        print(f"Using specified RMM provider: {provider_name}")
        rmm_provider = get_provider(provider_name, config)
    else:
        print("Using default RMM provider from config")
        rmm_provider = get_default_provider(config)

    print(f"RMM Provider: {rmm_provider.display_name}")

    # Authenticate
    print("Authenticating with RMM system...")
    try:
        rmm_provider.authenticate()
        print(f"✓ Successfully authenticated with {rmm_provider.display_name}")
    except Exception as e:
        print(f"FATAL: Could not authenticate with RMM system: {e}", file=sys.stderr)
        sys.exit(1)

    # Sync sites
    print("\nFetching sites from RMM system...")
    try:
        sites = rmm_provider.sync_sites()
        print(f"✓ Found {len(sites)} sites.")
    except Exception as e:
        print(f"FATAL: Could not retrieve sites from RMM system: {e}", file=sys.stderr)
        sys.exit(1)

    # Group sites by account number
    print("\nGrouping sites by AccountNumber...")
    sites_by_account = {}

    for site in sites:
        # Get AccountNumber variable for this site
        try:
            account_number = rmm_provider.get_site_variable(site['external_id'], ACCOUNT_NUMBER_VARIABLE)
        except Exception as e:
            print(f" -> WARNING: Could not get AccountNumber for site '{site['name']}': {e}")
            account_number = None

        if account_number:
            if account_number not in sites_by_account:
                sites_by_account[account_number] = []
            sites_by_account[account_number].append(site)
        else:
            print(f" -> WARNING: No AccountNumber for site '{site['name']}'. Skipping.")

    print(f"✓ Grouped {len(sites_by_account)} companies with AccountNumber")

    # Process each company
    print("\nProcessing companies and their assets...")

    with app.app_context():
        for account_number, site_list in sites_by_account.items():
            company = db.session.get(Company, account_number)
            if not company:
                print(f" -> WARNING: Company with account '{account_number}' not in Codex. Skipping {len(site_list)} site(s).")
                continue

            print(f"\n--- Processing Company: {company.name} ({account_number}) ---")

            # Get existing assets for this company
            existing_assets = Asset.query.filter_by(company_account_number=account_number).all()
            existing_assets_by_hostname = {asset.hostname: asset for asset in existing_assets}

            all_rmm_hostnames = set()

            for site in site_list:
                site_id = site['external_id']
                site_name = site['name']

                # Link site to company (vendor-agnostic)
                link = RMMSiteLink.query.filter_by(
                    rmm_site_uid=site_id,
                    rmm_provider=rmm_provider.name
                ).first()
                if not link:
                    link = RMMSiteLink(
                        company_account_number=account_number,
                        rmm_site_uid=site_id,
                        rmm_provider=rmm_provider.name
                    )
                    db.session.add(link)
                    try:
                        db.session.commit()
                        print(f" -> Linked site '{site_name}' to company '{company.name}'.")
                    except Exception as e:
                        print(f" -> ERROR linking site '{site_name}': {e}", file=sys.stderr)
                        db.session.rollback()
                        continue

                # Get devices for this site
                print(f"   -> Fetching devices for site '{site_name}'...")
                try:
                    devices = rmm_provider.sync_devices(site_id=site_id)
                except Exception as e:
                    print(f"   -> ERROR fetching devices for site '{site_name}': {e}", file=sys.stderr)
                    continue

                if not devices:
                    print(f"   -> No devices found for site '{site_name}'.")
                    continue

                print(f"   -> Found {len(devices)} devices. Syncing...")

                for device_data in devices:
                    hostname = device_data.get('hostname')
                    if not hostname:
                        continue

                    all_rmm_hostnames.add(hostname)

                    # Check if asset exists
                    existing_asset = existing_assets_by_hostname.get(hostname)

                    if not existing_asset:
                        # Create new asset
                        asset = Asset(
                            hostname=hostname,
                            company_account_number=account_number
                        )
                        db.session.add(asset)
                        print(f"      -> Created asset '{hostname}'")
                    else:
                        asset = existing_asset

                    # Update asset fields from normalized device data
                    asset.rmm_site_name = device_data.get('site_name')
                    asset.operating_system = device_data.get('operating_system')
                    asset.last_logged_in_user = device_data.get('last_logged_in_user')
                    asset.hardware_type = device_data.get('device_type')
                    asset.ext_ip_address = device_data.get('ip_address_external')
                    asset.int_ip_address = device_data.get('ip_address_internal')
                    asset.domain = device_data.get('domain')
                    asset.last_seen = device_data.get('last_seen')
                    asset.last_reboot = device_data.get('last_reboot')
                    asset.online = device_data.get('online')
                    asset.patch_status = device_data.get('patch_status')
                    asset.antivirus_product = device_data.get('antivirus_product')
                    asset.description = device_data.get('description')
                    asset.last_audit_date = device_data.get('last_audit_date')
                    asset.portal_url = device_data.get('portal_url')
                    asset.web_remote_url = device_data.get('web_remote_url')

                    # Store custom fields (UDF fields, etc.)
                    custom_fields = device_data.get('custom_fields', {})
                    for key, value in custom_fields.items():
                        if hasattr(asset, key):
                            setattr(asset, key, value)

                    try:
                        db.session.commit()
                    except Exception as e:
                        print(f"      -> FAILED to sync asset '{hostname}': {e}", file=sys.stderr)
                        db.session.rollback()

            # Delete assets that no longer exist in RMM
            existing_hostnames = set(existing_assets_by_hostname.keys())
            hostnames_to_delete = existing_hostnames - all_rmm_hostnames

            if hostnames_to_delete:
                print(f"   -> Found {len(hostnames_to_delete)} asset(s) to delete from Codex for '{company.name}'...")
                for hostname in hostnames_to_delete:
                    asset_to_delete = existing_assets_by_hostname[hostname]
                    try:
                        db.session.delete(asset_to_delete)
                        db.session.commit()
                        print(f"      -> Deleted asset '{hostname}' (ID: {asset_to_delete.id})")
                    except Exception as e:
                        print(f"      -> FAILED to delete asset '{hostname}': {e}", file=sys.stderr)
                        db.session.rollback()

    print("\n✓ Finished processing all companies and assets.")


def test_connection(provider_name=None):
    """
    Test connection to RMM system.

    Args:
        provider_name: Optional provider name (if None, use default from config)
    """
    config = get_config()

    # Load RMM provider
    if provider_name:
        print(f"Testing connection to: {provider_name}")
        rmm_provider = get_provider(provider_name, config)
    else:
        print("Testing connection to default RMM provider")
        rmm_provider = get_default_provider(config)

    print(f"Provider: {rmm_provider.display_name}")

    # Test connection
    result = rmm_provider.test_connection()

    if result['success']:
        print(f"✓ {result['message']}")
        sys.exit(0)
    else:
        print(f"✗ {result['message']}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Sync RMM data to Codex')
    parser.add_argument('--provider', type=str, help='RMM provider to use (datto, superops, etc.)')
    parser.add_argument('--test-connection', action='store_true', help='Test connection only (do not sync)')
    args = parser.parse_args()

    print("=" * 60)
    print("  RMM Data Sync")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    try:
        if args.test_connection:
            test_connection(provider_name=args.provider)
        else:
            sync_rmm_data(provider_name=args.provider)
            print("\n" + "=" * 60)
            print("  RMM Data Sync Successful")
            print("=" * 60)

    except Exception as e:
        print(f"\nFATAL ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
