#!/usr/bin/env python3
"""Spanish Tutor Bot — raw Bot polling (no Application.run_polling).
Bypasses the Application framework's async polling bug.
"""
import asyncio
import os
import signal
import sys
import tempfile
import time
import wave
from pathlib import Path
import struct

import numpy as np

sys.path.insert(0, "/Users/andrey/GitHub_projects/local-voice-spanish-tutor")
os.chdir("/Users/andrey/GitHub_projects/local-voice-spanish-tutor")

from loguru import logger
from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, ContextTypes

from core.engine import VoiceEngine
from core.memory import StudentMemory

# ── Audio conversion ────────────────────────────────────────────────────

def ogg_to_numpy(ogg_bytes: bytes):
    """Convert Telegram OGG voice to (sample_rate, numpy_float32) for Moonshine."""
    import subprocess
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f_ogg:
        f_ogg.write(ogg_bytes)
        ogg_path = f_ogg.name
    wav_path = ogg_path.replace(".ogg", ".wav")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", ogg_path, "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", wav_path],
            capture_output=True, check=True
        )
        with wave.open(wav_path, "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            sr = wf.getframerate()
            sw = wf.getsampwidth()
        if sw == 2:
            fmt = f"<{len(frames)//sw}h"
            samples = np.array(struct.unpack(fmt, frames), dtype=np.float32) / 32768.0
        else:
            samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        return (sr, samples)
    except Exception as e:
        logger.error(f"Audio conversion failed: {e}")
        return None
    finally:
        for p in [ogg_path, wav_path]:
            if Path(p).exists():
                Path(p).unlink()

# ── Handlers ────────────────────────────────────────────────────────────

app = None  # Application for building context + running async handlers

async def cmd_start(update: Update, engine, memory, app):
    uid = str(update.effective_user.id)
    name = update.effective_user.first_name or "amigo"
    memory.record_session(uid)
    profile = memory.get(uid)
    greeting = (
        f"¡Hola {name}! Soy tu tutor de español. 🇪🇸\n\n"
        f"Nivel: {profile['level']}\n\n"
        "Envía mensajes de texto o notas de voz para empezar.\n\n"
        "/progress - ver tu progreso\n"
        "/reset - reiniciar conversación\n"
        "/level - cambiar nivel"
    )
    await update.message.reply_text(greeting)
    logger.info(f"Sent /start to {uid}")

async def handle_text(update: Update, engine, memory, app):
    uid = str(update.effective_user.id)
    user_text = update.message.text
    memory.record_session(uid)
    logger.info(f"Text from {uid}: {user_text}")
    await update.message.chat.send_action("typing")
    response = engine.text_only(uid, user_text)
    clean = response.replace("*", "").replace("_", "")
    try:
        await update.message.reply_text(clean)
        logger.info(f"Replied to {uid}: {clean[:80]}")
    except Exception as e:
        logger.warning(f"Text reply failed: {e}")
        await update.message.reply_text(clean[:2000])

async def handle_voice(update: Update, engine, memory, app):
    uid = str(update.effective_user.id)
    memory.record_session(uid)
    logger.info(f"Voice from {uid}")
    await update.message.chat.send_action("typing")
    voice_file = await update.message.voice.get_file()
    voice_bytes = await voice_file.download_as_bytearray()
    audio_data = ogg_to_numpy(bytes(voice_bytes))
    if audio_data is None:
        await update.message.reply_text("No pude procesar el audio. ¿Puedes intentarlo de nuevo?")
        return
    response = engine.full_pipeline(uid, audio_data)
    clean = response.replace("*", "").replace("_", "")
    try:
        await update.message.reply_text(clean)
        logger.info(f"Voice reply to {uid}: {clean[:80]}")
    except Exception as e:
        logger.warning(f"Voice reply failed: {e}")
        await update.message.reply_text(clean[:2000])

async def cmd_reset(update: Update, engine, memory, app):
    uid = str(update.effective_user.id)
    engine.clear_history(uid)
    await update.message.reply_text("🔄 Conversación reiniciada. ¡Empecemos de nuevo! ¿De qué quieres hablar?")

async def cmd_progress(update: Update, engine, memory, app):
    uid = str(update.effective_user.id)
    summary = memory.summary(uid)
    await update.message.reply_text(f"📊 Tu Progreso:\n{summary}")

# ── Main loop ───────────────────────────────────────────────────────────

def main():
    token = os.environ.get("SPANISH_BOT_TOKEN", "")
    if not token or token == "your-telegram-bot-token":
        logger.error("No SPANISH_BOT_TOKEN in environment!")
        sys.exit(1)

    logger.info(f"Token: {token[:10]}...{token[-4:]}")

    persona_path = Path("persona/AGENTS.md")
    system_prompt = persona_path.read_text() if persona_path.exists() else ""

    logger.info("Loading engine...")
    engine = VoiceEngine(model="llama3.1:8b", system_prompt=system_prompt, tts_voice="es", max_tokens=500)
    memory = StudentMemory(str(Path("data/students.json")))

    # Build an Application just for the async run_coroutine utility
    global app
    app = ApplicationBuilder().token(token).build()

    # Create raw Bot for polling
    bot = Bot(token=token)

    # Clear any stale webhook
    logger.info("Ensuring webhook is cleared...")
    asyncio.run(bot.delete_webhook())

    logger.info("🚀 Spanish Tutor Bot is LIVE (raw Bot polling)!")

    offset = 0
    running = True

    def stop_handler(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    while running:
        try:
            updates = asyncio.run(bot.get_updates(
                offset=offset,
                timeout=10,
                allowed_updates=["message"]
            ))

            for update in updates:
                if update.update_id >= offset:
                    offset = update.update_id + 1

                if update.message is None:
                    continue

                msg = update.message
                uid = str(msg.from_user.id)

                try:
                    if msg.text:
                        if msg.text == "/start":
                            asyncio.run(cmd_start(update, engine, memory, app))
                        elif msg.text == "/reset":
                            asyncio.run(cmd_reset(update, engine, memory, app))
                        elif msg.text == "/progress":
                            asyncio.run(cmd_progress(update, engine, memory, app))
                        else:
                            asyncio.run(handle_text(update, engine, memory, app))
                    elif msg.voice or msg.audio:
                        asyncio.run(handle_voice(update, engine, memory, app))
                except Exception as e:
                    logger.error(f"Handler error for {uid}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    try:
                        asyncio.run(update.message.reply_text("Ups, algo salió mal. Inténtalo de nuevo."))
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(3)

    logger.info("Bot shutting down...")

if __name__ == "__main__":
    logger.info("=== Spanish Tutor Raw Bot ===")
    main()
