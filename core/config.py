"""
Configuration loader for local voice tutor bot.
Reads from config.json in project root, then env vars.
"""
import json
import os
from pathlib import Path


DEFAULT_CONFIG = {
    "bot_token": "",           # Telegram bot token from @BotFather
    "ollama_model": "llama3.1:8b",
    "tts_voice": "en",         # Kokoro voice: en, es (Spanish), pt (Portuguese)
    "tts_speed": 1.0,          # Kokoro speak speed
    "max_response_tokens": 500,
    "always_send_voice": True, # Always reply with voice message too
    "always_send_text": True,  # Always reply with text too
    "language_code": "es",     # ISO code: es, pt, etc.
}


def load_config() -> dict:
    """Load config from config.json, merge with defaults, override with env."""
    config = DEFAULT_CONFIG.copy()
    config_path = Path(__file__).parent.parent / "config.json"

    if config_path.exists():
        with open(config_path) as f:
            overrides = json.load(f)
            config.update(overrides)

    # Env vars override everything
    if os.environ.get("BOT_TOKEN"):
        config["bot_token"] = os.environ["BOT_TOKEN"]

    if os.environ.get("OLLAMA_MODEL"):
        config["ollama_model"] = os.environ["OLLAMA_MODEL"]

    return config
