from flask import Flask
import json
import os
import secrets

app = Flask(__name__, instance_relative_config=True)

# Enable template auto-reload for development
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Set secret key for sessions (generate a random one if not set)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

# Configure logging level from environment
import logging
log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
app.logger.setLevel(getattr(logging, log_level, logging.INFO))

# Enable structured JSON logging with correlation IDs
# Set ENABLE_JSON_LOGGING=false in environment to disable for development
enable_json = os.environ.get("ENABLE_JSON_LOGGING", "true").lower() in ("true", "1", "yes")
if enable_json:
    from app.structured_logger import setup_structured_logging
    setup_structured_logging(app, enable_json=True)

# --- Explicitly load all required configuration from environment variables ---
# Provide sensible defaults for init_db.py, will be overridden by Helm's .flaskenv
app.config['CORE_SERVICE_URL'] = os.environ.get('CORE_SERVICE_URL', 'http://localhost:5000')
app.config['SERVICE_NAME'] = os.environ.get('SERVICE_NAME', 'codex')

# Load database connection from config file
import configparser
try:
    os.makedirs(app.instance_path)
except OSError:
    pass

config_path = os.path.join(app.instance_path, 'codex.conf')
# Use RawConfigParser to avoid interpolation issues with special characters like %
config = configparser.RawConfigParser()
config.read(config_path)
app.config['CODEX_CONFIG'] = config

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = config.get('database', 'connection_string',
    fallback=f"sqlite:///{os.path.join(app.instance_path, 'codex.db')}")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Connection pool configuration for better performance
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'pool_recycle': 3600,  # Recycle connections after 1 hour
    'pool_pre_ping': True,  # Test connections before use
    'max_overflow': 5,
}

# PSA configuration
app.config['PSA_DEFAULT_PROVIDER'] = config.get('psa', 'default_provider', fallback='freshservice')
app.config['PSA_ENABLED_PROVIDERS'] = config.get('psa', 'enabled_providers', fallback='freshservice').split(',')

# Scheduler configuration
app.config['SYNC_PSA_ENABLED'] = config.getboolean('scheduler', 'sync_psa_enabled', fallback=True)
app.config['SYNC_DATTO_ENABLED'] = config.getboolean('scheduler', 'sync_datto_enabled', fallback=True)
app.config['SYNC_TICKETS_ENABLED'] = config.getboolean('scheduler', 'sync_tickets_enabled', fallback=True)
app.config['SYNC_PSA_SCHEDULE'] = config.get('scheduler', 'sync_psa_schedule', fallback='daily')
app.config['SYNC_DATTO_SCHEDULE'] = config.get('scheduler', 'sync_datto_schedule', fallback='daily')
app.config['SYNC_TICKETS_SCHEDULE'] = config.get('scheduler', 'sync_tickets_schedule', fallback='frequent')
app.config['SYNC_RUN_ON_STARTUP'] = config.getboolean('scheduler', 'sync_run_on_startup', fallback=False)

# Load services configuration for service-to-service calls
try:
    with open('services.json') as f:
        services_config = json.load(f)
        app.config['SERVICES'] = services_config
except FileNotFoundError:
    print("WARNING: services.json not found. Service-to-service calls will not work.")
    app.config['SERVICES'] = {}

from extensions import db
db.init_app(app)

# Initialize Flask-Limiter for rate limiting
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["10000 per hour", "500 per minute"],
    storage_uri="memory://"
)

# Apply ProxyFix to handle X-Forwarded headers from Nexus proxy
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,      # Trust X-Forwarded-For
    x_proto=1,    # Trust X-Forwarded-Proto (http/https)
    x_host=1,     # Trust X-Forwarded-Host
    x_prefix=1    # Trust X-Forwarded-Prefix (sets SCRIPT_NAME for url_for)
)

# Register blueprints
from routes.companies import companies_bp
from routes.contacts import contacts_bp
from routes.assets import assets_bp
from routes.admin import admin_bp
from routes.billing_plans import billing_plans_bp

app.register_blueprint(companies_bp)
app.register_blueprint(contacts_bp)
app.register_blueprint(assets_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(billing_plans_bp)

# Initialize Helm logger for centralized logging
app.config["SERVICE_NAME"] = os.environ.get("SERVICE_NAME", "codex")
app.config["HELM_SERVICE_URL"] = os.environ.get("HELM_SERVICE_URL", "http://localhost:5004")

from app.helm_logger import init_helm_logger
helm_logger = init_helm_logger(
    app.config["SERVICE_NAME"],
    app.config["HELM_SERVICE_URL"]
)

# Keycloak configuration for agent management
app.config['KEYCLOAK_SERVER_URL'] = os.environ.get('KEYCLOAK_SERVER_URL', 'http://localhost:8080')
app.config['KEYCLOAK_BACKEND_URL'] = os.environ.get('KEYCLOAK_BACKEND_URL', 'http://localhost:8080')
app.config['KEYCLOAK_REALM'] = os.environ.get('KEYCLOAK_REALM', 'hivematrix')
app.config['KEYCLOAK_ADMIN_USER'] = os.environ.get('KEYCLOAK_ADMIN_USER', 'admin')
app.config['KEYCLOAK_ADMIN_PASS'] = os.environ.get('KEYCLOAK_ADMIN_PASS', 'admin')

# SSL Verification Settings
# Default to False for self-signed certificates (common in HiveMatrix deployments)
# Can be overridden by setting VERIFY_SSL=True in .flaskenv if needed
verify_ssl_env = os.environ.get('VERIFY_SSL', 'False')
app.config['VERIFY_SSL'] = verify_ssl_env.lower() in ('true', '1', 'yes')

from app.version import VERSION, SERVICE_NAME as VERSION_SERVICE_NAME

# Context processor to inject version into all templates
@app.context_processor
def inject_version():
    return {
        'app_version': VERSION,
        'app_service_name': VERSION_SERVICE_NAME
    }

# Register RFC 7807 error handlers for consistent API error responses
from app.error_responses import (
    internal_server_error,
    not_found,
    bad_request,
    unauthorized,
    forbidden,
    service_unavailable
)

@app.errorhandler(400)
def handle_bad_request(e):
    """Handle 400 Bad Request errors"""
    return bad_request(detail=str(e))

@app.errorhandler(401)
def handle_unauthorized(e):
    """Handle 401 Unauthorized errors"""
    return unauthorized(detail=str(e))

@app.errorhandler(403)
def handle_forbidden(e):
    """Handle 403 Forbidden errors"""
    return forbidden(detail=str(e))

@app.errorhandler(404)
def handle_not_found(e):
    """Handle 404 Not Found errors"""
    return not_found(detail=str(e))

@app.errorhandler(500)
def handle_internal_error(e):
    """Handle 500 Internal Server Error"""
    app.logger.error(f"Internal server error: {e}")
    return internal_server_error()

@app.errorhandler(503)
def handle_service_unavailable(e):
    """Handle 503 Service Unavailable errors"""
    return service_unavailable(detail=str(e))

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    """Catch-all handler for unexpected exceptions"""
    app.logger.exception(f"Unexpected error: {e}")
    return internal_server_error(detail="An unexpected error occurred")

from app import routes
from app import agent_routes  # Agent management and Keycloak sync routes

# Initialize background scheduler for auto-sync (optional)
try:
    from app.scheduler import init_scheduler
    init_scheduler(app)
    helm_logger.info("Background sync scheduler initialized")
except ImportError as e:
    helm_logger.warning(f"Scheduler not available (APScheduler not installed): {e}")
except Exception as e:
    helm_logger.error(f"Failed to initialize scheduler: {e}")

# Log service startup
service_name = app.config['SERVICE_NAME']
helm_logger.info(f"{service_name} service started")
