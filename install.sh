#!/bin/bash
#
# HiveMatrix Codex - Minimal Installation Script
# This script only sets up Python dependencies.
# Manual configuration is required - see README.md
#

set -e  # Exit on error

APP_NAME="codex"
APP_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PARENT_DIR="$(dirname "$APP_DIR")"
HELM_DIR="$PARENT_DIR/hivematrix-helm"

echo "=========================================="
echo "  Installing HiveMatrix Codex"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Check Python version
echo -e "${YELLOW}Checking Python...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 not found${NC}"
    echo "Please install Python 3.8 or higher"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | awk '{print $2}')
echo -e "${GREEN}✓ Found Python $PYTHON_VERSION${NC}"
echo ""

# Create virtual environment
echo -e "${YELLOW}Creating virtual environment...${NC}"
if [ -d "pyenv" ]; then
    echo "  Virtual environment already exists"
else
    python3 -m venv pyenv
    echo -e "${GREEN}✓ Virtual environment created${NC}"
fi
echo ""

# Activate virtual environment
source pyenv/bin/activate

# Upgrade pip
echo -e "${YELLOW}Upgrading pip...${NC}"
pip install --upgrade pip > /dev/null 2>&1
echo -e "${GREEN}✓ pip upgraded${NC}"
echo ""

# Install dependencies
if [ -f "requirements.txt" ]; then
    echo -e "${YELLOW}Installing Python dependencies...${NC}"
    pip install -r requirements.txt
    echo -e "${GREEN}✓ Dependencies installed${NC}"
    echo ""
fi

# Create instance directory if needed
if [ ! -d "instance" ]; then
    echo -e "${YELLOW}Creating instance directory...${NC}"
    mkdir -p instance
    echo -e "${GREEN}✓ Instance directory created${NC}"
    echo ""
fi

# Create default database config if it doesn't exist
if [ ! -f "instance/codex.conf" ]; then
    echo -e "${YELLOW}Creating default database config...${NC}"
    cat > instance/codex.conf <<EOF
[database]
connection_string = postgresql://codex_user:CHANGE_ME@localhost:5432/codex_db
db_host = localhost
db_port = 5432
db_name = codex_db
db_user = codex_user

[psa]
default_provider = freshservice
EOF
    echo -e "${GREEN}✓ Database config created${NC}"
    echo -e "${YELLOW}  (Update instance/codex.conf with your database credentials)${NC}"
    echo ""
fi

# Create minimal .flaskenv so init_db.py can run
# Helm will regenerate this with full config later
if [ ! -f ".flaskenv" ]; then
    echo -e "${YELLOW}Creating minimal .flaskenv...${NC}"
    cat > .flaskenv <<EOF
FLASK_APP=run.py
FLASK_ENV=development
SERVICE_NAME=codex
CORE_SERVICE_URL=http://localhost:5000
HELM_SERVICE_URL=http://localhost:5004
EOF
    echo -e "${GREEN}✓ Minimal .flaskenv created${NC}"
    echo -e "${YELLOW}  (Helm will regenerate with full config after setup)${NC}"
    echo ""
fi

# Symlink services.json from Helm (if Helm is installed)
if [ -d "$HELM_DIR" ] && [ -f "$HELM_DIR/services.json" ]; then
    ln -sf ../hivematrix-helm/services.json services.json
fi

echo "=========================================="
echo -e "${GREEN}  Codex installed successfully!${NC}"
echo "=========================================="
echo ""
echo "Database Configuration:"
echo "  Database setup will be handled by Helm on next start"
echo ""
echo "Next steps:"
echo "  1. Start via Helm: ./start.sh (from hivematrix-helm)"
echo "  2. Or configure manually: python init_db.py"
echo ""
echo "After first start:"
echo "  • Access Codex via Nexus dashboard"
echo "  • Configure PSA/Datto integrations (optional)"
echo "    - Edit instance/codex.conf for API keys"
echo "    - Run sync scripts: sync_psa.py, pull_datto.py"
echo ""
