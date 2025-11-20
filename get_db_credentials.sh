#!/bin/bash
#
# Extract Codex Database Credentials
# Quick script to display database connection info for manual migrations
#

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CONFIG_FILE="$SCRIPT_DIR/instance/codex.conf"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${YELLOW}⚠ Config file not found at $CONFIG_FILE${NC}"
    echo "Run: python init_db.py"
    exit 1
fi

# Extract connection string
CONN_STR=$(grep "^connection_string" "$CONFIG_FILE" | cut -d'=' -f2 | xargs)

if [ -z "$CONN_STR" ]; then
    echo -e "${YELLOW}⚠ No connection string found in config${NC}"
    exit 1
fi

# Parse connection string: postgresql://user:password@host:port/dbname
# Extract components
DB_USER=$(echo "$CONN_STR" | sed -n 's|.*://\([^:]*\):.*|\1|p')
PASSWORD=$(echo "$CONN_STR" | sed -n 's|.*://[^:]*:\([^@]*\)@.*|\1|p')
DB_HOST=$(echo "$CONN_STR" | sed -n 's|.*@\([^:]*\):.*|\1|p')
DB_PORT=$(echo "$CONN_STR" | sed -n 's|.*:\([0-9]*\)/.*|\1|p')
DB_NAME=$(echo "$CONN_STR" | sed -n 's|.*/\([^?]*\).*|\1|p')

# URL decode the password
PASSWORD_DECODED=$(python3 -c "import urllib.parse; print(urllib.parse.unquote('$PASSWORD'))" 2>/dev/null || echo "$PASSWORD")

echo ""
echo "============================================"
echo -e "  ${GREEN}Codex Database Credentials${NC}"
echo "============================================"
echo -e "${BLUE}Host:${NC}     $DB_HOST"
echo -e "${BLUE}Port:${NC}     $DB_PORT"
echo -e "${BLUE}Database:${NC} $DB_NAME"
echo -e "${BLUE}User:${NC}     $DB_USER"
echo -e "${BLUE}Password:${NC} $PASSWORD_DECODED"
echo "============================================"
echo ""
echo -e "${GREEN}Manual Connection Commands:${NC}"
echo ""
echo "  # PostgreSQL shell:"
echo "  PGPASSWORD='$PASSWORD_DECODED' psql -h $DB_HOST -U $DB_USER -d $DB_NAME"
echo ""
echo "  # Or export password first:"
echo "  export PGPASSWORD='$PASSWORD_DECODED'"
echo "  psql -h $DB_HOST -U $DB_USER -d $DB_NAME"
echo ""
echo -e "${GREEN}Run Database Migration:${NC}"
echo ""
echo "  # Schema migration (safe, preserves data):"
echo "  python init_db.py --migrate-only"
echo ""
echo "  # Full connection string:"
echo "  $CONN_STR"
echo ""
