from dotenv import load_dotenv
import os

# Load .flaskenv before importing app
load_dotenv('.flaskenv')

from app import app

if __name__ == "__main__":
    # Security: Bind to localhost only - Codex should not be exposed externally
    # Access via Nexus proxy at https://localhost:443/codex
    app.run(host='127.0.0.1', port=5010)
