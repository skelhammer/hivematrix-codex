"""
RMM Device Type and Status Mappings

This module contains mappings for normalizing device types and statuses
across different RMM providers (Datto, SuperOps, etc.).

Normalized Device Types:
- 'workstation' - Desktop computer
- 'laptop' - Laptop/notebook
- 'server' - Server
- 'network_device' - Switch, router, firewall, etc.
- 'mobile' - Smartphone, tablet
- 'virtual_machine' - VM
- 'other' - Unknown or other type

Normalized Patch Statuses:
- 'up_to_date' - All patches applied
- 'missing_patches' - Patches available but not installed
- 'reboot_required' - Patches installed, reboot needed
- 'failed' - Patch installation failed
- 'unknown' - Patch status unavailable
"""

# Device type mappings from RMM-specific values to normalized values
DEVICE_TYPE_MAPPINGS = {
    'datto': {
        # Datto device type categories
        'Workstation': 'workstation',
        'Laptop': 'laptop',
        'Server': 'server',
        'ESXI Host': 'server',
        'Virtual Machine': 'virtual_machine',
        'Network Device': 'network_device',
        'Mobile Device': 'mobile',
        'Printer': 'other',
        'Unknown': 'other',
    },
    'superops': {
        # SuperOps asset classes (placeholder for future)
        'Desktop': 'workstation',
        'Laptop': 'laptop',
        'Server': 'server',
        'VM': 'virtual_machine',
        'Network': 'network_device',
        'Mobile': 'mobile',
    },
}

# Patch status mappings from RMM-specific values to normalized values
PATCH_STATUS_MAPPINGS = {
    'datto': {
        # Datto patch statuses
        'Up to Date': 'up_to_date',
        'Missing Patches': 'missing_patches',
        'Reboot Required': 'reboot_required',
        'Patch Failed': 'failed',
        'Unknown': 'unknown',
        None: 'unknown',
    },
    'superops': {
        # SuperOps patch statuses (placeholder for future)
        'Up to date': 'up_to_date',
        'Updates available': 'missing_patches',
        'Reboot required': 'reboot_required',
        'Update failed': 'failed',
    },
}

# Display names for normalized device types
DEVICE_TYPE_DISPLAY_NAMES = {
    'workstation': 'Workstation',
    'laptop': 'Laptop',
    'server': 'Server',
    'network_device': 'Network Device',
    'mobile': 'Mobile Device',
    'virtual_machine': 'Virtual Machine',
    'other': 'Other',
}

# Display names for normalized patch statuses
PATCH_STATUS_DISPLAY_NAMES = {
    'up_to_date': 'Up to Date',
    'missing_patches': 'Missing Patches',
    'reboot_required': 'Reboot Required',
    'failed': 'Failed',
    'unknown': 'Unknown',
}


def map_device_type(provider: str, native_type: str) -> str:
    """
    Map provider-specific device type to normalized type.

    Args:
        provider: Provider name ('datto', 'superops', etc.)
        native_type: Device type from the RMM system

    Returns:
        Normalized device type string
    """
    if not native_type:
        return 'other'

    provider_mappings = DEVICE_TYPE_MAPPINGS.get(provider, {})
    return provider_mappings.get(native_type, 'other')


def map_patch_status(provider: str, native_status: str) -> str:
    """
    Map provider-specific patch status to normalized status.

    Args:
        provider: Provider name ('datto', 'superops', etc.)
        native_status: Patch status from the RMM system

    Returns:
        Normalized patch status string
    """
    if not native_status:
        return 'unknown'

    provider_mappings = PATCH_STATUS_MAPPINGS.get(provider, {})
    return provider_mappings.get(native_status, 'unknown')


def get_device_type_display_name(device_type: str) -> str:
    """
    Get human-readable display name for a normalized device type.

    Args:
        device_type: Normalized device type

    Returns:
        Display name string
    """
    return DEVICE_TYPE_DISPLAY_NAMES.get(device_type, 'Other')


def get_patch_status_display_name(patch_status: str) -> str:
    """
    Get human-readable display name for a normalized patch status.

    Args:
        patch_status: Normalized patch status

    Returns:
        Display name string
    """
    return PATCH_STATUS_DISPLAY_NAMES.get(patch_status, 'Unknown')


def determine_online_status(last_seen: str, threshold_minutes: int = 30) -> bool:
    """
    Determine if a device is online based on last seen timestamp.

    This is useful for providers (like SuperOps) that don't provide
    an explicit online/offline status.

    Args:
        last_seen: ISO timestamp of last communication
        threshold_minutes: Minutes before considering device offline

    Returns:
        True if device is considered online, False otherwise
    """
    if not last_seen:
        return False

    try:
        from datetime import datetime, timedelta, timezone

        # Parse ISO timestamp
        if last_seen.endswith('Z'):
            last_seen_dt = datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
        else:
            last_seen_dt = datetime.fromisoformat(last_seen)

        # Get current time (timezone-aware)
        now = datetime.now(timezone.utc)

        # Calculate time difference
        diff = now - last_seen_dt

        # Online if seen within threshold
        return diff.total_seconds() < (threshold_minutes * 60)

    except (ValueError, TypeError):
        return False
