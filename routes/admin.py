from flask import Blueprint, render_template, g, request, redirect, url_for, flash, current_app
from app.auth import admin_required
from models import db, Company, Contact, Asset, Location, RMMSiteLink, CompanyFeatureOverride, TicketDetail, SyncJob, Agent, contact_company_link, asset_contact_link
import configparser
import os
from datetime import datetime, timezone


def utc_to_local(utc_timestamp_str):
    """Convert UTC ISO timestamp string to local time string."""
    if not utc_timestamp_str:
        return None
    try:
        # Parse the ISO timestamp
        ts = utc_timestamp_str

        # Handle 'Z' suffix
        if ts.endswith('Z'):
            ts = ts[:-1] + '+00:00'

        # Parse with fromisoformat
        utc_dt = datetime.fromisoformat(ts)

        # If no timezone info, assume UTC
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=timezone.utc)

        # Convert to local time
        local_dt = utc_dt.astimezone()

        # Return formatted for display (no microseconds, no timezone)
        return local_dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        # If parsing fails, try to at least clean up the display
        try:
            # Remove microseconds and timezone for cleaner display
            if 'T' in utc_timestamp_str:
                parts = utc_timestamp_str.split('T')
                date_part = parts[0]
                time_part = parts[1].split('.')[0].split('+')[0].split('-')[0][:8]
                return f"{date_part} {time_part}"
        except Exception:
            pass
        return utc_timestamp_str


def get_sync_display_name(script, provider=None, sync_type=None):
    """Generate a user-friendly display name for a sync job."""
    # Provider display names
    provider_names = {
        'freshservice': 'Freshservice',
        'superops': 'Superops',
    }

    if script == 'psa':
        provider_name = provider_names.get(provider, provider.title() if provider else 'PSA')

        # Ticket syncs - all variants show as "[Provider] Tickets"
        if sync_type and sync_type.startswith('tickets'):
            return f"[{provider_name}] Tickets"
        # Base sync (companies, contacts, agents) - shows as "[Provider] Sync"
        elif sync_type == 'base':
            return f"[{provider_name}] Sync"
        # Full sync - shows as "[Provider] Full Sync"
        elif sync_type == 'all':
            return f"[{provider_name}] Full Sync"
        # Individual entity syncs
        elif sync_type in ('companies', 'contacts', 'agents'):
            return f"[{provider_name}] {sync_type.title()}"
        else:
            return f"[{provider_name}] Sync"

    elif script == 'rmm':
        # RMM sync (Datto, SuperOps RMM, etc.)
        rmm_provider_names = {
            'datto': 'Datto',
            'superops': 'SuperOps',
        }
        provider_name = rmm_provider_names.get(provider, provider.title() if provider else 'RMM')
        return f"[{provider_name}] Sync"

    elif script == 'datto':
        # Legacy datto sync
        return "[Datto] Sync"

    elif script == 'tickets':
        # Legacy ticket sync
        return "[PSA] Tickets"

    elif script == 'freshservice':
        # Legacy freshservice sync
        return "[Freshservice] Sync"

    elif script == 'create-account-numbers':
        return "Create Account Numbers"

    elif script == 'push-to-datto':
        return "[Datto] Push Account Numbers"

    elif script in ('keycloak-agents', 'keycloak_agents'):
        return "[Keycloak] Agents"

    else:
        # Fallback: capitalize the script name
        return script.replace('-', ' ').replace('_', ' ').title()

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/')
@admin_required
def settings():
    """Admin settings page."""
    # Load current configuration
    config = current_app.config['CODEX_CONFIG']

    # Get database stats
    stats = {
        'companies': Company.query.count(),
        'contacts': Contact.query.count(),
        'assets': Asset.query.count(),
        'tickets': TicketDetail.query.count(),
        'agents': Agent.query.count(),
        'active_contacts': Contact.query.filter_by(active=True).count(),
        'online_assets': Asset.query.filter_by(online=True).count(),
        'enabled_agents': Agent.query.filter_by(enabled=True).count(),
    }

    # Get configuration values
    fs_config = {
        'domain': config.get('freshservice', 'domain', fallback='Not configured'),
        'web_domain': config.get('freshservice', 'web_domain', fallback=''),
        'api_key_set': bool(config.get('freshservice', 'api_key', fallback='') and
                           config.get('freshservice', 'api_key') not in ['', 'YOUR_FRESHSERVICE_API_KEY'])
    }

    datto_config = {
        'api_endpoint': config.get('datto', 'api_endpoint', fallback='Not configured'),
        'public_key_set': bool(config.get('datto', 'public_key', fallback='') and
                              config.get('datto', 'public_key') not in ['', 'YOUR_DATTO_PUBLIC_KEY']),
        'secret_key_set': bool(config.get('datto', 'secret_key', fallback='') and
                              config.get('datto', 'secret_key') not in ['', 'YOUR_DATTO_SECRET_KEY'])
    }

    # Get Superops configuration
    superops_config = {
        'api_url': config.get('psa.superops', 'api_url', fallback=''),
        'api_key_set': bool(config.get('psa.superops', 'api_key', fallback='') and
                           config.get('psa.superops', 'api_key') not in ['', 'YOUR_SUPEROPS_API_KEY'])
    }

    # Get PSA configuration
    psa_config = {
        'default_provider': config.get('psa', 'default_provider', fallback='freshservice'),
        'enabled_providers': config.get('psa', 'enabled_providers', fallback='freshservice').split(','),
    }

    # Get RMM configuration
    rmm_config = {
        'default_provider': config.get('rmm', 'default_provider', fallback='datto'),
    }

    db_config = {
        'host': config.get('database_credentials', 'db_host', fallback='Unknown'),
        'port': config.get('database_credentials', 'db_port', fallback='Unknown'),
        'dbname': config.get('database_credentials', 'db_dbname', fallback='Unknown'),
        'user': config.get('database_credentials', 'db_user', fallback='Unknown'),
    }

    # Get scheduler configuration
    scheduler_config = {
        'psa_enabled': current_app.config.get('SYNC_PSA_ENABLED', True),
        'rmm_enabled': current_app.config.get('SYNC_RMM_ENABLED', True),
        'tickets_enabled': current_app.config.get('SYNC_TICKETS_ENABLED', False),
        'psa_schedule': current_app.config.get('SYNC_PSA_SCHEDULE', 'daily'),
        'rmm_schedule': current_app.config.get('SYNC_RMM_SCHEDULE', 'daily'),
        'tickets_schedule': current_app.config.get('SYNC_TICKETS_SCHEDULE', 'hourly'),
        'run_on_startup': current_app.config.get('SYNC_RUN_ON_STARTUP', False),
        'default_provider': current_app.config.get('PSA_DEFAULT_PROVIDER', 'freshservice'),
    }

    # Get scheduler status
    from app.scheduler import get_scheduler
    scheduler = get_scheduler()
    scheduler_jobs = []
    if scheduler:
        for job in scheduler.get_jobs():
            scheduler_jobs.append({
                'id': job.id,
                'name': job.name,
                'next_run': job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else 'N/A'
            })

    # Get recent sync jobs (last 10) with local time conversion
    raw_jobs = SyncJob.query.order_by(SyncJob.started_at.desc()).limit(10).all()
    recent_jobs = []
    for job in raw_jobs:
        # Calculate duration if completed
        duration = None
        if job.started_at and job.completed_at:
            try:
                start = datetime.fromisoformat(job.started_at.replace('Z', '+00:00') if job.started_at.endswith('Z') else job.started_at)
                end = datetime.fromisoformat(job.completed_at.replace('Z', '+00:00') if job.completed_at.endswith('Z') else job.completed_at)
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                if end.tzinfo is None:
                    end = end.replace(tzinfo=timezone.utc)
                duration_seconds = (end - start).total_seconds()
                if duration_seconds < 60:
                    duration = f"{int(duration_seconds)}s"
                elif duration_seconds < 3600:
                    duration = f"{int(duration_seconds // 60)}m {int(duration_seconds % 60)}s"
                else:
                    hours = int(duration_seconds // 3600)
                    mins = int((duration_seconds % 3600) // 60)
                    duration = f"{hours}h {mins}m"
            except (ValueError, AttributeError):
                duration = None

        recent_jobs.append({
            'id': job.id,
            'script': job.script,
            'display_name': get_sync_display_name(job.script, job.provider, job.sync_type),
            'provider': job.provider,
            'sync_type': job.sync_type,
            'status': job.status,
            'started_at': utc_to_local(job.started_at),
            'completed_at': utc_to_local(job.completed_at),
            'duration': duration,
            'output': job.output,
            'error': job.error,
            'success': job.success,
        })

    return render_template('admin/settings.html',
                         user=g.user,
                         stats=stats,
                         psa_config=psa_config,
                         rmm_config=rmm_config,
                         fs_config=fs_config,
                         superops_config=superops_config,
                         datto_config=datto_config,
                         db_config=db_config,
                         scheduler_config=scheduler_config,
                         scheduler_jobs=scheduler_jobs,
                         recent_jobs=recent_jobs)

@admin_bp.route('/update-freshservice', methods=['POST'])
@admin_required
def update_freshservice():
    """
    Update Freshservice configuration.

    LEGACY: Freshservice uses [freshservice] section.
    New PSA providers should use [psa.{provider}] format (e.g., [psa.superops]).
    This will be removed when migrating away from Freshservice.
    """
    config_path = os.path.join(current_app.instance_path, 'codex.conf')
    config = configparser.RawConfigParser()
    config.read(config_path)

    # Ensure section exists (legacy format)
    if not config.has_section('freshservice'):
        config.add_section('freshservice')

    domain = request.form.get('fs_domain')
    web_domain = request.form.get('fs_web_domain')
    api_key = request.form.get('fs_api_key')

    if domain:
        config.set('freshservice', 'domain', domain)
    if web_domain is not None:
        config.set('freshservice', 'web_domain', web_domain)
    if api_key:
        config.set('freshservice', 'api_key', api_key)
    
    with open(config_path, 'w') as f:
        config.write(f)

    # Reload config in app
    current_app.config['CODEX_CONFIG'] = config

    flash('Freshservice configuration saved successfully', 'success')
    return redirect(url_for('admin.settings'))

@admin_bp.route('/update-datto', methods=['POST'])
@admin_required
def update_datto():
    """Update Datto RMM configuration."""
    config_path = os.path.join(current_app.instance_path, 'codex.conf')
    config = configparser.RawConfigParser()
    config.read(config_path)

    # Ensure section exists
    if not config.has_section('datto'):
        config.add_section('datto')

    api_endpoint = request.form.get('datto_endpoint')
    public_key = request.form.get('datto_public_key')
    secret_key = request.form.get('datto_secret_key')

    if api_endpoint:
        config.set('datto', 'api_endpoint', api_endpoint)
    if public_key:
        config.set('datto', 'public_key', public_key)
    if secret_key:
        config.set('datto', 'secret_key', secret_key)

    with open(config_path, 'w') as f:
        config.write(f)

    # Reload config in app
    current_app.config['CODEX_CONFIG'] = config

    flash('Datto RMM configuration saved successfully', 'success')
    return redirect(url_for('admin.settings'))

@admin_bp.route('/update-superops', methods=['POST'])
@admin_required
def update_superops():
    """
    Update Superops configuration.

    STANDARD: All new PSA providers use [psa.{provider}] format.
    This is the correct pattern for modular PSA providers.
    """
    config_path = os.path.join(current_app.instance_path, 'codex.conf')
    config = configparser.RawConfigParser()
    config.read(config_path)

    # Ensure section exists (standard PSA format)
    if not config.has_section('psa.superops'):
        config.add_section('psa.superops')

    api_url = request.form.get('superops_api_url')
    api_key = request.form.get('superops_api_key')

    if api_url is not None:
        config.set('psa.superops', 'api_url', api_url)
    if api_key:
        config.set('psa.superops', 'api_key', api_key)

    with open(config_path, 'w') as f:
        config.write(f)

    # Reload config in app
    current_app.config['CODEX_CONFIG'] = config

    flash('Superops configuration saved', 'success')
    return redirect(url_for('admin.settings'))

@admin_bp.route('/update-psa-provider', methods=['POST'])
@admin_required
def update_psa_provider():
    """
    Update default PSA provider.

    PSA Framework: [psa] section controls which provider is active.
    Individual provider configs are in [psa.{provider}] or legacy [freshservice].
    """
    config_path = os.path.join(current_app.instance_path, 'codex.conf')
    config = configparser.RawConfigParser()
    config.read(config_path)

    # Ensure section exists (PSA framework settings)
    if not config.has_section('psa'):
        config.add_section('psa')

    provider = request.form.get('default_provider')

    if provider in ['freshservice', 'superops']:
        config.set('psa', 'default_provider', provider)

        with open(config_path, 'w') as f:
            config.write(f)

        # Reload config in app
        current_app.config['CODEX_CONFIG'] = config
        current_app.config['PSA_DEFAULT_PROVIDER'] = provider

        flash(f'Default PSA provider changed to {provider.title()}. Restart Codex for scheduler changes to take effect.', 'success')
    else:
        flash('Invalid provider selected', 'error')

    return redirect(url_for('admin.settings'))

@admin_bp.route('/update-rmm-provider', methods=['POST'])
@admin_required
def update_rmm_provider():
    """
    Update default RMM provider.

    RMM Framework: [rmm] section controls which provider is active.
    Individual provider configs are in [datto], [superops], etc.
    """
    config_path = os.path.join(current_app.instance_path, 'codex.conf')
    config = configparser.RawConfigParser()
    config.read(config_path)

    # Ensure section exists (RMM framework settings)
    if not config.has_section('rmm'):
        config.add_section('rmm')

    provider = request.form.get('default_provider')

    if provider in ['datto', 'superops']:
        config.set('rmm', 'default_provider', provider)

        with open(config_path, 'w') as f:
            config.write(f)

        # Reload config in app
        current_app.config['CODEX_CONFIG'] = config

        flash(f'Default RMM provider changed to {provider.title()}. Restart Codex for scheduler changes to take effect.', 'success')
    else:
        flash('Invalid RMM provider selected', 'error')

    return redirect(url_for('admin.settings'))

@admin_bp.route('/clear-data', methods=['POST'])
@admin_required
def clear_data():
    """Clear all CRM data (dangerous operation)."""
    data_type = request.form.get('data_type')

    try:
        if data_type == 'companies':
            deleted_count = Company.query.count()
            # Clear association tables first
            db.session.execute(contact_company_link.delete())
            # Delete related tables in order (foreign keys)
            TicketDetail.query.delete()
            RMMSiteLink.query.delete()
            Location.query.delete()
            CompanyFeatureOverride.query.delete()
            Asset.query.delete()
            # Now delete companies
            Company.query.delete()
            db.session.commit()
            flash(f'✓ Deleted {deleted_count} companies and all related data', 'success')

        elif data_type == 'contacts':
            deleted_count = Contact.query.count()
            # Clear association tables first
            db.session.execute(contact_company_link.delete())
            db.session.execute(asset_contact_link.delete())
            # Now safe to delete contacts
            Contact.query.delete()
            db.session.commit()
            flash(f'✓ Deleted {deleted_count} contacts', 'success')

        elif data_type == 'assets':
            deleted_count = Asset.query.count()
            # Clear association tables first
            db.session.execute(asset_contact_link.delete())
            # Now safe to delete assets
            Asset.query.delete()
            db.session.commit()
            flash(f'✓ Deleted {deleted_count} assets', 'success')

        elif data_type == 'agents':
            deleted_count = Agent.query.count()
            # Agents have no foreign key dependencies
            Agent.query.delete()
            db.session.commit()
            flash(f'✓ Deleted {deleted_count} agents', 'success')

        elif data_type == 'all':
            asset_count = Asset.query.count()
            contact_count = Contact.query.count()
            company_count = Company.query.count()
            agent_count = Agent.query.count()

            # Delete association tables first
            db.session.execute(asset_contact_link.delete())
            db.session.execute(contact_company_link.delete())

            # Delete in proper order (respecting all foreign keys)
            TicketDetail.query.delete()
            RMMSiteLink.query.delete()
            Location.query.delete()
            CompanyFeatureOverride.query.delete()
            Asset.query.delete()
            Contact.query.delete()
            Company.query.delete()
            Agent.query.delete()

            db.session.commit()
            flash(f'✓ Deleted ALL data: {company_count} companies, {contact_count} contacts, {asset_count} assets, {agent_count} agents', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'✗ Error deleting data: {str(e)}', 'error')

    return redirect(url_for('admin.settings'))
