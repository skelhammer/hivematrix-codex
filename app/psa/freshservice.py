"""
Freshservice PSA Provider

This module implements the PSAProvider interface for Freshservice.
It handles all communication with the Freshservice API.
"""

import requests
import json
import time
import re
from typing import List, Dict, Any, Optional
from .base import PSAProvider, AuthenticationError, APIError, RateLimitError
from .mappings import map_status, map_priority, STATUS_MAPPINGS, PRIORITY_MAPPINGS


def strip_html(html_content):
    """Remove HTML tags and return plain text."""
    if not html_content:
        return ""
    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', '', html_content)
    # Decode HTML entities
    clean = clean.replace('&nbsp;', ' ')
    clean = clean.replace('&lt;', '<')
    clean = clean.replace('&gt;', '>')
    clean = clean.replace('&amp;', '&')
    clean = clean.replace('&quot;', '"')
    # Clean up whitespace
    clean = ' '.join(clean.split())
    return clean.strip()


class FreshserviceProvider(PSAProvider):
    """
    Freshservice PSA provider implementation.

    Handles authentication and data sync with Freshservice API.
    """

    name = 'freshservice'
    display_name = 'Freshservice'

    def __init__(self, config):
        """
        Initialize Freshservice provider.

        Args:
            config: ConfigParser object with [freshservice] section containing:
                - domain: API domain (e.g., 'company.freshservice.com')
                - api_key: Freshservice API key
                - web_domain: (optional) Custom domain for ticket links
        """
        super().__init__(config)

        # Load credentials from config
        try:
            self.domain = config.get('freshservice', 'domain')
            self.api_key = config.get('freshservice', 'api_key')
            self.web_domain = config.get('freshservice', 'web_domain', fallback=self.domain)
        except Exception as e:
            raise AuthenticationError(f"Missing Freshservice configuration: {e}")

        self.base_url = f"https://{self.domain}/api/v2"
        self.auth = (self.api_key, 'X')  # Freshservice uses API key as username, 'X' as password

    def authenticate(self) -> bool:
        """Test authentication by fetching current user."""
        try:
            response = requests.get(
                f"{self.base_url}/agents/me",
                auth=self.auth,
                timeout=30
            )
            if response.status_code == 200:
                self._authenticated = True
                return True
            elif response.status_code == 401:
                raise AuthenticationError("Invalid Freshservice API key")
            else:
                raise AuthenticationError(f"Authentication failed: {response.status_code}")
        except requests.RequestException as e:
            raise AuthenticationError(f"Connection failed: {e}")

    def test_connection(self) -> Dict[str, Any]:
        """Test connection to Freshservice."""
        try:
            self.authenticate()
            return {'success': True, 'message': 'Connected to Freshservice'}
        except AuthenticationError as e:
            return {'success': False, 'message': str(e)}

    # ========== Company/Organization Methods ==========

    def sync_companies(self) -> List[Dict[str, Any]]:
        """Fetch all departments (companies) from Freshservice."""
        companies = []
        page = 1
        per_page = 100

        while True:
            response = self._api_get(
                '/departments',
                params={'page': page, 'per_page': per_page}
            )

            departments = response.get('departments', [])
            if not departments:
                break

            for dept in departments:
                companies.append(self._normalize_company(dept))

            if len(departments) < per_page:
                break
            page += 1
            time.sleep(0.5)  # Rate limit protection

        return companies

    def get_company(self, external_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single department by ID."""
        try:
            response = self._api_get(f'/departments/{external_id}')
            dept = response.get('department')
            if dept:
                return self._normalize_company(dept)
        except APIError:
            pass
        return None

    def _normalize_company(self, dept: Dict) -> Dict[str, Any]:
        """Convert Freshservice department to normalized company format."""
        custom_fields = dept.get('custom_fields', {}) or {}

        return {
            'external_id': dept.get('id'),
            'name': dept.get('name'),
            'description': dept.get('description'),
            'domains': dept.get('domains', []),
            'head_user_id': dept.get('head_user_id'),
            'head_name': dept.get('head_name'),
            'prime_user_id': dept.get('prime_user_id'),
            'prime_user_name': dept.get('prime_user_name'),
            'workspace_id': dept.get('workspace_id'),
            'created_at': dept.get('created_at'),
            'updated_at': dept.get('updated_at'),
            'custom_fields': {
                'account_number': custom_fields.get('account_number'),
                'plan_selected': custom_fields.get('plan_selected'),
                'managed_users': custom_fields.get('managed_users'),
                'managed_devices': custom_fields.get('managed_devices'),
                'managed_network': custom_fields.get('managed_network'),
                'contract_term': custom_fields.get('contract_term'),
                'contract_start_date': custom_fields.get('contract_start_date'),
                'profit_or_non_profit': custom_fields.get('profit_or_non_profit'),
                'company_main_number': custom_fields.get('company_main_number'),
                'address': custom_fields.get('address'),
                'company_start_date': custom_fields.get('company_start_date'),
                'phone_system': custom_fields.get('phone_system'),
                'email_system': custom_fields.get('email_system'),
                'datto_portal_url': custom_fields.get('datto_portal_url'),
            }
        }

    # ========== Contact/User Methods ==========

    def sync_contacts(self) -> List[Dict[str, Any]]:
        """Fetch all requesters (contacts) from Freshservice."""
        contacts = []
        page = 1
        per_page = 100

        while True:
            response = self._api_get(
                '/requesters',
                params={'page': page, 'per_page': per_page}
            )

            requesters = response.get('requesters', [])
            if not requesters:
                break

            for req in requesters:
                contacts.append(self._normalize_contact(req))

            if len(requesters) < per_page:
                break
            page += 1
            time.sleep(0.5)  # Rate limit protection

        return contacts

    def get_contact(self, external_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single requester by ID."""
        try:
            response = self._api_get(f'/requesters/{external_id}')
            req = response.get('requester')
            if req:
                return self._normalize_contact(req)
        except APIError:
            pass
        return None

    def _normalize_contact(self, req: Dict) -> Dict[str, Any]:
        """Convert Freshservice requester to normalized contact format."""
        custom_fields = req.get('custom_fields', {}) or {}

        # Build full name
        first_name = req.get('first_name', '')
        last_name = req.get('last_name', '')
        full_name = f"{first_name} {last_name}".strip()
        if not full_name:
            email = req.get('primary_email', '')
            full_name = email.split('@')[0] if email else ''

        return {
            'external_id': req.get('id'),
            'first_name': first_name,
            'last_name': last_name,
            'name': full_name,
            'email': req.get('primary_email'),
            'mobile_phone_number': req.get('mobile_phone_number'),
            'work_phone_number': req.get('work_phone_number'),
            'job_title': req.get('job_title'),
            'department_ids': req.get('department_ids', []),
            'department_names': req.get('department_names'),
            'active': req.get('active', True),
            'is_agent': req.get('is_agent', False),
            'vip_user': req.get('vip_user', False),
            'has_logged_in': req.get('has_logged_in', False),
            'address': req.get('address'),
            'secondary_emails': req.get('secondary_emails', []),
            'reporting_manager_id': req.get('reporting_manager_id'),
            'location_id': req.get('location_id'),
            'location_name': req.get('location_name'),
            'time_zone': req.get('time_zone'),
            'time_format': req.get('time_format'),
            'language': req.get('language', 'en'),
            'can_see_all_tickets_from_associated_departments': req.get('can_see_all_tickets_from_associated_departments', False),
            'can_see_all_changes_from_associated_departments': req.get('can_see_all_changes_from_associated_departments', False),
            'background_information': req.get('background_information'),
            'work_schedule_id': req.get('work_schedule_id'),
            'created_at': req.get('created_at'),
            'updated_at': req.get('updated_at'),
            'custom_fields': {
                'user_number': custom_fields.get('user_number'),
            }
        }

    # ========== Agent/Technician Methods ==========

    def sync_agents(self) -> List[Dict[str, Any]]:
        """Fetch all agents from Freshservice."""
        agents = []
        page = 1
        per_page = 100

        while True:
            response = self._api_get(
                '/agents',
                params={'page': page, 'per_page': per_page}
            )

            agent_list = response.get('agents', [])
            if not agent_list:
                break

            for agent in agent_list:
                agents.append(self._normalize_agent(agent))

            if len(agent_list) < per_page:
                break
            page += 1
            time.sleep(0.5)  # Rate limit protection

        return agents

    def get_agent(self, external_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single agent by ID."""
        try:
            response = self._api_get(f'/agents/{external_id}')
            agent = response.get('agent')
            if agent:
                return self._normalize_agent(agent)
        except APIError:
            pass
        return None

    def _normalize_agent(self, agent: Dict) -> Dict[str, Any]:
        """Convert Freshservice agent to normalized format."""
        return {
            'external_id': agent.get('id'),
            'first_name': agent.get('first_name'),
            'last_name': agent.get('last_name'),
            'email': agent.get('email'),
            'job_title': agent.get('job_title'),
            'active': agent.get('active', True),
            'group_ids': agent.get('group_ids', []),
            'department_ids': agent.get('department_ids', []),
            'created_at': agent.get('created_at'),
            'updated_at': agent.get('updated_at'),
        }

    # ========== Ticket Methods ==========

    def sync_tickets(self, since: Optional[str] = None,
                     full_history: bool = False) -> List[Dict[str, Any]]:
        """
        Fetch tickets from Freshservice.

        Args:
            since: ISO timestamp to fetch tickets updated after
            full_history: If True, fetch all tickets

        Returns:
            List of normalized ticket dicts
        """
        tickets = []

        # Build query
        if full_history:
            query = '"created_at:>\'2000-01-01\'"'  # Get all tickets since 2000
            print("Fetching ALL tickets (full history)...")
        elif since:
            # Parse and format the timestamp for Freshservice API
            from datetime import datetime
            try:
                # Handle various timestamp formats
                ts = since
                if ts.endswith('Z'):
                    ts = ts[:-1] + '+00:00'
                dt = datetime.fromisoformat(ts)
                since_formatted = dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            except (ValueError, AttributeError):
                # Fallback: use as-is but strip microseconds
                since_formatted = since.split('.')[0]
                if not since_formatted.endswith('Z'):
                    since_formatted = since_formatted.split('+')[0] + 'Z'

            query = f'"updated_at:>\'{since_formatted}\'"'
            print(f"Fetching tickets updated since {since_formatted}...")
        else:
            # Default: get all active (non-closed) tickets
            # These are the statuses we want to show in Beacon
            active_statuses = [2, 3, 8, 9, 10, 13, 19, 23, 26, 27]
            status_conditions = [f"status:{s}" for s in active_statuses]
            query = f'"({" OR ".join(status_conditions)})"'
            print("Fetching all open tickets...")

        page = 1
        per_page = 100

        while True:
            response = self._api_get(
                '/tickets/filter',
                params={
                    'query': query,
                    'page': page,
                    'per_page': per_page
                }
            )

            ticket_list = response.get('tickets', [])
            if not ticket_list:
                break

            for ticket in ticket_list:
                # Fetch full ticket details including conversations
                full_ticket = self.get_ticket(ticket.get('id'))
                if full_ticket:
                    tickets.append(full_ticket)

            print(f"  -> Fetched page {page}, total tickets: {len(tickets)}")

            if len(ticket_list) < per_page:
                break
            page += 1
            time.sleep(1)  # Rate limit protection between pages

        return tickets

    def get_ticket(self, external_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single ticket with full details."""
        try:
            # Get ticket with stats and conversations
            response = self._api_get(
                f'/tickets/{external_id}',
                params={'include': 'stats,conversations'}
            )

            ticket = response.get('ticket')
            if ticket:
                # Get time entries and calculate total hours
                time_entries = self._get_ticket_time_entries(external_id)
                total_hours = 0
                for entry in time_entries:
                    # Parse time_spent string format (like "01:30" or "01:30:00")
                    time_str = entry.get('time_spent', '00:00')
                    try:
                        parts = time_str.split(':')
                        if len(parts) == 2:
                            h, m = map(int, parts)
                            total_hours += h + (m / 60.0)
                        elif len(parts) == 3:
                            h, m, s = map(int, parts)
                            total_hours += h + (m / 60.0) + (s / 3600.0)
                    except (ValueError, AttributeError):
                        pass

                return self._normalize_ticket(ticket, total_hours)
        except APIError:
            pass
        return None

    def _get_ticket_time_entries(self, ticket_id: int) -> List[Dict]:
        """Get time entries for a ticket."""
        try:
            response = self._api_get(f'/tickets/{ticket_id}/time_entries')
            return response.get('time_entries', [])
        except APIError:
            return []

    def _normalize_ticket(self, ticket: Dict, total_hours: float = 0) -> Dict[str, Any]:
        """Convert Freshservice ticket to normalized format."""
        stats = ticket.get('stats', {}) or {}
        conversations = ticket.get('conversations', []) or []

        # Separate conversations from notes
        public_conversations = []
        private_notes = []
        for conv in conversations:
            conv_entry = {
                'id': conv.get('id'),
                'body': strip_html(conv.get('body', '')),
                'body_html': conv.get('body', ''),
                'from_email': conv.get('from_email'),
                'to_emails': conv.get('to_emails', []),
                'created_at': conv.get('created_at'),
                'updated_at': conv.get('updated_at'),
                'incoming': conv.get('incoming', False),
                'private': conv.get('private', False),
                'user_id': conv.get('user_id'),
                'support_email': conv.get('support_email'),
            }

            # Separate private notes from public conversations
            if conv.get('private', False):
                private_notes.append(conv_entry)
            else:
                public_conversations.append(conv_entry)

        # Get requester info from nested object (if available)
        requester = ticket.get('requester', {})
        requester_email = None
        requester_name = None
        if isinstance(requester, dict):
            requester_email = requester.get('email')
            requester_name = requester.get('name')

        # Only set closed_at if ticket status is 5 (Closed)
        status_id = ticket.get('status')
        closed_at = ticket.get('updated_at') if status_id == 5 else None

        return {
            'external_id': ticket.get('id'),
            'ticket_number': str(ticket.get('id')),
            'subject': ticket.get('subject'),
            'description': ticket.get('description'),
            'description_text': strip_html(ticket.get('description_text') or ticket.get('description', '')),
            'status': self.map_status(status_id),
            'status_id': status_id,
            'priority': self.map_priority(ticket.get('priority')),
            'priority_id': ticket.get('priority'),
            'ticket_type': ticket.get('type', 'Incident'),
            'requester_id': ticket.get('requester_id'),
            'requester_email': requester_email,
            'requester_name': requester_name,
            'responder_id': ticket.get('responder_id'),
            'group_id': ticket.get('group_id'),
            'company_id': ticket.get('department_id'),
            'created_at': ticket.get('created_at'),
            'updated_at': ticket.get('updated_at'),
            'closed_at': closed_at,
            'fr_due_by': ticket.get('fr_due_by'),
            'due_by': ticket.get('due_by'),
            'first_responded_at': stats.get('first_responded_at'),
            'agent_responded_at': stats.get('agent_responded_at'),
            'conversations': public_conversations,
            'notes': private_notes,
            'total_hours_spent': total_hours,
        }

    # ========== URL Generation Methods ==========

    def get_ticket_url(self, external_id: int) -> str:
        """Get URL to view ticket in Freshservice."""
        return f"https://{self.web_domain}/a/tickets/{external_id}"

    def get_company_url(self, external_id: int) -> str:
        """Get URL to view department in Freshservice."""
        return f"https://{self.web_domain}/a/admin/departments/{external_id}"

    def get_contact_url(self, external_id: int) -> str:
        """Get URL to view requester in Freshservice."""
        return f"https://{self.web_domain}/a/requesters/{external_id}"

    # ========== Status/Priority Mapping ==========

    def map_status(self, native_status) -> str:
        """Map Freshservice status ID to normalized status."""
        return map_status('freshservice', native_status)

    def map_priority(self, native_priority) -> str:
        """Map Freshservice priority ID to normalized priority."""
        return map_priority('freshservice', native_priority)

    # ========== Optional Methods ==========

    def update_company(self, external_id: int, data: Dict[str, Any]) -> bool:
        """Update a department's custom fields in Freshservice."""
        # Build custom_fields payload
        custom_fields = {}
        field_mapping = {
            'account_number': 'account_number',
            'plan_selected': 'plan_selected',
            'managed_users': 'managed_users',
            'managed_devices': 'managed_devices',
            'managed_network': 'managed_network',
        }

        for key, fs_key in field_mapping.items():
            if key in data:
                custom_fields[fs_key] = data[key]

        if not custom_fields:
            return True  # Nothing to update

        payload = {'custom_fields': custom_fields}

        try:
            self._api_put(f'/departments/{external_id}', payload)
            return True
        except APIError:
            return False

    def get_companies_raw(self) -> List[Dict[str, Any]]:
        """Get all companies with their raw data including custom_fields."""
        companies = []
        page = 1
        per_page = 100

        while True:
            data = self._api_get('/departments', {'page': page, 'per_page': per_page})
            departments = data.get('departments', [])

            if not departments:
                break

            companies.extend(departments)

            if len(departments) < per_page:
                break

            page += 1

        return companies

    def get_time_entries(self, ticket_id: int) -> List[Dict[str, Any]]:
        """Get time entries for a ticket."""
        return self._get_ticket_time_entries(ticket_id)

    # ========== Internal API Methods ==========

    def _api_get(self, endpoint: str, params: Dict = None, max_retries: int = 3) -> Dict:
        """Make GET request to Freshservice API with rate limit handling."""
        url = f"{self.base_url}{endpoint}"
        retries = 0

        while retries < max_retries:
            try:
                response = requests.get(
                    url,
                    auth=self.auth,
                    params=params,
                    timeout=90
                )

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 401:
                    raise AuthenticationError("Invalid API key")
                elif response.status_code == 429:
                    # Rate limit - wait and retry
                    retry_after = int(response.headers.get('Retry-After', 10))
                    print(f"  -> Rate limit hit, waiting {retry_after}s...")
                    time.sleep(retry_after)
                    retries += 1
                    continue
                elif response.status_code == 404:
                    return {}
                else:
                    raise APIError(f"API error {response.status_code}: {response.text}")

            except requests.RequestException as e:
                retries += 1
                if retries >= max_retries:
                    raise APIError(f"Request failed after {max_retries} retries: {e}")
                time.sleep(5)

        raise RateLimitError(f"Rate limit exceeded after {max_retries} retries")

    def _api_put(self, endpoint: str, data: Dict) -> Dict:
        """Make PUT request to Freshservice API."""
        url = f"{self.base_url}{endpoint}"

        try:
            response = requests.put(
                url,
                auth=self.auth,
                json=data,
                headers={'Content-Type': 'application/json'},
                timeout=60
            )

            if response.status_code in (200, 204):
                return response.json() if response.text else {}
            elif response.status_code == 401:
                raise AuthenticationError("Invalid API key")
            elif response.status_code == 429:
                raise RateLimitError("Rate limit exceeded")
            else:
                raise APIError(f"API error {response.status_code}: {response.text}")

        except requests.RequestException as e:
            raise APIError(f"Request failed: {e}")
