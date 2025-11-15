#!/usr/bin/env python3
"""
Initialize Feature Category Configuration

Sets up display names for feature categories (e.g., 'soc' → 'SOC', 'sat' → 'SAT').
"""

import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, FeatureCategoryConfig

def init_feature_categories():
    """Initialize feature category display names."""
    print("=" * 80)
    print("INITIALIZING FEATURE CATEGORY DISPLAY NAMES")
    print("=" * 80)

    with app.app_context():
        # Define feature categories with proper display names
        categories = [
            {
                'feature_key': 'soc',
                'display_name': 'SOC',
                'full_name': 'Security Operations Center',
                'description': 'Security monitoring and incident response service'
            },
            {
                'feature_key': 'sat',
                'display_name': 'SAT',
                'full_name': 'Security Awareness Training',
                'description': 'Employee security training and phishing simulation'
            },
            {
                'feature_key': 'antivirus',
                'display_name': 'Antivirus',
                'full_name': 'Endpoint Detection and Response',
                'description': 'Antivirus and endpoint protection software'
            },
            {
                'feature_key': 'password_manager',
                'display_name': 'Password Manager',
                'full_name': 'Password Management',
                'description': 'Enterprise password vault and management'
            },
            {
                'feature_key': 'email_security',
                'display_name': 'Email Security',
                'full_name': 'Email Security and Filtering',
                'description': 'Advanced email threat protection'
            },
            {
                'feature_key': 'network_management',
                'display_name': 'Network Management',
                'full_name': 'Network Monitoring and Management',
                'description': 'Network device monitoring and management'
            },
        ]

        added = 0
        updated = 0
        skipped = 0

        for category in categories:
            existing = FeatureCategoryConfig.query.filter_by(feature_key=category['feature_key']).first()

            if existing:
                # Update if display_name changed
                if existing.display_name != category['display_name']:
                    print(f"Updating {category['feature_key']}: '{existing.display_name}' → '{category['display_name']}'")
                    existing.display_name = category['display_name']
                    existing.full_name = category.get('full_name')
                    existing.description = category.get('description')
                    updated += 1
                else:
                    print(f"Skipped {category['feature_key']}: already configured as '{existing.display_name}'")
                    skipped += 1
            else:
                # Add new
                new_config = FeatureCategoryConfig(
                    feature_key=category['feature_key'],
                    display_name=category['display_name'],
                    full_name=category.get('full_name'),
                    description=category.get('description')
                )
                db.session.add(new_config)
                print(f"Added {category['feature_key']}: '{category['display_name']}'")
                added += 1

        db.session.commit()

        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Added: {added}")
        print(f"Updated: {updated}")
        print(f"Skipped: {skipped}")
        print("=" * 80)

        return added + updated


if __name__ == '__main__':
    try:
        result = init_feature_categories()
        print(f"\n✓ Successfully initialized feature categories")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
