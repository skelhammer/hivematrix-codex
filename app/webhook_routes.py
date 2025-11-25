"""
Webhook Routes for Codex

This module handles incoming webhooks from external PSA systems (Freshservice, SuperOps, etc.)
to provide real-time ticket updates instead of relying solely on polling.

Architecture:
- Vendor-agnostic base handler with common logic
- Vendor-specific endpoints that normalize data to common format
- Easy to add new PSA providers by creating new endpoint + normalizer

Webhook Flow:
1. PSA sends POST to /webhooks/<provider>/ticket when a ticket changes
2. Codex verifies the webhook secret
3. Vendor-specific handler normalizes the payload
4. Common handler updates the ticket in the database
5. Beacon sees the update on its next refresh (or via future WebSocket)

Security:
- Webhooks require a secret key in the X-Webhook-Secret header
- The secret is configured in codex.conf under [webhooks] section
- IP allowlisting can be enabled for additional security
"""

import os
import json
import configparser
from secrets import compare_digest
from datetime import datetime, timezone
from functools import wraps
from flask import request, jsonify, current_app
from app import app
from models import TicketDetail
from extensions import db
from app.psa.mappings import map_status, map_priority


# =============================================================================
# Configuration
# =============================================================================

def get_webhook_config():
    """Load webhook configuration from codex.conf."""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'instance', 'codex.conf')
    config = configparser.RawConfigParser()
    config.read(config_path)

    return {
        'enabled': config.getboolean('webhooks', 'enabled', fallback=False),
        'secret': config.get('webhooks', 'secret', fallback=None),
        'allowed_ips': config.get('webhooks', 'allowed_ips', fallback='').split(','),
        'log_payloads': config.getboolean('webhooks', 'log_payloads', fallback=False),
    }


# =============================================================================
# Security Decorators
# =============================================================================

def webhook_auth_required(f):
    """
    Decorator to verify webhook authentication.

    Checks:
    1. Webhooks are enabled in config
    2. X-Webhook-Secret header matches configured secret
    3. (Optional) Source IP is in allowed list
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        config = get_webhook_config()

        # Check if webhooks are enabled
        if not config['enabled']:
            current_app.logger.warning("Webhook received but webhooks are disabled")
            return jsonify({'error': 'Webhooks are disabled'}), 503

        # Verify secret using constant-time comparison to prevent timing attacks
        provided_secret = request.headers.get('X-Webhook-Secret') or ''
        configured_secret = config['secret'] or ''
        if not provided_secret or not compare_digest(provided_secret, configured_secret):
            current_app.logger.warning(f"Webhook auth failed - invalid or missing secret from {request.remote_addr}")
            return jsonify({'error': 'Unauthorized'}), 401

        # Optional: Check IP allowlist (if configured)
        allowed_ips = [ip.strip() for ip in config['allowed_ips'] if ip.strip()]
        if allowed_ips and request.remote_addr not in allowed_ips:
            current_app.logger.warning(f"Webhook rejected - IP {request.remote_addr} not in allowlist")
            return jsonify({'error': 'IP not allowed'}), 403

        return f(*args, **kwargs)
    return decorated_function


# =============================================================================
# Common Webhook Handler (Vendor-Agnostic)
# =============================================================================

class WebhookHandler:
    """
    Base webhook handler with common ticket update logic.

    Vendor-specific handlers normalize their payloads to this common format:
    {
        'event': 'updated' | 'created' | 'deleted',
        'ticket_id': int,
        'subject': str (optional),
        'status': str (normalized status),
        'status_id': int (original PSA status ID),
        'priority': str (normalized priority),
        'priority_id': int (original PSA priority ID),
        'requester_email': str (optional),
        'requester_name': str (optional),
        'requester_id': int (optional),
        'responder_id': int (optional),
        'group_id': int (optional),
        'department_id': int (optional),
        'updated_at': str (ISO timestamp),
        'created_at': str (ISO timestamp, for new tickets),
    }
    """

    @staticmethod
    def process_ticket(provider: str, normalized_data: dict):
        """
        Process a normalized ticket webhook payload.

        Args:
            provider: PSA provider name (e.g., 'freshservice', 'superops')
            normalized_data: Ticket data normalized to common format

        Returns:
            tuple: (response_dict, status_code)
        """
        event = normalized_data.get('event', 'updated')
        ticket_id = normalized_data.get('ticket_id')

        if not ticket_id:
            return {'error': 'ticket_id is required'}, 400

        # Handle different event types
        if event == 'deleted':
            return WebhookHandler._handle_deleted(provider, ticket_id, normalized_data)
        elif event == 'created':
            return WebhookHandler._handle_created(provider, ticket_id, normalized_data)
        else:
            return WebhookHandler._handle_updated(provider, ticket_id, normalized_data)

    @staticmethod
    def _handle_updated(provider: str, ticket_id: int, data: dict):
        """Update an existing ticket from webhook data."""
        ticket = TicketDetail.query.filter_by(
            external_id=ticket_id,
            external_source=provider
        ).first()

        if not ticket:
            # Ticket doesn't exist yet - create a minimal record
            current_app.logger.info(f"Webhook for unknown ticket {ticket_id} - creating placeholder")
            return WebhookHandler._handle_created(provider, ticket_id, data)

        # Track what changed for logging
        changes = []

        # Update status if provided
        if 'status' in data and data['status']:
            if ticket.status != data['status']:
                changes.append(f"status: {ticket.status} -> {data['status']}")
                ticket.status = data['status']

            if 'status_id' in data:
                ticket.status_id = data['status_id']

            # Track closed_at for resolved/closed tickets
            if data['status'] in ['closed', 'resolved', 'billing_complete']:
                ticket.closed_at = data.get('updated_at') or datetime.now(timezone.utc).isoformat()

        # Update priority if provided
        if 'priority' in data and data['priority']:
            if ticket.priority != data['priority']:
                changes.append(f"priority: {ticket.priority} -> {data['priority']}")
                ticket.priority = data['priority']

            if 'priority_id' in data:
                ticket.priority_id = data['priority_id']

        # Update subject if provided
        if 'subject' in data and data['subject'] and data['subject'] != ticket.subject:
            changes.append("subject updated")
            ticket.subject = data['subject']

        # Update requester info if provided
        if data.get('requester_email'):
            ticket.requester_email = data['requester_email']
        if data.get('requester_name'):
            ticket.requester_name = data['requester_name']
        if data.get('requester_id'):
            ticket.requester_id = data['requester_id']

        # Update assignment info if provided
        if data.get('responder_id'):
            ticket.responder_id = data['responder_id']
        if data.get('group_id'):
            ticket.group_id = data['group_id']

        # Update timestamps
        ticket.last_updated_at = data.get('updated_at') or datetime.now(timezone.utc).isoformat()
        ticket.webhook_updated_at = datetime.now(timezone.utc).isoformat()

        db.session.commit()

        current_app.logger.info(f"[{provider}] Webhook updated ticket {ticket_id}: {', '.join(changes) if changes else 'metadata only'}")

        return {
            'status': 'updated',
            'ticket_id': ticket_id,
            'provider': provider,
            'changes': changes
        }, 200

    @staticmethod
    def _handle_created(provider: str, ticket_id: int, data: dict):
        """Create a new ticket record from webhook data."""
        # Check if ticket already exists
        existing = TicketDetail.query.filter_by(
            external_id=ticket_id,
            external_source=provider
        ).first()

        if existing:
            return WebhookHandler._handle_updated(provider, ticket_id, data)

        # Create new ticket record
        ticket = TicketDetail(
            external_id=ticket_id,
            external_source=provider,
            ticket_number=str(ticket_id),
            subject=data.get('subject', f'Ticket #{ticket_id}'),
            status=data.get('status', 'open'),
            status_id=data.get('status_id'),
            priority=data.get('priority', 'medium'),
            priority_id=data.get('priority_id'),
            requester_email=data.get('requester_email'),
            requester_name=data.get('requester_name'),
            requester_id=data.get('requester_id'),
            responder_id=data.get('responder_id'),
            group_id=data.get('group_id'),
            department_id=data.get('department_id'),
            created_at=data.get('created_at') or datetime.now(timezone.utc).isoformat(),
            last_updated_at=data.get('updated_at') or datetime.now(timezone.utc).isoformat(),
            webhook_updated_at=datetime.now(timezone.utc).isoformat(),
        )

        db.session.add(ticket)
        db.session.commit()

        current_app.logger.info(f"[{provider}] Webhook created ticket {ticket_id}: {data.get('subject', 'No subject')}")

        return {
            'status': 'created',
            'ticket_id': ticket_id,
            'provider': provider
        }, 201

    @staticmethod
    def _handle_deleted(provider: str, ticket_id: int, data: dict):
        """Mark a ticket as deleted from webhook data."""
        ticket = TicketDetail.query.filter_by(
            external_id=ticket_id,
            external_source=provider
        ).first()

        if not ticket:
            current_app.logger.info(f"[{provider}] Webhook delete for unknown ticket {ticket_id} - ignoring")
            return {'status': 'ignored', 'reason': 'ticket not found'}, 200

        old_status = ticket.status
        new_status = data.get('status', 'deleted')

        ticket.status = new_status
        if 'status_id' in data:
            ticket.status_id = data['status_id']
        ticket.last_updated_at = data.get('updated_at') or datetime.now(timezone.utc).isoformat()
        ticket.webhook_updated_at = datetime.now(timezone.utc).isoformat()

        db.session.commit()

        current_app.logger.info(f"[{provider}] Webhook marked ticket {ticket_id} as {new_status} (was {old_status})")

        return {
            'status': 'deleted',
            'ticket_id': ticket_id,
            'provider': provider,
            'new_status': new_status
        }, 200


# =============================================================================
# Freshservice Webhook Endpoint
# =============================================================================

@app.route('/webhooks/freshservice/ticket', methods=['POST'])
@webhook_auth_required
def freshservice_ticket_webhook():
    """
    Receive ticket updates from Freshservice.

    Expected payload (configure these fields in Freshservice Workflow Automator):
    {
        "event": "ticket.updated",  // or "ticket.created", "ticket.deleted"
        "ticket_id": 12345,
        "subject": "Ticket subject",
        "status_id": 2,
        "priority_id": 3,
        "requester_email": "user@example.com",
        "requester_name": "John Doe",
        "requester_id": 12345,
        "responder_id": 67890,
        "group_id": 19000234009,
        "department_id": 11111,
        "updated_at": "2024-01-15T10:30:00Z",
        "created_at": "2024-01-15T10:00:00Z"
    }

    Returns:
        200: Successfully processed
        400: Invalid payload
        401: Authentication failed
        404: Ticket not found (for updates)
        500: Processing error
    """
    config = get_webhook_config()

    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'No JSON payload'}), 400

        # Log payload if configured (useful for debugging)
        if config['log_payloads']:
            current_app.logger.info(f"[freshservice] Webhook payload: {json.dumps(data, indent=2)}")

        # Normalize Freshservice payload to common format
        normalized = normalize_freshservice_payload(data)

        # Process with common handler
        result, status_code = WebhookHandler.process_ticket('freshservice', normalized)
        return jsonify(result), status_code

    except Exception as e:
        current_app.logger.error(f"[freshservice] Webhook processing error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


def normalize_freshservice_payload(data: dict) -> dict:
    """
    Normalize Freshservice webhook payload to common format.

    Args:
        data: Raw Freshservice webhook payload

    Returns:
        Normalized payload dict
    """
    # Determine event type
    event = data.get('event', 'ticket.updated')
    status_id = data.get('status_id')

    # Map Freshservice event names to common format
    if event == 'ticket.deleted' or status_id in [6, 7]:  # 6=spam, 7=deleted
        normalized_event = 'deleted'
    elif event == 'ticket.created':
        normalized_event = 'created'
    else:
        normalized_event = 'updated'

    # Determine status for deleted tickets
    if status_id == 6:
        normalized_status = 'spam'
    elif status_id == 7:
        normalized_status = 'deleted'
    elif status_id:
        normalized_status = map_status('freshservice', status_id)
    else:
        normalized_status = None

    # Map priority if provided
    priority_id = data.get('priority_id')
    normalized_priority = map_priority('freshservice', priority_id) if priority_id else None

    return {
        'event': normalized_event,
        'ticket_id': data.get('ticket_id'),
        'subject': data.get('subject'),
        'status': normalized_status,
        'status_id': status_id,
        'priority': normalized_priority,
        'priority_id': priority_id,
        'requester_email': data.get('requester_email'),
        'requester_name': data.get('requester_name'),
        'requester_id': data.get('requester_id'),
        'responder_id': data.get('responder_id'),
        'group_id': data.get('group_id'),
        'department_id': data.get('department_id'),
        'updated_at': data.get('updated_at'),
        'created_at': data.get('created_at'),
    }


# =============================================================================
# SuperOps Webhook Endpoint (Template - implement when ready)
# =============================================================================

@app.route('/webhooks/superops/ticket', methods=['POST'])
@webhook_auth_required
def superops_ticket_webhook():
    """
    Receive ticket updates from SuperOps.

    TODO: Implement when SuperOps webhook format is known.

    Expected to receive ticket data from SuperOps and normalize to common format.
    """
    config = get_webhook_config()

    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'No JSON payload'}), 400

        # Log payload if configured
        if config['log_payloads']:
            current_app.logger.info(f"[superops] Webhook payload: {json.dumps(data, indent=2)}")

        # TODO: Implement normalize_superops_payload when SuperOps format is known
        # normalized = normalize_superops_payload(data)
        # result, status_code = WebhookHandler.process_ticket('superops', normalized)
        # return jsonify(result), status_code

        # For now, log and return success (placeholder)
        current_app.logger.info(f"[superops] Webhook received - not yet implemented")
        return jsonify({
            'status': 'received',
            'message': 'SuperOps webhook handler not yet implemented'
        }), 200

    except Exception as e:
        current_app.logger.error(f"[superops] Webhook processing error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


def normalize_superops_payload(data: dict) -> dict:
    """
    Normalize SuperOps webhook payload to common format.

    TODO: Implement when SuperOps webhook format is documented.

    Args:
        data: Raw SuperOps webhook payload

    Returns:
        Normalized payload dict
    """
    # Placeholder - implement based on SuperOps webhook documentation
    return {
        'event': 'updated',
        'ticket_id': data.get('id'),  # Adjust field names as needed
        'subject': data.get('title'),
        'status': None,  # Map from SuperOps status
        'status_id': data.get('status'),
        'priority': None,  # Map from SuperOps priority
        'priority_id': data.get('priority'),
        'requester_email': data.get('requester', {}).get('email'),
        'requester_name': data.get('requester', {}).get('name'),
        'requester_id': data.get('requester', {}).get('id'),
        'responder_id': data.get('assignee_id'),
        'group_id': data.get('team_id'),
        'department_id': data.get('department_id'),
        'updated_at': data.get('updated_at'),
        'created_at': data.get('created_at'),
    }


# =============================================================================
# Webhook Health & Testing Endpoints
# =============================================================================

@app.route('/webhooks/health', methods=['GET'])
def webhook_health():
    """
    Health check endpoint for webhooks.

    Returns webhook configuration status (without exposing secrets).
    Useful for verifying webhook setup.
    """
    config = get_webhook_config()

    return jsonify({
        'status': 'ok',
        'webhooks_enabled': config['enabled'],
        'secret_configured': bool(config['secret']),
        'ip_allowlist_enabled': bool([ip for ip in config['allowed_ips'] if ip.strip()]),
        'supported_providers': ['freshservice', 'superops'],
        'endpoints': {
            'freshservice': '/webhooks/freshservice/ticket',
            'superops': '/webhooks/superops/ticket',
            'test': '/webhooks/test',
            'health': '/webhooks/health',
        },
        'timestamp': datetime.now(timezone.utc).isoformat()
    }), 200


@app.route('/webhooks/test', methods=['POST'])
@webhook_auth_required
def webhook_test():
    """
    Test endpoint to verify webhook authentication is working.

    Send a POST with X-Webhook-Secret header to verify setup.
    """
    return jsonify({
        'status': 'ok',
        'message': 'Webhook authentication successful',
        'source_ip': request.remote_addr,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }), 200
