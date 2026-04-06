#!/bin/bash
# ── Spanish Tutor Launcher ────────────────────────────────────────────
# Launches the Spanish voice tutor bot with token from Hermes .env.
# Usage: bash run.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${HERMES_ENV:-$HOME/.hermes/.env}"

# Source Hermes .env if available
if [ -f "$ENV_FILE" ]; then
    source "$ENV_FILE"
    echo "Loaded environment from $ENV_FILE"
fi

cd "$PROJECT_DIR"

# Activate venv
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "Creating virtual environment..."
    uv venv
    source .venv/bin/activate
    uv sync
fi

# Export the token so the bot picks it up
if [ -n "$SPANISH_BOT_TOKEN" ]; then
    export BOT_TOKEN="$SPANISH_BOT_TOKEN"
    echo "Using bot token from Hermes .env (SPANISH_BOT_TOKEN)"
elif [ -z "$(python3 -c "
import json
try:
    c = json.load(open('config.json'))
    print(c.get('bot_token',''))
except: pass
")" ]; then
    echo "Error: No SPANISH_BOT_TOKEN in .env and no token in config.json"
    exit 1
fi

echo "🚀 Starting Spanish Tutor Bot..."
echo "   Model: $(python3 -c "import json; c=json.load(open('config.json')); print(c.get('ollama_model','llama3.1:8b'))")"
echo "   Persona: persona/AGENTS.md"
echo ""

# Run the bot
exec python bot.py
