# HiveMatrix Codex

Central data repository for companies, contacts, assets, and integrations.

## Overview

Codex is the "rolodex" of HiveMatrix - it aggregates data from external systems (PSA systems, Datto RMM) and provides a unified API for all company and asset information.

**Port:** 5010

## Features

- **Company Management** - Company profiles with account numbers
- **Contact Directory** - Employee and contact information
- **Asset Inventory** - Workstations, servers, VMs, network equipment
- **Ticket Sync** - PSA ticket integration
- **Agent Management** - PSA agent data
- **User Preferences** - Theme and home page settings

## Tech Stack

- Flask + Gunicorn
- PostgreSQL
- SQLAlchemy ORM

## Key Endpoints

- `GET /api/companies` - List all companies
- `GET /api/companies/<id>` - Get company details
- `GET /api/contacts` - List contacts
- `GET /api/assets` - List assets
- `GET /api/tickets/active` - Get active tickets
- `GET /api/psa/agents` - List PSA agents
- `PUT /api/my/settings` - Update user preferences

## Integrations

- **PSA Systems** - Ticket and agent sync via `sync_psa.py`
- **Datto RMM** - Asset sync via `pull_datto_rmm.py`

## Environment Variables

- `CORE_SERVICE_URL` - Core service URL
- `DATTO_API_KEY` - Datto RMM API key
- `DATTO_API_SECRET` - Datto RMM API secret

PSA credentials are configured in `instance/codex.conf`

## Documentation

For complete installation, configuration, and architecture documentation:

**[HiveMatrix Documentation](https://skelhammer.github.io/hivematrix-docs/)**

## License

MIT License - See LICENSE file
