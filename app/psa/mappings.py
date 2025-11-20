"""
PSA Status and Priority Mappings

This module contains the mappings from PSA-specific status/priority values
to normalized HiveMatrix values. When adding a new PSA provider, add its
mappings here.

Normalized Status Values:
- 'open' - New ticket, needs first response
- 'pending' - Waiting on internal action
- 'waiting_customer' - Waiting for customer response
- 'on_hold' - Temporarily paused
- 'resolved' - Solution provided, awaiting confirmation
- 'closed' - Ticket completed

Normalized Priority Values:
- 'low' - No rush, handle when available
- 'medium' - Normal priority
- 'high' - Needs attention soon
- 'urgent' - Critical, needs immediate attention
"""

# Common/universal display names for standard statuses
# These are defaults that apply across all providers
COMMON_STATUS_DISPLAY_NAMES = {
    'open': 'Open',
    'pending': 'Pending',
    'resolved': 'Resolved',
    'closed': 'Closed',
    'on_hold': 'On Hold',
    'waiting_customer': 'Waiting on Customer',
    'unknown': 'Unknown',
}

# Provider-specific display names (for custom statuses)
STATUS_DISPLAY_NAMES = {
    'freshservice': {
        'open': 'Open',
        'pending': 'Pending',
        'resolved': 'Resolved',
        'closed': 'Closed',
        'scheduled': 'Scheduled',
        'waiting_customer': 'Waiting on Customer',
        'waiting_third_party': 'Waiting on Third Party',
        'under_investigation': 'Under Investigation',
        'job_complete_bill': 'Job Complete - Bill',
        'billing_complete': 'Billing Complete - Close',
        'update_needed': 'Update Needed',
        'on_hold': 'On Hold',
        'customer_replied': 'Customer Replied',
        'pending_hubspot': 'Pending Hubspot',
    },
    'superops': {
        # TODO: Add Superops display names when implemented
    },
}

# Common/universal display names for priorities
COMMON_PRIORITY_DISPLAY_NAMES = {
    'low': 'Low',
    'medium': 'Medium',
    'high': 'High',
    'urgent': 'Urgent',
    'unknown': 'Unknown',
}

# Provider-specific priority display names (if needed)
PRIORITY_DISPLAY_NAMES = {
    'freshservice': {
        'low': 'Low',
        'medium': 'Medium',
        'high': 'High',
        'urgent': 'Urgent',
    },
    'superops': {
        # TODO: Add Superops priority names when implemented
    },
}

# Status mappings from PSA-specific values to normalized values
STATUS_MAPPINGS = {
    'freshservice': {
        # Standard Freshservice statuses
        2: 'open',
        3: 'pending',
        4: 'resolved',
        5: 'closed',
        # Custom statuses
        8: 'scheduled',              # Scheduled
        9: 'waiting_customer',       # Waiting on Customer
        10: 'waiting_third_party',   # Waiting on Third Party
        13: 'under_investigation',   # Under Investigation
        15: 'job_complete_bill',     # Job Complete - Bill
        16: 'billing_complete',      # Billing Complete - Close
        19: 'update_needed',         # Update Needed
        23: 'on_hold',               # On Hold
        26: 'customer_replied',      # Customer Replied
        27: 'pending_hubspot',       # Pending Hubspot
    },
    'superops': {
        # TODO: Add Superops status mappings when API documentation is available
        # Example structure:
        # 'new': 'open',
        # 'in_progress': 'pending',
        # 'waiting_for_customer': 'waiting_customer',
        # 'on_hold': 'on_hold',
        # 'resolved': 'resolved',
        # 'closed': 'closed',
    },
}

# Priority mappings from PSA-specific values to normalized values
PRIORITY_MAPPINGS = {
    'freshservice': {
        1: 'low',
        2: 'medium',
        3: 'high',
        4: 'urgent',
    },
    'superops': {
        # TODO: Add Superops priority mappings when API documentation is available
        # Example structure:
        # 'low': 'low',
        # 'normal': 'medium',
        # 'high': 'high',
        # 'critical': 'urgent',
    },
}

# Reverse mappings (normalized to PSA-specific) - useful for creating tickets
STATUS_REVERSE_MAPPINGS = {
    'freshservice': {
        'open': 2,
        'pending': 3,
        'resolved': 4,
        'closed': 5,
        'waiting_customer': 9,
        'on_hold': 23,
    },
    'superops': {
        # TODO: Add when API documentation is available
    },
}

PRIORITY_REVERSE_MAPPINGS = {
    'freshservice': {
        'low': 1,
        'medium': 2,
        'high': 3,
        'urgent': 4,
    },
    'superops': {
        # TODO: Add when API documentation is available
    },
}

# Group/Team mappings (PSA-specific group IDs)
GROUP_MAPPINGS = {
    'freshservice': {
        # Map your Freshservice group IDs to logical names
        'helpdesk': None,  # Default group (no specific ID)
        'professional_services': 19000234009,  # Update with your actual group ID
        # Add more groups as needed
    },
    'superops': {
        # TODO: Add when API documentation is available
    },
}


def map_status(provider: str, native_status) -> str:
    """
    Convert PSA-specific status to normalized status.

    Args:
        provider: PSA provider name (e.g., 'freshservice', 'superops')
        native_status: The status value from the PSA system

    Returns:
        Normalized status string
    """
    provider_mappings = STATUS_MAPPINGS.get(provider, {})
    return provider_mappings.get(native_status, 'unknown')


def map_priority(provider: str, native_priority) -> str:
    """
    Convert PSA-specific priority to normalized priority.

    Args:
        provider: PSA provider name (e.g., 'freshservice', 'superops')
        native_priority: The priority value from the PSA system

    Returns:
        Normalized priority string
    """
    provider_mappings = PRIORITY_MAPPINGS.get(provider, {})
    return provider_mappings.get(native_priority, 'unknown')


def reverse_map_status(provider: str, normalized_status: str):
    """
    Convert normalized status to PSA-specific status.

    Args:
        provider: PSA provider name
        normalized_status: Normalized status string

    Returns:
        PSA-specific status value
    """
    provider_mappings = STATUS_REVERSE_MAPPINGS.get(provider, {})
    return provider_mappings.get(normalized_status)


def reverse_map_priority(provider: str, normalized_priority: str):
    """
    Convert normalized priority to PSA-specific priority.

    Args:
        provider: PSA provider name
        normalized_priority: Normalized priority string

    Returns:
        PSA-specific priority value
    """
    provider_mappings = PRIORITY_REVERSE_MAPPINGS.get(provider, {})
    return provider_mappings.get(normalized_priority)


def get_group_id(provider: str, group_name: str):
    """
    Get PSA-specific group ID from logical group name.

    Args:
        provider: PSA provider name
        group_name: Logical group name (e.g., 'professional_services')

    Returns:
        PSA-specific group ID or None
    """
    provider_groups = GROUP_MAPPINGS.get(provider, {})
    return provider_groups.get(group_name)


def get_status_display_name(normalized_status: str, provider: str = None) -> str:
    """
    Get human-readable display name for a normalized status.

    Args:
        normalized_status: Normalized status string (e.g., 'waiting_customer')
        provider: PSA provider name (e.g., 'freshservice') for provider-specific names

    Returns:
        Display name (e.g., 'Waiting on Customer')
    """
    # Try provider-specific first
    if provider:
        provider_names = STATUS_DISPLAY_NAMES.get(provider, {})
        if normalized_status in provider_names:
            return provider_names[normalized_status]

    # Fall back to common names
    if normalized_status in COMMON_STATUS_DISPLAY_NAMES:
        return COMMON_STATUS_DISPLAY_NAMES[normalized_status]

    # Last resort: format the normalized value
    return normalized_status.replace('_', ' ').title()


def get_priority_display_name(normalized_priority: str, provider: str = None) -> str:
    """
    Get human-readable display name for a normalized priority.

    Args:
        normalized_priority: Normalized priority string (e.g., 'urgent')
        provider: PSA provider name for provider-specific names

    Returns:
        Display name (e.g., 'Urgent')
    """
    # Try provider-specific first
    if provider:
        provider_names = PRIORITY_DISPLAY_NAMES.get(provider, {})
        if normalized_priority in provider_names:
            return provider_names[normalized_priority]

    # Fall back to common names
    if normalized_priority in COMMON_PRIORITY_DISPLAY_NAMES:
        return COMMON_PRIORITY_DISPLAY_NAMES[normalized_priority]

    # Last resort: capitalize
    return normalized_priority.title()
