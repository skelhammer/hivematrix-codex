"""
Datto RMM Provider

This module implements the RMMProvider interface for Datto RMM.
It handles OAuth authentication and REST API communication.
"""

import requests
from typing import List, Dict, Any, Optional
from datetime import datetime
from .base import RMMProvider, AuthenticationError, APIError


class DattoRMMProvider(RMMProvider):
    """
    Datto RMM provider implementation.

    Uses OAuth2 password grant for authentication.
    REST API endpoints for device and site management.
    """

    name = 'datto'
    display_name = 'Datto RMM'

    def __init__(self, config):
        """
        Initialize Datto RMM provider.

        Args:
            config: ConfigParser object with [datto] section containing:
                - api_endpoint: Datto API URL (e.g., https://instance.centrastage.net)
                - public_key: Datto API public key
                - secret_key: Datto API secret key
        """
        super().__init__(config)

        try:
            self.api_endpoint = config.get('datto', 'api_endpoint')
            self.public_key = config.get('datto', 'public_key')
            self.secret_key = config.get('datto', 'secret_key')
        except Exception as e:
            raise AuthenticationError(f"Missing Datto configuration: {e}")

        self.access_token = None

    def authenticate(self) -> bool:
        """Authenticate with Datto RMM using OAuth2 password grant."""
        token_url = f"{self.api_endpoint}/auth/oauth/token"
        payload = {
            'grant_type': 'password',
            'username': self.public_key,
            'password': self.secret_key
        }
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': 'Basic cHVibGljLWNsaWVudDpwdWJsaWM='
        }

        try:
            response = requests.post(token_url, headers=headers, data=payload, timeout=30)
            response.raise_for_status()
            self.access_token = response.json().get("access_token")
            self._authenticated = True
            return True
        except requests.RequestException as e:
            raise AuthenticationError(f"Datto authentication failed: {e}")

    def test_connection(self) -> Dict[str, Any]:
        """Test connection to Datto RMM."""
        try:
            if not self._authenticated:
                self.authenticate()
            return {'success': True, 'message': 'Connected to Datto RMM'}
        except AuthenticationError as e:
            return {'success': False, 'message': str(e)}

    # ========== Site Methods ==========

    def sync_sites(self) -> List[Dict[str, Any]]:
        """Fetch all sites from Datto RMM with pagination."""
        if not self._authenticated:
            self.authenticate()

        all_sites = []
        next_page_url = f"{self.api_endpoint}/api/v2/account/sites"
        headers = {'Authorization': f'Bearer {self.access_token}'}

        while next_page_url:
            response = self._api_get(next_page_url, headers)
            data = response.json()
            sites = data.get('sites', [])

            for site in sites:
                all_sites.append(self._normalize_site(site))

            next_page_url = data.get('pageDetails', {}).get('nextPageUrl')

        return all_sites

    def get_site(self, external_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single site by UID."""
        if not self._authenticated:
            self.authenticate()

        url = f"{self.api_endpoint}/api/v2/site/{external_id}"
        headers = {'Authorization': f'Bearer {self.access_token}'}

        try:
            response = self._api_get(url, headers)
            site = response.json().get('site')
            if site:
                return self._normalize_site(site)
        except APIError:
            pass
        return None

    def get_site_variable(self, site_id: str, variable_name: str) -> Optional[str]:
        """Get a custom site variable value."""
        if not self._authenticated:
            self.authenticate()

        url = f"{self.api_endpoint}/api/v2/site/{site_id}/variables"
        headers = {'Authorization': f'Bearer {self.access_token}'}

        try:
            response = self._api_get(url, headers)
            variables = response.json().get("variables", [])

            for var in variables:
                if var.get("name") == variable_name:
                    return var.get("value")
        except APIError:
            pass
        return None

    def set_site_variable(self, site_id: str, variable_name: str, value: str) -> bool:
        """Set a custom site variable value."""
        if not self._authenticated:
            self.authenticate()

        url = f"{self.api_endpoint}/api/v2/site/{site_id}/variable"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
        payload = {
            "name": variable_name,
            "value": str(value)
        }

        try:
            response = requests.put(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            return True
        except requests.RequestException:
            return False

    def _normalize_site(self, site: Dict) -> Dict[str, Any]:
        """Convert Datto site to normalized format."""
        return {
            'external_id': site.get('uid'),
            'name': site.get('name'),
            'description': site.get('description'),
            'account_number': None,  # Must be fetched via get_site_variable
            'custom_fields': {}
        }

    # ========== Device Methods ==========

    def sync_devices(self, site_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetch devices from Datto RMM.

        Args:
            site_id: Optional site UID to filter devices

        Returns:
            List of normalized device dicts
        """
        if not self._authenticated:
            self.authenticate()

        if site_id:
            return self._get_devices_for_site(site_id)
        else:
            # Fetch all sites, then all devices
            sites = self.sync_sites()
            all_devices = []
            for site in sites:
                devices = self._get_devices_for_site(site['external_id'])
                all_devices.extend(devices)
            return all_devices

    def _get_devices_for_site(self, site_uid: str) -> List[Dict[str, Any]]:
        """Fetch all devices for a specific site."""
        all_devices = []
        next_page_url = f"{self.api_endpoint}/api/v2/site/{site_uid}/devices"
        headers = {'Authorization': f'Bearer {self.access_token}'}

        while next_page_url:
            response = self._api_get(next_page_url, headers)
            data = response.json()
            devices = data.get('devices', [])

            for device in devices:
                all_devices.append(self._normalize_device(device, site_uid))

            next_page_url = data.get('pageDetails', {}).get('nextPageUrl')

        return all_devices

    def get_device(self, external_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single device by ID.

        Note: Datto doesn't have a direct device endpoint, need site context.
        This is a limitation of Datto's API.
        """
        raise NotImplementedError("Datto RMM requires site context to fetch devices. Use sync_devices(site_id) instead.")

    def _normalize_device(self, device: Dict, site_id: str) -> Dict[str, Any]:
        """Convert Datto device to normalized format."""
        udf = device.get('udf', {})

        # Get site name from device data if available
        site_name = device.get('siteName', '')

        return {
            'external_id': device.get('uid'),
            'hostname': device.get('hostname'),
            'site_id': site_id,
            'site_name': site_name,
            'device_type': (device.get('deviceType') or {}).get('category'),
            'operating_system': device.get('operatingSystem'),
            'manufacturer': None,  # Not provided by Datto
            'model': None,  # Not provided by Datto
            'serial_number': None,  # Not provided by Datto
            'ip_address_internal': device.get('intIpAddress'),
            'ip_address_external': device.get('extIpAddress'),
            'mac_address': None,  # Not provided by Datto
            'online': device.get('online'),
            'last_seen': self._format_timestamp(device.get('lastSeen')),
            'last_reboot': self._format_timestamp(device.get('lastReboot')),
            'last_audit_date': self._format_timestamp(device.get('lastAuditDate')),
            'last_logged_in_user': device.get('lastLoggedInUser'),
            'domain': device.get('domain'),
            'antivirus_product': (device.get('antivirus') or {}).get('antivirusProduct'),
            'patch_status': (device.get('patchManagement') or {}).get('patchStatus'),
            'description': device.get('description'),
            'portal_url': device.get('portalUrl'),
            'web_remote_url': device.get('webRemoteUrl'),
            'custom_fields': {
                # UDF fields (User Defined Fields 1-30)
                **{f'udf{i}': udf.get(f'udf{i}') for i in range(1, 31)},
                # Special UDF mappings
                'backup_usage_tb': self._bytes_to_tb(udf.get('udf6')),
                'enabled_administrators': udf.get('udf4'),
                'device_type_udf': udf.get('udf7'),
            }
        }

    def _format_timestamp(self, ts) -> Optional[str]:
        """Convert millisecond epoch timestamp to ISO format."""
        if not ts:
            return None
        try:
            return datetime.fromtimestamp(ts / 1000).isoformat()
        except (ValueError, TypeError, OSError):
            return None

    def _bytes_to_tb(self, b) -> Optional[str]:
        """Convert bytes to terabytes and return as formatted string."""
        if not b:
            return None
        try:
            b_float = float(b)
            tb = b_float / (1024**4)
            return f"{tb:.2f}"
        except (ValueError, TypeError):
            return None

    # ========== Internal Helpers ==========

    def _api_get(self, url: str, headers: Dict) -> requests.Response:
        """Make GET request with error handling."""
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            raise APIError(f"Datto API error: {e}")
