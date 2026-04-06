#!/usr/bin/env python3
"""Spanish Tutor Bot — fully synchronous polling with requests.
Zero asyncio usage for the polling loop."""
import json
import os
import signal
import sys
import tempfile
import time
import wave
import threading
from pathlib import Path
import struct
import subprocess

import numpy as np
import requests

sys.path.insert(0, "/Users/andrey/GitHub_projects/local-voice-spanish-tutor")
os.chdir("/Users/andrey/GitHub_projects/local-voice-spanish-tutor")

from loguru import logger
from core.engine import VoiceEngine
from core.memory import StudentMemory

BASE = "https://api.telegram.org/bot"

def api(token, method, **kwargs):
    """Synchronous Telegram Bot API call."""
    url = f"{BASE}{token}/{method}"
    resp = requests.post(url, json=kwargs, timeout=30)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Unknown API error"))
    return data.get("result")

def send_message(token, chat_id, text):
    return api(token, "sendMessage", chat_id=chat_id, text=text)

def send_action(token, chat_id, action):
    try:
        api(token, "sendChatAction", chat_id=chat_id, action=action)
    except Exception:
        pass

def download_voice(token, file_id, out_path):
    """Download voice file via Telegram API."""
    file_info = api(token, "getFile", file_id=file_id)
    file_path = file_info["file_path"]
    url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    resp = requests.get(url, timeout=60)
    with open(out_path, "wb") as f:
        f.write(resp.content)
    return out_path

def ogg_to_numpy(ogg_path):
    """Convert OGG to numpy float32 audio."""
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
    token = os.environ.get("SPANISH_BOT_TOKEN", "")
    if not token or token == "your-telegram-bot-token":
        logger.error("No SPANISH_BOT_TOKEN in environment!")
        sys.exit(1)
    logger.info(f"Token: {token[:10]}...{token[-4:]}")

    persona_path = Path("persona/AGENTS.md")
    system_prompt = persona_path.read_text() if persona_path.exists() else ""

    logger.info("Loading engine (Moonshine + Ollama + Kokoro)...")
    engine = VoiceEngine(model="llama3.1:8b", system_prompt=system_prompt, tts_voice="es", max_tokens=500)
    memory = StudentMemory(str(Path("data/students.json")))

    # Clear webhook so polling works
    try:
        api(token, "deleteWebhook")
        logger.info("Webhook cleared")
    except Exception:
        pass

    logger.info("🚀 Spanish Tutor Bot is LIVE (sync polling)!")

    running = True
    def stop(sig, frame):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    offset = 0
    while running:
        try:
            updates = api(token, "getUpdates", offset=offset, timeout=10, allowed_updates=["message"])
            for upd in updates:
                offset = max(offset, upd["update_id"] + 1)
                msg = upd.get("message")
                if not msg:
                    continue
                text = msg.get("text")
                voice = msg.get("voice")
                chat_id = msg["chat"]["id"]
                uid = str(msg["from"]["id"])
                memory.record_session(uid)

                try:
                    if text:
                        if text == "/start":
                            name = msg["from"].get("first_name", "amigo")
                            profile = memory.get(uid)
                            greeting = (f"¡Hola {name}! Soy tu tutor de español. 🇪🇸\n\n"
                                        f"Nivel: {profile['level']}\n\n"
                                        "Envía mensajes de texto o notas de voz.\n"
                                        "/progress - ver tu progreso\n"
                                        "/reset - reiniciar\n"
                                        "/level - cambiar nivel")
                            send_message(token, chat_id, greeting)
                        elif text == "/reset":
                            engine.clear_history(uid)
                            send_message(token, chat_id, "🔄 Conversación reiniciada. ¿De qué quieres hablar?")
                        elif text == "/progress":
                            summary = memory.summary(uid)
                            send_message(token, chat_id, f"📊 Tu Progreso:\n{summary}")
                        else:
                            logger.info(f"Text from {uid}: {text}")
                            response = engine.text_only(uid, text)
                            clean = response.replace("*", "").replace("_", "")
                            send_message(token, chat_id, clean[:2000])
                            logger.info(f"Replied: {clean[:80]}")

                    elif voice:
                        logger.info(f"Voice from {uid}")
                        send_action(token, chat_id, "typing")
                        ogg = f"/tmp/tg_voice_{uid}.ogg"
                        download_voice(token, voice["file_id"], ogg)
                        audio_data = ogg_to_numpy(ogg)
                        if audio_data is None:
                            send_message(token, chat_id, "No pude procesar el audio. ¿Intentar de nuevo?")
                            continue
                        response = engine.full_pipeline(uid, audio_data)
                        clean = response.replace("*", "").replace("_", "")
                        send_message(token, chat_id, clean[:2000])
                        logger.info(f"Voice replied: {clean[:80]}")
                except Exception as e:
                    logger.error(f"Handler error: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    try:
                        send_message(token, chat_id, "Ups, algo salió mal. Inténtalo de nuevo.")
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(3)

    logger.info("Bot shutting down.")

if __name__ == "__main__":
    logger.info("=== Spanish Tutor Bot (sync) ===")
    main()
