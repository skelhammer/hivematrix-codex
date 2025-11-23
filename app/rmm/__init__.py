"""
RMM (Remote Monitoring and Management) Provider Module

This module provides a unified interface for interacting with different
RMM systems (Datto, SuperOps, etc.).

Usage:
    from app.rmm import get_provider, map_device_type, map_patch_status

    # Get a provider instance
    provider = get_provider('datto', config)

    # Map device types and patch statuses
    normalized_type = map_device_type('datto', 'Workstation')  # Returns 'workstation'
    normalized_status = map_patch_status('datto', 'Up to Date')  # Returns 'up_to_date'
"""

from .mappings import (
    map_device_type,
    map_patch_status,
    get_device_type_display_name,
    get_patch_status_display_name,
    determine_online_status,
    DEVICE_TYPE_MAPPINGS,
    PATCH_STATUS_MAPPINGS,
    DEVICE_TYPE_DISPLAY_NAMES,
    PATCH_STATUS_DISPLAY_NAMES,
)
from .base import RMMProvider, RMMProviderError, AuthenticationError, APIError, RateLimitError
from .datto import DattoRMMProvider
from .superops import SuperOpsRMMProvider

# Provider registry
RMM_PROVIDERS = {
    'datto': DattoRMMProvider,
    'superops': SuperOpsRMMProvider,
}


def get_provider(provider_name: str, config):
    """
    Get an RMM provider instance by name.

    Args:
        provider_name: Name of the provider ('datto', 'superops', etc.)
        config: Configuration object with provider credentials

    Returns:
        RMMProvider instance

    Raises:
        ValueError: If provider is not found in registry
        NotImplementedError: If provider is registered but not yet implemented
    """
    provider_class = RMM_PROVIDERS.get(provider_name)
    if not provider_class:
        raise ValueError(f"Unknown RMM provider: {provider_name}. "
                        f"Available providers: {list(RMM_PROVIDERS.keys())}")
    return provider_class(config)


def get_default_provider(config):
    """
    Get the default RMM provider from configuration.

    Args:
        config: ConfigParser object with [rmm] section

    Returns:
        RMMProvider instance

    Raises:
        ValueError: If default provider not configured
    """
    if not config.has_section('rmm'):
        # Fallback to 'datto' if no [rmm] section exists (backward compatibility)
        default_provider = 'datto'
    else:
        default_provider = config.get('rmm', 'default_provider', fallback='datto')

    return get_provider(default_provider, config)


def list_providers():
    """List all registered RMM providers."""
    return list(RMM_PROVIDERS.keys())


__all__ = [
    # Factory functions
    'get_provider',
    'get_default_provider',
    'list_providers',
    # Base classes and exceptions
    'RMMProvider',
    'RMMProviderError',
    'AuthenticationError',
    'APIError',
    'RateLimitError',
    # Provider implementations
    'DattoRMMProvider',
    'SuperOpsRMMProvider',
    'RMM_PROVIDERS',
    # Mapping functions
    'map_device_type',
    'map_patch_status',
    'get_device_type_display_name',
    'get_patch_status_display_name',
    'determine_online_status',
    # Mapping data
    'DEVICE_TYPE_MAPPINGS',
    'PATCH_STATUS_MAPPINGS',
    'DEVICE_TYPE_DISPLAY_NAMES',
    'PATCH_STATUS_DISPLAY_NAMES',
]
