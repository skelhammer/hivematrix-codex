"""
Background Scheduler for Codex Data Syncs

Automatically runs data sync scripts on a schedule.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import subprocess
import os
import logging
import uuid
from datetime import datetime, timezone
from flask import current_app

logger = logging.getLogger(__name__)

# Store app reference for database access
_app = None

# Global scheduler instance
scheduler = None


def run_sync_script(script_name):
    """
    Run a sync script as a background subprocess with SyncJob tracking.

    Args:
        script_name: Name of the script (e.g., 'sync_psa.py')
    """
    global _app

    try:
        base_dir = os.path.dirname(os.path.dirname(__file__))
        script_path = os.path.join(base_dir, script_name)
        python_path = os.path.join(base_dir, 'pyenv', 'bin', 'python')

        if not os.path.exists(python_path):
            python_path = 'python3'

        logger.info(f"Running scheduled sync: {script_name}")

        # Determine script type for SyncJob record
        if 'ticket' in script_name:
            script_type = 'tickets'
        elif 'freshservice' in script_name:
            script_type = 'freshservice'
        elif 'datto' in script_name:
            script_type = 'datto'
        else:
            script_type = script_name.replace('.py', '')

        job_id = None

        # Create SyncJob record if app is available
        if _app is not None:
            from models import SyncJob
            from extensions import db

            with _app.app_context():
                job_id = str(uuid.uuid4())
                job = SyncJob(
                    id=job_id,
                    script=script_type,
                    status='running',
                    started_at=datetime.now(timezone.utc).isoformat()
                )
                db.session.add(job)
                db.session.commit()
                logger.info(f"Created SyncJob {job_id} for {script_type}")

        # Run script synchronously to capture result
        result = subprocess.run(
            [python_path, script_path],
            capture_output=True,
            text=True,
            timeout=7200,  # 2 hour timeout
            cwd=base_dir
        )

        # Update SyncJob with result
        if _app is not None and job_id:
            from models import SyncJob
            from extensions import db

            with _app.app_context():
                job = db.session.get(SyncJob, job_id)
                if job:
                    job.status = 'completed' if result.returncode == 0 else 'failed'
                    job.success = result.returncode == 0
                    job.output = result.stdout[-1000:] if result.stdout else None
                    job.error = result.stderr[-1000:] if result.stderr else None
                    job.completed_at = datetime.now(timezone.utc).isoformat()
                    db.session.commit()
                    logger.info(f"Updated SyncJob {job_id}: {job.status}")

        if result.returncode == 0:
            logger.info(f"Completed scheduled sync: {script_name}")
        else:
            logger.error(f"Scheduled sync failed: {script_name} - {result.stderr[:200] if result.stderr else 'No error output'}")

    except subprocess.TimeoutExpired:
        logger.error(f"Scheduled sync timed out: {script_name}")
        if _app is not None and job_id:
            from models import SyncJob
            from extensions import db

            with _app.app_context():
                job = db.session.get(SyncJob, job_id)
                if job:
                    job.status = 'failed'
                    job.success = False
                    job.error = 'Script timed out after 2 hours'
                    job.completed_at = datetime.now(timezone.utc).isoformat()
                    db.session.commit()

    except Exception as e:
        logger.error(f"Error running scheduled sync {script_name}: {e}")
        if _app is not None and job_id:
            from models import SyncJob
            from extensions import db

            with _app.app_context():
                job = db.session.get(SyncJob, job_id)
                if job:
                    job.status = 'failed'
                    job.success = False
                    job.error = str(e)
                    job.completed_at = datetime.now(timezone.utc).isoformat()
                    db.session.commit()


def run_psa_sync(provider: str, sync_type: str = 'all', full_history: bool = False):
    """
    Run PSA sync using the unified sync_psa.py script.

    Args:
        provider: PSA provider name ('freshservice', 'superops')
        sync_type: Type of sync ('companies', 'contacts', 'agents', 'tickets', 'all')
        full_history: For tickets, fetch all history
    """
    global _app

    try:
        base_dir = os.path.dirname(os.path.dirname(__file__))
        script_path = os.path.join(base_dir, 'sync_psa.py')
        python_path = os.path.join(base_dir, 'pyenv', 'bin', 'python')

        if not os.path.exists(python_path):
            python_path = 'python3'

        logger.info(f"Running PSA sync: provider={provider}, type={sync_type}")

        # Build command
        cmd = [python_path, script_path, '--provider', provider, '--type', sync_type]
        if full_history:
            cmd.append('--full-history')

        job_id = None

        # Create SyncJob record
        if _app is not None:
            from models import SyncJob
            from extensions import db

            with _app.app_context():
                job_id = str(uuid.uuid4())
                job = SyncJob(
                    id=job_id,
                    script='psa',
                    provider=provider,
                    sync_type=sync_type,
                    status='running',
                    started_at=datetime.now(timezone.utc).isoformat()
                )
                db.session.add(job)
                db.session.commit()
                logger.info(f"Created SyncJob {job_id} for {provider} {sync_type}")

        # Run sync
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=7200,  # 2 hour timeout
            cwd=base_dir
        )

        # Update SyncJob with result
        if _app is not None and job_id:
            from models import SyncJob
            from extensions import db

            with _app.app_context():
                job = db.session.get(SyncJob, job_id)
                if job:
                    job.status = 'completed' if result.returncode == 0 else 'failed'
                    job.success = result.returncode == 0
                    job.output = result.stdout[-1000:] if result.stdout else None
                    job.error = result.stderr[-1000:] if result.stderr else None
                    job.completed_at = datetime.now(timezone.utc).isoformat()
                    db.session.commit()
                    logger.info(f"Updated SyncJob {job_id}: {job.status}")

        if result.returncode == 0:
            logger.info(f"Completed PSA sync: {provider} {sync_type}")
        else:
            logger.error(f"PSA sync failed: {provider} {sync_type} - {result.stderr[:200] if result.stderr else 'No error output'}")

    except subprocess.TimeoutExpired:
        logger.error(f"PSA sync timed out: {provider} {sync_type}")
        if _app is not None and job_id:
            from models import SyncJob
            from extensions import db

            with _app.app_context():
                job = db.session.get(SyncJob, job_id)
                if job:
                    job.status = 'failed'
                    job.success = False
                    job.error = 'Script timed out after 2 hours'
                    job.completed_at = datetime.now(timezone.utc).isoformat()
                    db.session.commit()

    except Exception as e:
        logger.error(f"Error running PSA sync {provider} {sync_type}: {e}")


def run_freshservice_sync():
    """
    Run Freshservice sync (legacy wrapper).

    Uses the new unified PSA sync system.
    Syncs companies, contacts, and agents only (not tickets - they have their own schedule).
    """
    run_psa_sync('freshservice', 'base')


def init_scheduler(app):
    """
    Initialize and start the background scheduler.

    Args:
        app: Flask application instance
    """
    global scheduler, _app

    if scheduler is not None:
        logger.warning("Scheduler already initialized")
        return scheduler

    # Store app reference for database access in sync jobs
    _app = app

    scheduler = BackgroundScheduler(daemon=True)

    with app.app_context():
        # Get schedule settings from config
        psa_enabled = app.config.get('SYNC_PSA_ENABLED', True)
        rmm_enabled = app.config.get('SYNC_RMM_ENABLED', True)
        tickets_enabled = app.config.get('SYNC_TICKETS_ENABLED', True)

        psa_schedule = app.config.get('SYNC_PSA_SCHEDULE', 'daily')
        rmm_schedule = app.config.get('SYNC_RMM_SCHEDULE', 'daily')
        tickets_schedule = app.config.get('SYNC_TICKETS_SCHEDULE', 'frequent')

        # Get default PSA provider name for logging
        psa_provider = app.config.get('PSA_DEFAULT_PROVIDER', 'freshservice').title()

        # Schedule PSA sync (companies & contacts)
        if psa_enabled:
            if psa_schedule == 'daily':
                scheduler.add_job(
                    func=run_freshservice_sync,
                    trigger=CronTrigger(hour=2, minute=0),  # 2:00 AM daily
                    id='psa_sync',
                    name=f'Sync {psa_provider} (Companies & Contacts)',
                    replace_existing=True
                )
                logger.info(f"Scheduled {psa_provider} sync: Daily at 2:00 AM")
            elif psa_schedule == 'hourly':
                scheduler.add_job(
                    func=run_freshservice_sync,
                    trigger=IntervalTrigger(hours=1),
                    id='psa_sync',
                    name=f'Sync {psa_provider} (Companies & Contacts)',
                    replace_existing=True
                )
                logger.info(f"Scheduled {psa_provider} sync: Every hour")

        # Schedule RMM sync (assets & backup)
        if rmm_enabled:
            if rmm_schedule == 'daily':
                scheduler.add_job(
                    func=lambda: run_sync_script('sync_rmm.py'),
                    trigger=CronTrigger(hour=3, minute=0),  # 3:00 AM daily
                    id='rmm_sync',
                    name='Sync RMM (Assets & Backup)',
                    replace_existing=True
                )
                logger.info("Scheduled RMM sync: Daily at 3:00 AM")
            elif rmm_schedule == 'hourly':
                scheduler.add_job(
                    func=lambda: run_sync_script('sync_rmm.py'),
                    trigger=IntervalTrigger(hours=1),
                    id='rmm_sync',
                    name='Sync RMM (Assets & Backup)',
                    replace_existing=True
                )
                logger.info("Scheduled RMM sync: Every hour")

        # Schedule Tickets sync (uses PSA provider system)
        if tickets_enabled:
            # Get default PSA provider for tickets
            default_provider = app.config.get('PSA_DEFAULT_PROVIDER', 'freshservice')

            if tickets_schedule == 'frequent':
                scheduler.add_job(
                    func=lambda: run_psa_sync(default_provider, 'tickets'),
                    trigger=IntervalTrigger(minutes=3),
                    id='tickets_sync',
                    name='Sync Tickets',
                    replace_existing=True
                )
                logger.info(f"Scheduled Tickets sync ({default_provider}): Every 3 minutes")
            elif tickets_schedule == 'hourly':
                scheduler.add_job(
                    func=lambda: run_psa_sync(default_provider, 'tickets'),
                    trigger=IntervalTrigger(hours=1),
                    id='tickets_sync',
                    name='Sync Tickets',
                    replace_existing=True
                )
                logger.info(f"Scheduled Tickets sync ({default_provider}): Every hour")
            elif tickets_schedule == 'daily':
                scheduler.add_job(
                    func=lambda: run_psa_sync(default_provider, 'tickets'),
                    trigger=CronTrigger(hour=4, minute=0),  # 4:00 AM daily
                    id='tickets_sync',
                    name='Sync Tickets',
                    replace_existing=True
                )
                logger.info(f"Scheduled Tickets sync ({default_provider}): Daily at 4:00 AM")

        # Run initial sync on startup if enabled
        run_on_startup = app.config.get('SYNC_RUN_ON_STARTUP', False)
        if run_on_startup:
            logger.info("Running initial sync on startup...")
            if psa_enabled:
                scheduler.add_job(
                    func=run_freshservice_sync,
                    trigger='date',  # Run once immediately
                    id='psa_startup',
                    name=f'Startup {psa_provider} Sync',
                    replace_existing=True
                )
            if datto_enabled:
                scheduler.add_job(
                    func=lambda: run_sync_script('sync_rmm.py'),
                    trigger='date',  # Run once immediately
                    id='datto_startup',
                    name='Startup RMM Sync',
                    replace_existing=True
                )

        # Start the scheduler
        scheduler.start()
        logger.info("Background scheduler started successfully")

    return scheduler


def get_scheduler():
    """Get the global scheduler instance."""
    return scheduler


def shutdown_scheduler():
    """Shutdown the scheduler gracefully."""
    global scheduler
    if scheduler is not None:
        scheduler.shutdown()
        scheduler = None
        logger.info("Scheduler shut down")
