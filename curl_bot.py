#!/usr/bin/env python3
"""Spanish Tutor Bot — polling via curl subprocess.
Zero asyncio, zero httpx, zero requests. Just curl + stdlib."""
import json
import os
import signal
import subprocess
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
from core.engine import VoiceEngine
from core.memory import StudentMemory

def curl_api(token, method, params=None):
    """Make a Telegram API call via curl subprocess."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    cmd = ["curl", "-s", "-m", "30", "-X", "POST", url]
    if params:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(params)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr}")
    data = json.loads(result.stdout)
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Unknown API error"))
    return data.get("result")

def send_message(token, chat_id, text):
    try:
        return curl_api(token, "sendMessage", {"chat_id": chat_id, "text": text})
    except Exception as e:
        logger.error(f"sendMessage failed: {e}")
        return None

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
    # Clear webhook
    logger.info("Clearing webhook...")
    curl_api(token, "deleteWebhook")
    logger.info("✓ Webhook cleared")

    print("🚀 STARTING POLLING LOOP NOW", flush=True)

    running = True
    def stop(sig, frame):
        nonlocal running
        print("Got stop signal", flush=True)
        running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    offset = 0
    poll_count = 0
    print(f"Entering while loop, running={running}", flush=True)
    while running:
        print("-- Polling for updates --", flush=True)
        try:
            updates = curl_api(token, "getUpdates", {
                "offset": offset,
                "timeout": 10,
                "allowed_updates": ["message"]
            })
            poll_count += 1
            if poll_count % 10 == 0:
                logger.info(f"Polling loop healthy (#{poll_count})")

            for upd in updates:
                offset = max(offset, upd["update_id"] + 1)
                msg = upd.get("message")
                if not msg:
                    continue

                chat_id = msg["chat"]["id"]
                uid = str(msg["from"]["id"])
                text = msg.get("text")
                voice = msg.get("voice")
                memory.record_session(uid)

                try:
                    if text:
                        if text == "/start":
                            name = msg["from"].get("first_name", "amigo")
                            profile = memory.get(uid)
                            greeting = (f"¡Hola {name}! Soy tu tutor de español. 🇪🇸\n\n"
                                        f"Nivel: {profile['level']}\n\n"
                                        "Envía mensajes o notas de voz.\n"
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
                        send_message(token, chat_id, "Procesando tu mensaje de voz...")
                        # Download voice file
                        file_info = curl_api(token, "getFile", {"file_id": voice["file_id"]})
                        file_path = file_info["file_path"]
                        ogg_path = f"/tmp/tg_voice_{uid}.ogg"
                        wav_path = ogg_path.replace(".ogg", ".wav")
                        # Download the file
                        dl_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
                        dl = subprocess.run(["curl", "-s", "-m", "60", "-o", ogg_path, dl_url],
                                            timeout=65, capture_output=True)
                        if dl.returncode != 0:
                            send_message(token, chat_id, "No pude descargar el audio.")
                            continue
                        audio_data = ogg_to_numpy(ogg_path)
                        if audio_data is None:
                            send_message(token, chat_id, "No pude procesar el audio.")
                            continue
                        response = engine.full_pipeline(uid, audio_data)
                        clean = response.replace("*", "").replace("_", "")
                        send_message(token, chat_id, clean[:2000])
                        logger.info(f"Voice replied: {clean[:80]}")
                except Exception as e:
                    logger.error(f"Handler error: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    send_message(token, chat_id, "Ups, algo salió mal.")

        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(3)

    logger.info("Bot shutting down.")


def ogg_to_numpy(ogg_path):
    import subprocess
    wav_path = ogg_path.replace(".ogg", ".wav")
    try:
        subprocess.run(["ffmpeg", "-y", "-i", ogg_path, "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", wav_path],
                        capture_output=True, check=True)
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


if __name__ == "__main__":
    logger.info("=== Spanish Tutor Bot (curl) ===")
    main()
