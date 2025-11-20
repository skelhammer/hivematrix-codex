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
        script_name: Name of the script (e.g., 'pull_freshservice.py')
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


def run_freshservice_sync():
    """
    Run Freshservice sync with account number assignment first.

    This ensures all companies have account numbers before syncing.
    """
    try:
        base_dir = os.path.dirname(os.path.dirname(__file__))
        python_path = os.path.join(base_dir, 'pyenv', 'bin', 'python')

        if not os.path.exists(python_path):
            python_path = 'python3'

        logger.info("Running Freshservice sync workflow")

        # Step 1: Assign account numbers to companies missing them
        logger.info("Step 1: Assigning account numbers to Freshservice companies")
        set_account_script = os.path.join(base_dir, 'set_account_numbers.py')

        result = subprocess.run(
            [python_path, set_account_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=base_dir,
            timeout=300  # 5 minute timeout
        )

        if result.returncode == 0:
            logger.info("Account numbers assigned successfully")
        else:
            logger.warning(f"Account number assignment had issues: {result.stderr.decode()}")

        # Step 2: Pull Freshservice data
        logger.info("Step 2: Pulling Freshservice data")
        run_sync_script('pull_freshservice.py')

    except subprocess.TimeoutExpired:
        logger.error("set_account_numbers.py timed out after 5 minutes")
    except Exception as e:
        logger.error(f"Error in Freshservice sync workflow: {e}")


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
        freshservice_enabled = app.config.get('SYNC_FRESHSERVICE_ENABLED', True)
        datto_enabled = app.config.get('SYNC_DATTO_ENABLED', True)
        tickets_enabled = app.config.get('SYNC_TICKETS_ENABLED', True)

        freshservice_schedule = app.config.get('SYNC_FRESHSERVICE_SCHEDULE', 'daily')
        datto_schedule = app.config.get('SYNC_DATTO_SCHEDULE', 'daily')
        tickets_schedule = app.config.get('SYNC_TICKETS_SCHEDULE', 'frequent')

        # Schedule Freshservice sync (companies & contacts)
        if freshservice_enabled:
            if freshservice_schedule == 'daily':
                scheduler.add_job(
                    func=run_freshservice_sync,
                    trigger=CronTrigger(hour=2, minute=0),  # 2:00 AM daily
                    id='freshservice_sync',
                    name='Sync Freshservice (Companies & Contacts)',
                    replace_existing=True
                )
                logger.info("Scheduled Freshservice sync: Daily at 2:00 AM")
            elif freshservice_schedule == 'hourly':
                scheduler.add_job(
                    func=run_freshservice_sync,
                    trigger=IntervalTrigger(hours=1),
                    id='freshservice_sync',
                    name='Sync Freshservice (Companies & Contacts)',
                    replace_existing=True
                )
                logger.info("Scheduled Freshservice sync: Every hour")

        # Schedule Datto RMM sync (assets & backup)
        if datto_enabled:
            if datto_schedule == 'daily':
                scheduler.add_job(
                    func=lambda: run_sync_script('pull_datto.py'),
                    trigger=CronTrigger(hour=3, minute=0),  # 3:00 AM daily
                    id='datto_sync',
                    name='Sync Datto RMM (Assets & Backup)',
                    replace_existing=True
                )
                logger.info("Scheduled Datto sync: Daily at 3:00 AM")
            elif datto_schedule == 'hourly':
                scheduler.add_job(
                    func=lambda: run_sync_script('pull_datto.py'),
                    trigger=IntervalTrigger(hours=1),
                    id='datto_sync',
                    name='Sync Datto RMM (Assets & Backup)',
                    replace_existing=True
                )
                logger.info("Scheduled Datto sync: Every hour")

        # Schedule Tickets sync
        if tickets_enabled:
            if tickets_schedule == 'frequent':
                scheduler.add_job(
                    func=lambda: run_sync_script('sync_tickets_from_freshservice.py'),
                    trigger=IntervalTrigger(minutes=3),
                    id='tickets_sync',
                    name='Sync Tickets',
                    replace_existing=True
                )
                logger.info("Scheduled Tickets sync: Every 3 minutes")
            elif tickets_schedule == 'hourly':
                scheduler.add_job(
                    func=lambda: run_sync_script('sync_tickets_from_freshservice.py'),
                    trigger=IntervalTrigger(hours=1),
                    id='tickets_sync',
                    name='Sync Tickets',
                    replace_existing=True
                )
                logger.info("Scheduled Tickets sync: Every hour")
            elif tickets_schedule == 'daily':
                scheduler.add_job(
                    func=lambda: run_sync_script('sync_tickets_from_freshservice.py'),
                    trigger=CronTrigger(hour=4, minute=0),  # 4:00 AM daily
                    id='tickets_sync',
                    name='Sync Tickets',
                    replace_existing=True
                )
                logger.info("Scheduled Tickets sync: Daily at 4:00 AM")

        # Run initial sync on startup if enabled
        run_on_startup = app.config.get('SYNC_RUN_ON_STARTUP', False)
        if run_on_startup:
            logger.info("Running initial sync on startup...")
            if freshservice_enabled:
                scheduler.add_job(
                    func=run_freshservice_sync,
                    trigger='date',  # Run once immediately
                    id='freshservice_startup',
                    name='Startup Freshservice Sync',
                    replace_existing=True
                )
            if datto_enabled:
                scheduler.add_job(
                    func=lambda: run_sync_script('pull_datto.py'),
                    trigger='date',  # Run once immediately
                    id='datto_startup',
                    name='Startup Datto Sync',
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
