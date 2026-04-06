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

## Acknowledgements

This project is based on [jesuscopado/local-voice-ai-agent](https://github.com/jesuscopado/local-voice-ai-agent), which created the local voice AI pipeline using FastRTC, Moonshine, and Kokoro. We adapted it for Telegram-based language tutoring with persistent student memory and customizable AGENTS.md personas.

## License

MIT
