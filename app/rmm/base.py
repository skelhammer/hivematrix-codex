"""
RMM Provider Base Class

This module defines the abstract interface that all RMM providers must implement.
Each provider (Datto, SuperOps, etc.) must implement these methods to provide
a unified interface for syncing device/asset data.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class RMMProvider(ABC):
    """
    Abstract base class for RMM system integrations.

    All RMM providers (Datto, SuperOps, etc.) must inherit from this
    class and implement all abstract methods.
    """

    def __init__(self, config):
        """
        Initialize the provider with configuration.

        Args:
            config: ConfigParser object with provider credentials
        """
        self.config = config
        self._authenticated = False

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Provider name identifier.

        Returns:
            String identifier (e.g., 'datto', 'superops')
        """
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """
        Human-readable provider name.

        Returns:
            Display name (e.g., 'Datto RMM', 'SuperOps RMM')
        """
        pass

    @abstractmethod
    def authenticate(self) -> bool:
        """
        Authenticate with the RMM system.

        Returns:
            True if authentication successful, False otherwise

        Raises:
            AuthenticationError: If authentication fails
        """
        pass

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        """
        Test the connection to the RMM system.

        Returns:
            Dict with 'success' (bool) and 'message' (str)
        """
        pass

    # ========== Site/Location Methods ==========

    @abstractmethod
    def sync_sites(self) -> List[Dict[str, Any]]:
        """
        Fetch all sites/locations from the RMM system.

        Returns:
            List of site dicts with normalized fields:
            - external_id: RMM system site ID
            - name: Site name
            - account_number: HiveMatrix account number (if available)
            - description: Site description (optional)
            - custom_fields: Dict of custom field values
        """
        pass

    @abstractmethod
    def get_site(self, external_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single site by its RMM system ID.

        Args:
            external_id: The site's ID in the RMM system

        Returns:
            Site dict or None if not found
        """
        pass

    @abstractmethod
    def get_site_variable(self, site_id: str, variable_name: str) -> Optional[str]:
        """
        Get a custom variable/field value for a site.

        Args:
            site_id: The site's ID in the RMM system
            variable_name: Name of the variable (e.g., 'AccountNumber')

        Returns:
            Variable value as string, or None if not found
        """
        pass

    @abstractmethod
    def set_site_variable(self, site_id: str, variable_name: str, value: str) -> bool:
        """
        Set a custom variable/field value for a site.

        Args:
            site_id: The site's ID in the RMM system
            variable_name: Name of the variable
            value: Value to set

        Returns:
            True if successful, False otherwise
        """
        pass

    # ========== Device/Asset Methods ==========

    @abstractmethod
    def sync_devices(self, site_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetch devices/assets from the RMM system.

        Args:
            site_id: Optional site ID to filter devices (if None, fetch all)

        Returns:
            List of device dicts with normalized fields:
            - external_id: RMM system device ID
            - hostname: Device hostname
            - site_id: Site/location ID this device belongs to
            - site_name: Site/location name
            - device_type: 'Workstation', 'Server', 'Laptop', etc.
            - operating_system: OS name and version
            - manufacturer: Hardware manufacturer (Dell, HP, etc.)
            - model: Hardware model
            - serial_number: Device serial number
            - ip_address_internal: Private IP
            - ip_address_external: Public IP
            - mac_address: MAC address
            - online: Boolean online status
            - last_seen: ISO timestamp of last communication
            - last_reboot: ISO timestamp of last reboot
            - last_audit_date: ISO timestamp of last audit
            - last_logged_in_user: Username of last logged in user
            - domain: Windows domain (if applicable)
            - antivirus_product: AV software name
            - patch_status: 'Up to date', 'Missing patches', etc.
            - description: Device description
            - portal_url: URL to device in RMM portal
            - web_remote_url: URL for remote access
            - custom_fields: Dict of RMM-specific fields
        """
        pass

    @abstractmethod
    def get_device(self, external_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single device with full details.

        Args:
            external_id: The device's ID in the RMM system

        Returns:
            Device dict with all fields, or None if not found
        """
        pass

    # ========== Optional Methods (override if supported) ==========

    def get_device_software(self, device_id: str) -> List[Dict[str, Any]]:
        """
        Get installed software list for a device.

        Args:
            device_id: The device's ID in the RMM system

        Returns:
            List of software dicts:
            - name: Software name
            - version: Software version
            - publisher: Software publisher
            - install_date: Installation date (optional)

        Raises:
            NotImplementedError: If provider doesn't support software inventory
        """
        raise NotImplementedError(f"{self.display_name} provider does not support software inventory")

    def get_device_patches(self, device_id: str) -> List[Dict[str, Any]]:
        """
        Get patch/update status for a device.

        Args:
            device_id: The device's ID in the RMM system

        Returns:
            List of patch dicts:
            - patch_id: Patch identifier
            - title: Patch title/description
            - severity: 'Critical', 'Important', 'Moderate', 'Low'
            - installed: Boolean (is patch installed?)
            - install_date: When installed (if installed)

        Raises:
            NotImplementedError: If provider doesn't support detailed patch info
        """
        raise NotImplementedError(f"{self.display_name} provider does not support detailed patch information")

    def get_device_alerts(self, device_id: str) -> List[Dict[str, Any]]:
        """
        Get active alerts for a device.

        Args:
            device_id: The device's ID in the RMM system

        Returns:
            List of alert dicts:
            - alert_id: Alert identifier
            - severity: 'Critical', 'Warning', 'Info'
            - title: Alert title
            - description: Alert description
            - triggered_at: ISO timestamp when alert triggered
            - acknowledged: Boolean (has alert been acknowledged?)

        Raises:
            NotImplementedError: If provider doesn't support alerts
        """
        raise NotImplementedError(f"{self.display_name} provider does not support alert information")

    def execute_script(self, device_id: str, script_id: str, parameters: Dict = None) -> Dict[str, Any]:
        """
        Execute a remote script on a device.

        Args:
            device_id: The device's ID in the RMM system
            script_id: Script identifier
            parameters: Optional script parameters

        Returns:
            Execution result dict:
            - success: Boolean
            - output: Script output (if available)
            - error: Error message (if failed)

        Raises:
            NotImplementedError: If provider doesn't support remote execution
        """
        raise NotImplementedError(f"{self.display_name} provider does not support remote script execution")

    def get_available_scripts(self) -> List[Dict[str, Any]]:
        """
        Get list of available scripts that can be executed.

        Returns:
            List of script dicts:
            - script_id: Script identifier
            - name: Script name
            - description: What the script does
            - platform: 'Windows', 'Linux', 'macOS', 'All'

        Raises:
            NotImplementedError: If provider doesn't support script listing
        """
        raise NotImplementedError(f"{self.display_name} provider does not support script listing")


class RMMProviderError(Exception):
    """Base exception for RMM provider errors."""
    pass


class AuthenticationError(RMMProviderError):
    """Raised when authentication fails."""
    pass


class APIError(RMMProviderError):
    """Raised when an API call fails."""
    pass


class RateLimitError(RMMProviderError):
    """Raised when rate limit is exceeded."""
    pass
