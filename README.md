# Local Voice Spanish Tutor

A real-time, voice-powered Spanish language tutor running entirely locally — no cloud APIs, no latency, no costs.

Built on top of [local-voice-ai-agent](https://github.com/jesuscopado/local-voice-ai-agent) by [jesuscopado](https://github.com/jesuscopado), adapted for Telegram-based language learning with persistent memory and structured personas.

## Features

- Voice and text conversations via Telegram
- Full local stack: Moonshine (STT) + Ollama LLM + Kokoro (TTS)
- Persistent student memory — tracks level, vocabulary, weak areas, session history
- Conversation history with the LLM for contextual tutoring
- Commands: /start, /progress, /level, /reset
- Fully offline once models are downloaded

## Prerequisites

- Mac with Apple Silicon (recommended, but works on Linux too)
- [Ollama](https://ollama.ai/) running locally
- `ffmpeg` installed (`brew install ffmpeg`)
- Python 3.13+
- [uv](https://github.com/astral-sh/uv) package manager

## Installation

### 1. Install dependencies

```bash
brew install ollama ffmpeg
brew install uv
```

### 2. Download Ollama model

```bash
ollama pull llama3.1:8b
```

Other models work too — `qwen3.5:9b`, `gemma4:e4b`, etc.

### 3. Clone & setup

```bash
git clone https://github.com/AndErem314/local-voice-spanish-tutor.git
cd local-voice-spanish-tutor
uv venv
source .venv/bin/activate
uv sync
```

### 4. Create Telegram Bot

1. Open [@BotFather](https://t.me/BotFather)
2. Send `/newbot`
3. Follow instructions, get your bot token
4. Paste it in `config.json`:
   ```json
   {
     "bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
   }
   ```

### 5. Customize the Tutor

Edit `persona/AGENTS.md` to change the tutor personality, teaching approach, and initial level.

## Usage

```bash
# Start the bot
python bot.py
```

That's it. Chat with your bot on Telegram. Send voice messages or text.

### Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message with current level |
| `/progress` | Show learning progress and stats |
| `/level` | Show current level |
| `/level B1` | Set a new level (A1, A2, B1, B2, C1, C2) |
| `/reset` | Clear conversation history |

## Architecture

```
Telegram Voice → Moonshine (STT) → Ollama (LLM + persona) → Kokoro (TTS) → Telegram Voice
     Text ──────┘                                              └→ Telegram Text
```

```
bot.py              ← Telegram bot main entry
├── config.json     ← Configuration (token, model, voice settings)
├── persona/
│   └── AGENTS.md   ← System prompt / tutor persona
├── core/
│   ├── config.py   ← Config loader with env override
│   ├── engine.py   ← Voice pipeline: STT → LLM → TTS
│   └── memory.py   ← Student progress tracker
├── data/
│   └── students.json ← Auto-created, stores student data
└── pyproject.toml  ← Dependencies
```

## Troubleshooting & Development Log

### Known Issue: Bot sends messages but does not receive/reply to updates

All components work independently (Moonshine STT, Ollama LLM, Kokoro TTS, Telegram API send), but the bot **fails to consume incoming messages** via the Telegram polling API. The process stays alive with models loaded (~1.5 GB RAM) but never triggers any handler. No errors are logged — the polling loop silently stalls.

#### What we tried (all failed to fix the polling issue):

| Attempt | Description | Result |
|---------|-------------|--------|
| 1 | **Python 3.14 → 3.13 downgrade** | Rebuilt `.venv` with Python 3.13. Suspected asyncio/httpx incompatibility in PTB v22. Same behavior — bot starts, no errors, no message consumption. |
| 2 | **`Application.run_polling()` fix** | Removed the double-start bug (`app.start()` + `await app.updater.start_polling()`). Made `main()` sync instead of async (since `run_polling()` is not a coroutine). The 409 Conflict went away but messages still not consumed. |
| 3 | **`asyncio.run()` nested loop fix** | Replaced manual event loop creation with `asyncio.run(main())`. PTB's `__run` internally calls `loop.run_until_complete()` which conflicts with an already-running loop. |
| 4 | **Raw Bot + `asyncio.run()` per request** | Bypassed `Application` entirely. Wrote `raw_bot.py` that calls `bot.get_updates()` via `asyncio.run()`. Error: "Event loop is closed" — httpx destroys its loop after each `asyncio.run()` returns. |
| 5 | **`requests`-based sync polling** | Replaced all asyncio with `requests` library (`sync_bot.py`). The bot starts cleanly but `requests.post()` to `getUpdates` hangs indefinitely — same silent stall. |
| 6 | **`curl` subprocess polling** | Zero Python HTTP — used `subprocess.run(["curl", ...])` for all API calls. The `curl` command works standalone from the terminal but **hangs inside `subprocess.run()`** when called from the bot process. Verified that `curl` connects and completes fine outside Python. |

#### Diagnosis summary:

The root cause appears to be a **silent network hang at the Python process level** on macOS when making long-poll HTTP requests. This affects `httpx` (PTB v22), `requests`, and even `subprocess.run` with `curl`. The same `curl` commands work fine from the terminal outside of Python. This suggests an issue specific to how the Python child process handles network I/O under macOS's network stack, possibly related to asyncio signal handling, file descriptor inheritance, or the macOS application sandbox.

#### Workarounds to investigate:
- **Option 3: Webhook** — instead of long-polling, run a local HTTPS server (uvicorn/FastAPI) that Telegram pushes updates to. This avoids long-poll entirely because the server receives inbound connections instead of initiating them.
- **Docker container** — run the bot inside a Docker Linux container where the Python networking stack behaves differently.
- **Different machine** — test the same codebase on a Linux machine to rule out a macOS-specific issue.

## Acknowledgements

This project is based on [jesuscopado/local-voice-ai-agent](https://github.com/jesuscopado/local-voice-ai-agent), which created the local voice AI pipeline using FastRTC, Moonshine, and Kokoro. We adapted it for Telegram-based language tutoring with persistent student memory and customizable AGENTS.md personas.

## License

MIT
