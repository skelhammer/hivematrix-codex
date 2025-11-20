"""
PSA (Professional Services Automation) Provider Module

This module provides a unified interface for interacting with different
PSA/ticketing systems (Freshservice, Superops, etc.).

Usage:
    from app.psa import get_provider, map_status, map_priority

    # Get a provider instance
    provider = get_provider('freshservice', config)

    # Map status/priority
    normalized_status = map_status('freshservice', 2)  # Returns 'open'
"""

from .mappings import (
    map_status,
    map_priority,
    reverse_map_status,
    reverse_map_priority,
    get_group_id,
    get_status_display_name,
    get_priority_display_name,
    STATUS_MAPPINGS,
    PRIORITY_MAPPINGS,
    GROUP_MAPPINGS,
    STATUS_DISPLAY_NAMES,
    PRIORITY_DISPLAY_NAMES,
    COMMON_STATUS_DISPLAY_NAMES,
    COMMON_PRIORITY_DISPLAY_NAMES,
)
from .base import PSAProvider, PSAProviderError, AuthenticationError, APIError, RateLimitError
from .freshservice import FreshserviceProvider
from .superops import SuperopsProvider

# Provider registry
PSA_PROVIDERS = {
    'freshservice': FreshserviceProvider,
    'superops': SuperopsProvider,
}


def get_provider(provider_name: str, config):
    """
    Get a PSA provider instance by name.

    Args:
        provider_name: Name of the provider ('freshservice', 'superops', etc.)
        config: Configuration object with provider credentials

    Returns:
        PSAProvider instance

    Raises:
        ValueError: If provider is not found in registry
        NotImplementedError: If provider is registered but not yet implemented
    """
    provider_class = PSA_PROVIDERS.get(provider_name)
    if not provider_class:
        raise ValueError(f"Unknown PSA provider: {provider_name}. "
                        f"Available providers: {list(PSA_PROVIDERS.keys())}")
    return provider_class(config)


def list_providers():
    """List all registered PSA providers."""
    return list(PSA_PROVIDERS.keys())


__all__ = [
    # Factory functions
    'get_provider',
    'list_providers',
    # Base classes and exceptions
    'PSAProvider',
    'PSAProviderError',
    'AuthenticationError',
    'APIError',
    'RateLimitError',
    # Provider implementations
    'FreshserviceProvider',
    'SuperopsProvider',
    'PSA_PROVIDERS',
    # Mapping functions
    'map_status',
    'map_priority',
    'reverse_map_status',
    'reverse_map_priority',
    'get_group_id',
    'get_status_display_name',
    'get_priority_display_name',
    # Mapping data
    'STATUS_MAPPINGS',
    'PRIORITY_MAPPINGS',
    'GROUP_MAPPINGS',
    'STATUS_DISPLAY_NAMES',
    'PRIORITY_DISPLAY_NAMES',
    'COMMON_STATUS_DISPLAY_NAMES',
    'COMMON_PRIORITY_DISPLAY_NAMES',
]
