"""
PSA Provider Base Class

This module defines the abstract interface that all PSA providers must implement.
Each provider (Freshservice, Superops, etc.) must implement these methods to
provide a unified interface for syncing data.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class PSAProvider(ABC):
    """
    Abstract base class for PSA system integrations.

    All PSA providers (Freshservice, Superops, etc.) must inherit from this
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
            String identifier (e.g., 'freshservice', 'superops')
        """
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """
        Human-readable provider name.

        Returns:
            Display name (e.g., 'Freshservice', 'SuperOps')
        """
        pass

    @abstractmethod
    def authenticate(self) -> bool:
        """
        Authenticate with the PSA system.

        Returns:
            True if authentication successful, False otherwise

        Raises:
            AuthenticationError: If authentication fails
        """
        pass

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        """
        Test the connection to the PSA system.

        Returns:
            Dict with 'success' (bool) and 'message' (str)
        """
        pass

    # ========== Company/Organization Methods ==========

    @abstractmethod
    def sync_companies(self) -> List[Dict[str, Any]]:
        """
        Fetch all companies/organizations from the PSA system.

        Returns:
            List of company dicts with normalized fields:
            - external_id: PSA system ID
            - name: Company name
            - description: Company description
            - domains: List of email domains
            - custom_fields: Dict of custom field values
            - head_user_id: Primary contact ID (optional)
            - prime_user_id: Billing contact ID (optional)
        """
        pass

    @abstractmethod
    def get_company(self, external_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch a single company by its PSA system ID.

        Args:
            external_id: The company's ID in the PSA system

        Returns:
            Company dict or None if not found
        """
        pass

    # ========== Contact/User Methods ==========

    @abstractmethod
    def sync_contacts(self) -> List[Dict[str, Any]]:
        """
        Fetch all contacts/users from the PSA system.

        Returns:
            List of contact dicts with normalized fields:
            - external_id: PSA system ID
            - first_name: First name
            - last_name: Last name
            - email: Primary email
            - phone: Phone number (optional)
            - job_title: Job title (optional)
            - company_ids: List of associated company IDs
            - active: Boolean active status
        """
        pass

    @abstractmethod
    def get_contact(self, external_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch a single contact by their PSA system ID.

        Args:
            external_id: The contact's ID in the PSA system

        Returns:
            Contact dict or None if not found
        """
        pass

    # ========== Agent/Technician Methods ==========

    @abstractmethod
    def sync_agents(self) -> List[Dict[str, Any]]:
        """
        Fetch all agents/technicians from the PSA system.

        Returns:
            List of agent dicts with normalized fields:
            - external_id: PSA system ID
            - first_name: First name
            - last_name: Last name
            - email: Email address
            - job_title: Job title (optional)
            - active: Boolean active status
            - group_ids: List of group/team IDs
            - department_ids: List of department IDs
        """
        pass

    @abstractmethod
    def get_agent(self, external_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch a single agent by their PSA system ID.

        Args:
            external_id: The agent's ID in the PSA system

        Returns:
            Agent dict or None if not found
        """
        pass

    # ========== Ticket Methods ==========

    @abstractmethod
    def sync_tickets(self, since: Optional[str] = None,
                     full_history: bool = False) -> List[Dict[str, Any]]:
        """
        Fetch tickets from the PSA system.

        Args:
            since: ISO timestamp to fetch tickets updated after this time
            full_history: If True, fetch all tickets regardless of 'since'

        Returns:
            List of ticket dicts with normalized fields:
            - external_id: PSA system ticket ID
            - ticket_number: Display ticket number
            - subject: Ticket subject
            - description: Ticket description (HTML)
            - description_text: Plain text description
            - status: Normalized status string
            - status_id: Original PSA status value
            - priority: Normalized priority string
            - priority_id: Original PSA priority value
            - ticket_type: 'Incident' or 'Service Request'
            - requester_id: Requester's PSA ID
            - requester_email: Requester's email
            - requester_name: Requester's name
            - responder_id: Assigned agent's PSA ID
            - group_id: Assigned group/team ID
            - company_id: Associated company's PSA ID
            - created_at: ISO timestamp
            - updated_at: ISO timestamp
            - closed_at: ISO timestamp (if closed)
            - conversations: List of conversation entries
            - notes: List of internal notes
            - time_entries: Total hours logged
        """
        pass

    @abstractmethod
    def get_ticket(self, external_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch a single ticket with full details.

        Args:
            external_id: The ticket's ID in the PSA system

        Returns:
            Ticket dict with all fields, or None if not found
        """
        pass

    # ========== URL Generation Methods ==========

    @abstractmethod
    def get_ticket_url(self, external_id: int) -> str:
        """
        Get the URL to view a ticket in the PSA web interface.

        Args:
            external_id: The ticket's ID in the PSA system

        Returns:
            Full URL to the ticket
        """
        pass

    @abstractmethod
    def get_company_url(self, external_id: int) -> str:
        """
        Get the URL to view a company in the PSA web interface.

        Args:
            external_id: The company's ID in the PSA system

        Returns:
            Full URL to the company
        """
        pass

    @abstractmethod
    def get_contact_url(self, external_id: int) -> str:
        """
        Get the URL to view a contact in the PSA web interface.

        Args:
            external_id: The contact's ID in the PSA system

        Returns:
            Full URL to the contact
        """
        pass

    # ========== Status/Priority Mapping Methods ==========

    @abstractmethod
    def map_status(self, native_status) -> str:
        """
        Convert PSA-specific status to normalized status.

        Args:
            native_status: The status value from the PSA system

        Returns:
            Normalized status string ('open', 'pending', etc.)
        """
        pass

    @abstractmethod
    def map_priority(self, native_priority) -> str:
        """
        Convert PSA-specific priority to normalized priority.

        Args:
            native_priority: The priority value from the PSA system

        Returns:
            Normalized priority string ('low', 'medium', etc.)
        """
        pass

    # ========== Optional Methods (override if supported) ==========

    def update_company(self, external_id: int, data: Dict[str, Any]) -> bool:
        """
        Update a company in the PSA system.

        Args:
            external_id: The company's ID in the PSA system
            data: Dict of fields to update

        Returns:
            True if update successful

        Raises:
            NotImplementedError: If provider doesn't support updates
        """
        raise NotImplementedError(f"{self.display_name} provider does not support company updates")

    def create_ticket(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new ticket in the PSA system.

        Args:
            data: Dict with ticket fields

        Returns:
            Created ticket dict

        Raises:
            NotImplementedError: If provider doesn't support ticket creation
        """
        raise NotImplementedError(f"{self.display_name} provider does not support ticket creation")

    def get_time_entries(self, ticket_id: int) -> List[Dict[str, Any]]:
        """
        Get time entries for a ticket.

        Args:
            ticket_id: The ticket's ID in the PSA system

        Returns:
            List of time entry dicts

        Raises:
            NotImplementedError: If provider doesn't support time entries
        """
        raise NotImplementedError(f"{self.display_name} provider does not support time entries")


class PSAProviderError(Exception):
    """Base exception for PSA provider errors."""
    pass


class AuthenticationError(PSAProviderError):
    """Raised when authentication fails."""
    pass


class APIError(PSAProviderError):
    """Raised when an API call fails."""
    pass


class RateLimitError(PSAProviderError):
    """Raised when rate limit is exceeded."""
    pass
