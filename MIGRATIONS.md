# Codex Database Migration Guide

This guide covers manual database migrations for Codex.

## Quick Reference

### Get Database Credentials
```bash
./get_db_credentials.sh
```

### Run Migration (Recommended)
```bash
# Safe migration - preserves all data, adds new columns/tables
python init_db.py --migrate-only
```

## Migration Methods

### 1. Automatic Migration (Recommended)
The `init_db.py` script includes intelligent schema migration:

```bash
cd ~/projects/hivematrix/hivematrix-codex
source pyenv/bin/activate
python init_db.py --migrate-only
```

**What it does:**
- ✅ Adds new tables if missing
- ✅ Adds new columns to existing tables
- ✅ Preserves all existing data
- ✅ Safe for production use
- ✅ Can be run multiple times (idempotent)
- ❌ Does NOT drop columns or tables

### 2. Manual SQL Migration
For custom migrations or rollbacks:

```bash
# Get credentials first
./get_db_credentials.sh

# Connect to database
export PGPASSWORD='your_password_from_above'
psql -h localhost -U codex_user -d codex_db

# Run your SQL
codex_db=> ALTER TABLE companies ADD COLUMN new_field VARCHAR(100);
codex_db=> \q
```

### 3. Force Rebuild (DANGEROUS - Development Only)
**⚠️ WARNING: This deletes all data!**

```bash
python init_db.py --force-rebuild
```

Only use this in development when you want to start fresh.

## Common Migration Scenarios

### Adding a New Column
```sql
-- Example: Add a custom field to companies table
ALTER TABLE companies ADD COLUMN custom_field TEXT;
```

### Adding a New Table
```python
# 1. Add model to models.py:
class NewTable(db.Model):
    __tablename__ = 'new_table'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    # ... other fields

# 2. Run migration:
python init_db.py --migrate-only
```

### Updating Existing Data
```sql
-- Connect to database
export PGPASSWORD='your_password'
psql -h localhost -U codex_user -d codex_db

-- Run update
UPDATE companies SET status = 'active' WHERE status IS NULL;
```

### Checking Schema
```sql
-- List all tables
\dt

-- Describe a table
\d companies

-- Show all columns in a table
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'companies';
```

## Backup Before Migration

**Always backup before manual migrations!**

```bash
# Backup database
pg_dump -h localhost -U codex_user codex_db > codex_backup_$(date +%Y%m%d_%H%M%S).sql

# Restore if needed
psql -h localhost -U codex_user codex_db < codex_backup_YYYYMMDD_HHMMSS.sql
```

## Troubleshooting

### "Permission denied" errors
```bash
# Grant all permissions to codex_user
export PGPASSWORD='your_password'
psql -h localhost -U postgres -d codex_db <<EOF
GRANT ALL ON SCHEMA public TO codex_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO codex_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO codex_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO codex_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO codex_user;
EOF
```

### "Database does not exist"
```bash
# Recreate database
sudo -u postgres psql <<EOF
CREATE DATABASE codex_db;
CREATE USER codex_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE codex_db TO codex_user;
EOF

# Then run init_db.py
python init_db.py --migrate-only
```

### "Connection refused"
```bash
# Check if PostgreSQL is running
sudo systemctl status postgresql

# Start PostgreSQL
sudo systemctl start postgresql
```

## Migration Checklist

- [ ] Backup database before migration
- [ ] Review models.py for schema changes
- [ ] Run `python init_db.py --migrate-only`
- [ ] Check migration output for errors
- [ ] Test application with new schema
- [ ] Verify data integrity

## Emergency Rollback

If a migration fails:

1. **Stop the application:**
   ```bash
   cd ~/projects/hivematrix/hivematrix-helm
   python cli.py stop codex
   ```

2. **Restore from backup:**
   ```bash
   psql -h localhost -U codex_user codex_db < codex_backup_YYYYMMDD_HHMMSS.sql
   ```

3. **Restart application:**
   ```bash
   python cli.py start codex
   ```

## Advanced: Custom Migration Scripts

For complex migrations, create a migration script:

```python
#!/usr/bin/env python3
"""
Custom migration: Add parent_company relationship
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from extensions import db
from sqlalchemy import text

def migrate():
    """Run custom migration"""
    with app.app_context():
        # Add column if it doesn't exist
        db.session.execute(text("""
            ALTER TABLE companies
            ADD COLUMN IF NOT EXISTS parent_company_id INTEGER
            REFERENCES companies(id);
        """))

        # Create index
        db.session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_parent_company
            ON companies(parent_company_id);
        """))

        db.session.commit()
        print("✓ Migration complete")

if __name__ == '__main__':
    migrate()
```

Run it:
```bash
source pyenv/bin/activate
python custom_migration.py
```

## Notes

- The `init_db.py --migrate-only` is the safest option for most cases
- Always test migrations in development first
- Keep backups for at least 30 days
- Document custom migrations in this file
- Migration history is not tracked (unlike Alembic/Flask-Migrate)
- For production, consider adding Flask-Migrate for tracked migrations
