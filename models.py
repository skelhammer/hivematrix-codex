from extensions import db
from sqlalchemy import BigInteger

# Association table for contacts and companies
contact_company_link = db.Table('contact_company_link',
    db.Column('contact_id', db.Integer, db.ForeignKey('contacts.id'), primary_key=True),
    db.Column('company_account_number', db.String(50), db.ForeignKey('companies.account_number'), primary_key=True)
)

# Association table for assets and contacts
asset_contact_link = db.Table('asset_contact_link',
    db.Column('asset_id', db.Integer, db.ForeignKey('assets.id'), primary_key=True),
    db.Column('contact_id', db.Integer, db.ForeignKey('contacts.id'), primary_key=True)
)

class Company(db.Model):
    __tablename__ = 'companies'

    # Primary key
    account_number = db.Column(db.String(50), primary_key=True)

    # PSA system configuration
    psa_provider = db.Column(db.String(50), default='freshservice')  # 'freshservice', 'superops', etc.

    # External PSA system identifier (generic - works with any PSA)
    external_id = db.Column(BigInteger, unique=True, nullable=True)
    external_source = db.Column(db.String(50), default='freshservice')  # Which PSA this ID came from

    # Core fields
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.String(100))
    updated_at = db.Column(db.String(100))

    # Company head/prime user (from top-level)
    head_user_id = db.Column(BigInteger)
    head_name = db.Column(db.String(150))
    prime_user_id = db.Column(BigInteger)
    prime_user_name = db.Column(db.String(150))

    # Domains (JSON array stored as string)
    domains = db.Column(db.Text)  # JSON array like ["domain1.com", "domain2.com"]

    # Workspace
    workspace_id = db.Column(db.Integer)

    # Custom fields from Freshservice
    plan_selected = db.Column(db.String(100))
    managed_users = db.Column(db.String(100))
    managed_devices = db.Column(db.String(100))
    managed_network = db.Column(db.String(100))
    contract_term = db.Column(db.String(50))  # Contract term length
    contract_start_date = db.Column(db.String(100))
    contract_end_date = db.Column(db.String(100))  # Calculated end date
    profit_or_non_profit = db.Column(db.String(50))
    company_main_number = db.Column(db.String(50))
    address = db.Column(db.Text)  # Full address
    company_start_date = db.Column(db.String(100))

    # Additional fields for compatibility
    billing_plan = db.Column(db.String(100))  # Alias for plan_selected
    contract_term_length = db.Column(db.String(50))  # Alias for contract_term
    support_level = db.Column(db.String(100))  # Support tier
    phone_system = db.Column(db.String(100))
    email_system = db.Column(db.String(100))
    datto_portal_url = db.Column(db.String(255))

    assets = db.relationship('Asset', back_populates='company', lazy=True, cascade="all, delete-orphan")
    contacts = db.relationship('Contact', secondary=contact_company_link, back_populates='companies')
    feature_overrides = db.relationship('CompanyFeatureOverride', back_populates='company', lazy='dynamic', cascade="all, delete-orphan")
    locations = db.relationship('Location', back_populates='company', lazy=True, cascade="all, delete-orphan")
    rmm_site_links = db.relationship('RMMSiteLink', back_populates='company', lazy=True, cascade="all, delete-orphan")

class Asset(db.Model):
    __tablename__ = 'assets'
    id = db.Column(db.Integer, primary_key=True)
    hostname = db.Column(db.String(150), nullable=False)
    company_account_number = db.Column(db.String(50), db.ForeignKey('companies.account_number'), nullable=False)
    hardware_type = db.Column(db.String(100))
    operating_system = db.Column(db.String(100))
    last_logged_in_user = db.Column(db.String(150))
    rmm_site_name = db.Column(db.String(150))
    antivirus_product = db.Column(db.String(100))
    description = db.Column(db.Text)
    ext_ip_address = db.Column(db.String(50))
    int_ip_address = db.Column(db.String(50))
    domain = db.Column(db.String(100))
    last_audit_date = db.Column(db.String(50))
    last_reboot = db.Column(db.String(50))
    last_seen = db.Column(db.String(50))
    online = db.Column(db.Boolean)
    patch_status = db.Column(db.String(50))
    backup_usage_tb = db.Column(db.String(50))
    enabled_administrators = db.Column(db.Text)
    device_type = db.Column(db.String(50))
    portal_url = db.Column(db.String(255))
    web_remote_url = db.Column(db.String(255))

    # UDF fields from Datto (User Defined Fields 1-30)
    udf1 = db.Column(db.Text)
    udf2 = db.Column(db.Text)
    udf3 = db.Column(db.Text)
    udf4 = db.Column(db.Text)
    udf5 = db.Column(db.Text)
    udf6 = db.Column(db.Text)
    udf7 = db.Column(db.Text)
    udf8 = db.Column(db.Text)
    udf9 = db.Column(db.Text)
    udf10 = db.Column(db.Text)
    udf11 = db.Column(db.Text)
    udf12 = db.Column(db.Text)
    udf13 = db.Column(db.Text)
    udf14 = db.Column(db.Text)
    udf15 = db.Column(db.Text)
    udf16 = db.Column(db.Text)
    udf17 = db.Column(db.Text)
    udf18 = db.Column(db.Text)
    udf19 = db.Column(db.Text)
    udf20 = db.Column(db.Text)
    udf21 = db.Column(db.Text)
    udf22 = db.Column(db.Text)
    udf23 = db.Column(db.Text)
    udf24 = db.Column(db.Text)
    udf25 = db.Column(db.Text)
    udf26 = db.Column(db.Text)
    udf27 = db.Column(db.Text)
    udf28 = db.Column(db.Text)
    udf29 = db.Column(db.Text)
    udf30 = db.Column(db.Text)

    company = db.relationship('Company', back_populates='assets')
    contacts = db.relationship('Contact', secondary=asset_contact_link, back_populates='assets')

class Contact(db.Model):
    __tablename__ = 'contacts'

    # Primary key
    id = db.Column(db.Integer, primary_key=True)

    # External PSA system identifier (generic - works with any PSA)
    external_id = db.Column(BigInteger, unique=True, nullable=True)
    external_source = db.Column(db.String(50), default='freshservice')  # Which PSA this ID came from

    # Core fields
    first_name = db.Column(db.String(150))
    last_name = db.Column(db.String(150))
    name = db.Column(db.String(150), nullable=False)  # Computed: first_name + last_name
    primary_email = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)  # Alias for primary_email

    # Status fields
    active = db.Column(db.Boolean, default=True)
    is_agent = db.Column(db.Boolean, default=False)
    vip_user = db.Column(db.Boolean, default=False)
    has_logged_in = db.Column(db.Boolean, default=False)

    # Contact information
    mobile_phone_number = db.Column(db.String(50))
    work_phone_number = db.Column(db.String(50))
    address = db.Column(db.Text)
    secondary_emails = db.Column(db.Text)  # JSON array

    # Job/role information
    job_title = db.Column(db.String(150))
    title = db.Column(db.String(150))  # Alias for job_title
    employment_type = db.Column(db.String(100), default='Full Time')  # Not from FS, local field
    department_ids = db.Column(db.Text)  # JSON array of department IDs
    department_names = db.Column(db.Text)  # Comma-separated department names

    # Manager and location
    reporting_manager_id = db.Column(BigInteger)
    location_id = db.Column(BigInteger)
    location_name = db.Column(db.String(150))

    # Preferences
    language = db.Column(db.String(10), default='en')
    time_zone = db.Column(db.String(100))
    time_format = db.Column(db.String(10))  # '12h' or '24h'

    # Permissions
    can_see_all_tickets_from_associated_departments = db.Column(db.Boolean, default=False)
    can_see_all_changes_from_associated_departments = db.Column(db.Boolean, default=False)

    # Metadata
    created_at = db.Column(db.String(100))
    updated_at = db.Column(db.String(100))
    background_information = db.Column(db.Text)
    work_schedule_id = db.Column(BigInteger)

    # Custom fields
    user_number = db.Column(db.String(50))

    # Relationships
    companies = db.relationship('Company', secondary=contact_company_link, back_populates='contacts')
    assets = db.relationship('Asset', secondary=asset_contact_link, back_populates='contacts')

class CompanyFeatureOverride(db.Model):
    __tablename__ = 'company_feature_overrides'
    id = db.Column(db.Integer, primary_key=True)
    company_account_number = db.Column(db.String(50), db.ForeignKey('companies.account_number'), nullable=False)
    feature_key = db.Column(db.String(100), nullable=False)
    value = db.Column(db.String(100), nullable=False)
    override_enabled = db.Column(db.Boolean, nullable=False, default=True)

    company = db.relationship('Company', back_populates='feature_overrides')

class Location(db.Model):
    __tablename__ = 'locations'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    address = db.Column(db.String(255))
    phone_number = db.Column(db.String(50))
    company_account_number = db.Column(db.String(50), db.ForeignKey('companies.account_number'), nullable=False)

    company = db.relationship('Company', back_populates='locations')

class RMMSiteLink(db.Model):
    """
    Links companies to RMM provider sites (Datto, SuperOps, etc.).
    Vendor-agnostic design allows supporting multiple RMM providers.
    """
    __tablename__ = 'rmm_site_links'
    id = db.Column(db.Integer, primary_key=True)
    company_account_number = db.Column(db.String(50), db.ForeignKey('companies.account_number'), nullable=False)
    rmm_site_uid = db.Column(db.String(100), nullable=False)
    rmm_provider = db.Column(db.String(50), nullable=False, default='datto')  # 'datto', 'superops', etc.

    company = db.relationship('Company', back_populates='rmm_site_links')

    __table_args__ = (
        db.UniqueConstraint('rmm_site_uid', 'rmm_provider', name='unique_rmm_site'),
    )

class PSAAgent(db.Model):
    """
    PSA system agents (technicians/staff) pulled from PSA APIs (Freshservice, Superops, etc.).
    Used for mapping responder_id to agent names in tickets.
    """
    __tablename__ = 'psa_agents'

    id = db.Column(db.Integer, primary_key=True)

    # External PSA system identifier
    external_id = db.Column(BigInteger, nullable=False)
    external_source = db.Column(db.String(50), nullable=False)  # 'freshservice', 'superops', etc.

    # Core fields
    email = db.Column(db.String(150))
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    active = db.Column(db.Boolean, default=True)
    job_title = db.Column(db.String(150))
    department_ids = db.Column(db.Text)  # JSON array of department IDs
    group_ids = db.Column(db.Text)  # JSON array of group IDs
    created_at = db.Column(db.String(50))
    updated_at = db.Column(db.String(50))

    # Provider-specific data (for extensibility)
    provider_data = db.Column(db.JSON)

    @property
    def name(self):
        """Full name of the agent."""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name or self.last_name or f"Agent {self.id}"

    __table_args__ = (
        db.UniqueConstraint('external_id', 'external_source', name='unique_psa_agent'),
    )

class TicketDetail(db.Model):
    __tablename__ = 'ticket_details'

    # Use composite primary key for multi-PSA support
    id = db.Column(db.Integer, primary_key=True)

    # External PSA system identifier
    external_id = db.Column(BigInteger, nullable=False)  # Ticket ID in the PSA system
    external_source = db.Column(db.String(50), nullable=False, default='freshservice')  # 'freshservice', 'superops', etc.

    company_account_number = db.Column(db.String(50), db.ForeignKey('companies.account_number'), nullable=True)
    ticket_number = db.Column(db.String(50))
    subject = db.Column(db.Text)
    description = db.Column(db.Text)  # Initial ticket description
    description_text = db.Column(db.Text)  # Plain text version

    # Normalized status/priority (consistent across PSA systems)
    status = db.Column(db.String(50))  # 'open', 'pending', 'resolved', 'closed', 'waiting_customer', 'on_hold'
    priority = db.Column(db.String(50))  # 'low', 'medium', 'high', 'urgent'

    # Original PSA-specific values (for reference/debugging)
    status_id = db.Column(db.Integer)  # Original numeric status from PSA
    priority_id = db.Column(db.Integer)  # Original numeric priority from PSA
    ticket_type = db.Column(db.String(50))  # 'Incident' or 'Service Request'
    requester_email = db.Column(db.String(150))
    requester_name = db.Column(db.String(150))
    requester_id = db.Column(BigInteger)
    responder_id = db.Column(BigInteger)  # Assigned agent ID
    group_id = db.Column(BigInteger)  # Team/department ID
    created_at = db.Column(db.String(50))
    last_updated_at = db.Column(db.String(50))
    closed_at = db.Column(db.String(50))
    total_hours_spent = db.Column(db.Float, default=0.0)

    # SLA tracking fields
    fr_due_by = db.Column(db.String(50))  # First response due date
    due_by = db.Column(db.String(50))  # Resolution due date
    first_responded_at = db.Column(db.String(50))  # When first response was made
    agent_responded_at = db.Column(db.String(50))  # When agent last responded

    # Conversation history stored as JSON
    conversations = db.Column(db.Text)  # JSON array of conversation entries
    notes = db.Column(db.Text)  # JSON array of internal notes

    # Composite indexes for common query patterns
    __table_args__ = (
        db.UniqueConstraint('external_id', 'external_source', name='unique_ticket_external'),
        db.Index('idx_ticket_company', 'company_account_number'),
        db.Index('idx_ticket_status', 'status'),
        db.Index('idx_ticket_priority', 'priority'),
        db.Index('idx_ticket_updated', 'last_updated_at'),
        db.Index('idx_ticket_responder', 'responder_id'),
        db.Index('idx_ticket_group', 'group_id'),
        db.Index('idx_ticket_source', 'external_source'),
    )

class SyncJob(db.Model):
    __tablename__ = 'sync_jobs'
    id = db.Column(db.String(50), primary_key=True)  # UUID
    script = db.Column(db.String(50), nullable=False)  # 'psa', 'datto', 'tickets'
    provider = db.Column(db.String(50))  # 'freshservice', 'superops', etc. (for PSA syncs)
    sync_type = db.Column(db.String(50))  # 'companies', 'contacts', 'agents', 'tickets', 'all'
    status = db.Column(db.String(20), nullable=False)  # 'running', 'completed', 'failed'
    started_at = db.Column(db.String(50), nullable=False)  # ISO timestamp
    completed_at = db.Column(db.String(50))  # ISO timestamp
    output = db.Column(db.Text)  # Last 1000 chars of stdout
    error = db.Column(db.Text)  # Error message if failed
    success = db.Column(db.Boolean)

class BillingPlan(db.Model):
    __tablename__ = 'billing_plans'
    id = db.Column(db.Integer, primary_key=True)
    plan_name = db.Column(db.String(100), nullable=False)
    term_length = db.Column(db.String(50), nullable=False)  # 'Month to Month', '1-Year', '2-Year', '3-Year'
    support_level = db.Column(db.String(100), default='Billed Hourly', nullable=False)  # 'Billed Hourly', 'All Inclusive', etc.

    # Per-item costs
    per_user_cost = db.Column(db.Numeric(10, 2), default=0.00)
    per_workstation_cost = db.Column(db.Numeric(10, 2), default=0.00)
    per_server_cost = db.Column(db.Numeric(10, 2), default=0.00)
    per_vm_cost = db.Column(db.Numeric(10, 2), default=0.00)
    per_switch_cost = db.Column(db.Numeric(10, 2), default=0.00)
    per_firewall_cost = db.Column(db.Numeric(10, 2), default=0.00)
    per_hour_ticket_cost = db.Column(db.Numeric(10, 2), default=0.00)

    # Backup costs
    backup_base_fee_workstation = db.Column(db.Numeric(10, 2), default=0.00)
    backup_base_fee_server = db.Column(db.Numeric(10, 2), default=0.00)
    backup_included_tb = db.Column(db.Numeric(10, 2), default=1.00)  # TB included per device
    backup_per_tb_fee = db.Column(db.Numeric(10, 2), default=0.00)  # Cost per TB over included

    # Feature options (DEPRECATED - kept for backwards compatibility during migration)
    antivirus = db.Column(db.String(100), default='Not Included')
    soc = db.Column(db.String(100), default='Not Included')
    password_manager = db.Column(db.String(100), default='Not Included')
    sat = db.Column(db.String(100), default='Not Included')
    email_security = db.Column(db.String(100), default='Not Included')
    network_management = db.Column(db.String(100), default='Not Included')

    # Dynamic features relationship
    features = db.relationship('PlanFeature', back_populates='billing_plan', lazy='dynamic', cascade="all, delete-orphan")

    __table_args__ = (db.UniqueConstraint('plan_name', 'term_length', name='unique_plan_term'),)

class FeatureOption(db.Model):
    __tablename__ = 'feature_options'
    id = db.Column(db.Integer, primary_key=True)
    feature_category = db.Column(db.String(100), nullable=False)  # 'antivirus', 'soc', 'password_manager', etc.
    option_value = db.Column(db.String(100), nullable=False)  # 'SentinelOne', 'Arctic Wolf', etc.
    display_name = db.Column(db.String(150))  # Optional display name
    feature_type = db.Column(db.String(100))  # Legacy field, kept for compatibility
    description = db.Column(db.Text)  # Optional description

    __table_args__ = (db.UniqueConstraint('feature_category', 'option_value', name='unique_feature_option'),)


class FeatureCategoryConfig(db.Model):
    """
    Configuration for feature category display names.
    Stores proper capitalization/formatting for feature names (e.g., 'soc' → 'SOC').
    """
    __tablename__ = 'feature_category_config'
    id = db.Column(db.Integer, primary_key=True)
    feature_key = db.Column(db.String(100), unique=True, nullable=False)  # 'soc', 'sat', 'antivirus', etc.
    display_name = db.Column(db.String(150), nullable=False)  # 'SOC', 'SAT', 'Antivirus', etc.
    full_name = db.Column(db.String(255))  # Optional: 'Security Operations Center', 'Security Awareness Training'
    description = db.Column(db.Text)  # Optional description


class PlanFeature(db.Model):
    """
    Dynamic feature storage for billing plans.
    This allows adding ANY feature type without database schema changes.
    Each plan can have multiple features with their selected values.
    """
    __tablename__ = 'plan_features'
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('billing_plans.id', ondelete='CASCADE'), nullable=False)
    feature_type = db.Column(db.String(100), nullable=False)  # 'antivirus', 'soc', 'web_filtering', etc.
    feature_value = db.Column(db.String(150), nullable=False)  # 'SentinelOne', 'Not Included', etc.

    # Relationship
    billing_plan = db.relationship('BillingPlan', back_populates='features')

    __table_args__ = (db.UniqueConstraint('plan_id', 'feature_type', name='unique_plan_feature'),)


class Agent(db.Model):
    """
    Agents are system users from Keycloak with additional settings.
    These are internal users (technicians, admins, etc.) not Freshservice contacts.
    """
    __tablename__ = 'agents'

    # Primary key - Keycloak user ID
    keycloak_id = db.Column(db.String(100), primary_key=True)

    # User info from Keycloak
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    first_name = db.Column(db.String(150))
    last_name = db.Column(db.String(150))

    # Status
    enabled = db.Column(db.Boolean, default=True)

    # User settings - stored in Codex, not Keycloak
    theme_preference = db.Column(db.String(20), default='light')  # 'light' or 'dark'
    knowledgetree_view_preference = db.Column(db.String(20), default='grid')  # 'grid', 'tree', or 'hierarchy'
    home_page_preference = db.Column(db.String(50), default='beacon')  # Service slug for home page

    # Metadata
    created_at = db.Column(db.String(100))  # ISO timestamp
    updated_at = db.Column(db.String(100))  # ISO timestamp
    last_synced_at = db.Column(db.String(100))  # Last time synced from Keycloak

    def to_dict(self):
        """Convert agent to dictionary for API responses"""
        return {
            'keycloak_id': self.keycloak_id,
            'username': self.username,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'enabled': self.enabled,
            'theme_preference': self.theme_preference,
            'knowledgetree_view_preference': self.knowledgetree_view_preference,
            'home_page_preference': self.home_page_preference,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'last_synced_at': self.last_synced_at
        }
