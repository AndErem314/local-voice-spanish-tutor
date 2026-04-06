#!/usr/bin/env python3
"""Robust Spanish Tutor Bot launcher - handles text and voice."""
import asyncio
import io
import os
import struct
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, "/Users/andrey/GitHub_projects/local-voice-spanish-tutor")
os.chdir("/Users/andrey/GitHub_projects/local-voice-spanish-tutor")

from loguru import logger
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

from core.engine import VoiceEngine
from core.memory import StudentMemory


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


def main():
    # Get token
    token = os.environ.get("SPANISH_BOT_TOKEN", "")
    if not token or token == "your-telegram-bot-token":
        logger.error("No SPANISH_BOT_TOKEN in environment!")
        sys.exit(1)

    logger.info(f"Token: {token[:10]}...{token[-4:]}")

    # Load persona
    persona_path = Path("persona/AGENTS.md")
    system_prompt = persona_path.read_text() if persona_path.exists() else ""

    # Load engine (STT + LLM + TTS)
    logger.info("Loading engine...")
    engine = VoiceEngine(
        model="llama3.1:8b",
        system_prompt=system_prompt,
        tts_voice="es",
        max_tokens=500,
    )
    memory = StudentMemory(str(Path("data/students.json")))

    # Build app with explicit request settings
    app = (
        ApplicationBuilder()
        .token(token)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .build()
    )

    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        name = update.effective_user.first_name or "amigo"
        memory.record_session(uid)
        profile = memory.get(uid)
        greeting = (
            f"\u00a1Hola {name}! Soy tu tutor de espa\u00f1ol. \U0001f1ea\U0001f1f8\n\n"
            f"Nivel: {profile['level']}\n\n"
            "Env\u00eda mensajes de texto o notas de voz para empezar.\n\n"
            "/progress - ver tu progreso\n"
            "/reset - reiniciar conversaci\u00f3n\n"
            "/level - cambiar nivel"
        )
        await update.message.reply_text(greeting)
        print(f"Sent /start response to {uid}")

    def blocking_text_response(uid, text):
        """Run LLM response in thread (blocks)."""
        return engine.text_only(uid, text)

    def blocking_voice_response(uid, audio_bytes):
        """Run full STT+LLM pipeline in thread (blocks)."""
        audio_data = ogg_to_numpy(audio_bytes)
        if audio_data is None:
            return "No pude procesar el audio. \u00bfPuedes intentarlo de nuevo?"
        return engine.full_pipeline(uid, audio_data)

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        """Catch ALL errors."""
        error = context.error
        print(f"❌ ERROR: {error!r}")
        import traceback
        traceback.print_exc()

    async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        print(f"📨 TEXT HANDLER CALLED: {update.message.text}")
        uid = str(update.effective_user.id)
        user_text = update.message.text
        memory.record_session(uid)
        logger.info(f"Received text from {uid}: {user_text}")
        await update.message.chat.send_action("typing")

        response = await asyncio.to_thread(blocking_text_response, uid, user_text)
        logger.info(f"LLM response: {response[:100]}...")

        clean = response.replace("*", "").replace("_", "")
        try:
            await update.message.reply_text(clean)
            print(f"Replied to {uid}: {clean[:80]}")
        except Exception as e:
            logger.warning(f"Text reply failed: {e}")
            await update.message.reply_text(clean[:2000])

    async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        memory.record_session(uid)
        logger.info(f"Received voice from {uid}")
        await update.message.chat.send_action("typing")

        voice_file = await update.message.voice.get_file()
        voice_bytes = await voice_file.download_as_bytearray()

        response = await asyncio.to_thread(blocking_voice_response, uid, bytes(voice_bytes))
        logger.info(f"Voice response: {response[:100]}...")

        clean = response.replace("*", "").replace("_", "")
        try:
            await update.message.reply_text(clean)
            print(f"Replied to voice from {uid}: {clean[:80]}")
        except Exception as e:
            logger.warning(f"Voice reply failed: {e}")
            await update.message.reply_text(clean[:2000])

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_error_handler(error_handler)

    logger.info("\U0001f680 Spanish Tutor Bot is now LIVE and accepting messages!")
    app.run_polling(
        poll_interval=0.1,
        timeout=30,
        bootstrap_retries=0,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    logger.info("=== Spanish Tutor Bot Launcher ===")
    main()
