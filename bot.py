"""
Telegram bot for local voice tutor.
Handles text messages, voice messages, and progress queries.
"""
import io
import wave
import tempfile
import os
import asyncio
from pathlib import Path

import numpy as np
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from core.config import load_config
from core.engine import VoiceEngine
from core.memory import StudentMemory
from loguru import logger


class TutorBot:
    """Telegram bot that wraps the VoiceEngine for a single language tutor."""

    def __init__(self):
        self.config = load_config()
        self.memory = StudentMemory(
            str(Path(__file__).parent.parent / "data" / "students.json")
        )

        # Load persona / system prompt
        persona_path = Path(__file__).parent.parent / "persona" / "AGENTS.md"
        self.system_prompt = persona_path.read_text() if persona_path.exists() else ""

        self.engine = VoiceEngine(
            model=self.config["ollama_model"],
            system_prompt=self.system_prompt,
            tts_voice=self.config.get("tts_voice", "en"),
            max_tokens=self.config.get("max_response_tokens", 500),
        )

        self.app: Application | None = None

    # ── Commands ────────────────────────────────────────────────────────

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        name = update.effective_user.first_name or "student"
        self.memory.record_session(uid)
        profile = self.memory.get(uid)

        greeting = (
            f"¡Hola {name}! 👋 Soy tu tutor de español.\n\n"
            f"Nivel actual: {profile['level']}\n"
            "Envíame mensajes de texto **o notas de voz** para empezar.\n\n"
            f"/progress — ver tu progreso\n"
            f"/reset — reiniciar conversación\n"
            f"/level — cambiar nivel (A1, A2, B1, B2, C1)"
        )
        await update.message.reply_text(greeting, parse_mode="Markdown")

    async def cmd_progress(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        summary = self.memory.summary(uid)
        await update.message.reply_text(f"📊 **Tu Progreso:**\n{summary}", parse_mode="Markdown")

    async def cmd_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        self.engine.clear_history(uid)
        await update.message.reply_text(
            "🔄 Conversación reiniciada. ¡Empecemos de nuevo! ¿De qué quieres hablar?"
        )

    async def cmd_level(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Change student level: /level B1"""
        uid = str(update.effective_user.id)
        if context.args:
            new_level = context.args[0].upper()
            valid_levels = {"A1", "A2", "B1", "B2", "C1", "C2"}
            if new_level in valid_levels:
                self.memory.update(uid, {"level": new_level})
                await update.message.reply_text(
                    f"✅ Nivel cambiado a **{new_level}**.", parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"Niveles válidos: {', '.join(sorted(valid_levels))}"
                )
        else:
            current = self.memory.get(uid)["level"]
            await update.message.reply_text(f"Tu nivel actual: **{current}**", parse_mode="Markdown")

    # ── Message Handlers ────────────────────────────────────────────────

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process incoming voice message: STT → LLM → TTS + text reply."""
        uid = str(update.effective_user.id)
        self.memory.record_session(uid)

        # Send typing indicator
        await update.message.chat.send_action("typing")

        # Download voice message
        voice = await update.message.voice.get_file()
        voice_bytes = await voice.download_as_bytearray()

        # Convert OGG to WAV → numpy for Moonshine
        audio_data = self._ogg_to_numpy(voice_bytes)
        if audio_data is None:
            await update.message.reply_text("❌ No pude procesar el audio. ¿Puedes intentarlo de nuevo?")
            return

        # STT → LLM
        response_text = self.engine.full_pipeline(uid, audio_data)

        # Send text reply
        if self.config.get("always_send_text", True):
            await update.message.reply_text(response_text, parse_mode="Markdown")

        # Send voice reply
        if self.config.get("always_send_voice", True):
            await self._send_voice_message(update, response_text)

        # Update memory with topic inference
        self._update_memory_from_response(uid, response_text)

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process incoming text message."""
        uid = str(update.effective_user.id)
        self.memory.record_session(uid)
        await update.message.chat.send_action("typing")

        response_text = self.engine.text_only(uid, update.message.text)

        if self.config.get("always_send_text", True):
            await update.message.reply_text(response_text, parse_mode="Markdown")

        if self.config.get("always_send_voice", True):
            await self._send_voice_message(update, response_text)

        self._update_memory_from_response(uid, response_text)

    async def handle_audio(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process audio file messages (same as voice)."""
        await self.handle_voice(update, context)

    # ── Helper Methods ──────────────────────────────────────────────────

    def _ogg_to_numpy(self, ogg_bytes: bytearray) -> tuple[int, np.ndarray] | None:
        """Convert OGG voice message to (sample_rate, numpy_float32) for Moonshine."""
        try:
            import subprocess

            # Use ffmpeg to convert OGG to WAV, then read with wave module
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f_ogg:
                f_ogg.write(ogg_bytes)
                ogg_path = f_ogg.name

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_wav:
                wav_path = f_wav.name

            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", ogg_path,
                    "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
                    wav_path
                ],
                capture_output=True, check=True
            )

            os.unlink(ogg_path)

            # Read WAV to numpy
            import wave as wave_module
            with wave_module.open(wav_path, 'rb') as wf:
                frames = wf.readframes(wf.getnframes())
                sample_rate = wf.getframerate()
                n_channels = wf.getnchannels()
                sample_width = wf.getsampwidth()

            os.unlink(wav_path)

            # Convert bytes to numpy int16 → float32
            import struct
            if sample_width == 2:
                fmt = f"<{len(frames)//sample_width}h"
                samples = np.array(struct.unpack(fmt, frames), dtype=np.float32) / 32768.0
            else:
                samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

            if n_channels > 1:
                samples = samples.reshape(-1, n_channels).mean(axis=1)

            return (sample_rate, samples)

        except Exception as e:
            logger.error(f"Audio conversion failed: {e}")
            return None

    async def _send_voice_message(self, update: Update, text: str):
        """Generate TTS audio and send as Telegram voice message."""
        try:
            chunks = self.engine.synthesize(text)
            if not chunks:
                return

            # Convert audio chunks to OGG for Telegram
            ogg_data = self._numpy_chunks_to_ogg(chunks)
            if ogg_data:
                await update.message.reply_voice(io.BytesIO(ogg_data))
        except Exception as e:
            logger.error(f"TTS failed: {e}")

    def _numpy_chunks_to_ogg(self, chunks: list) -> bytes | None:
        """Audio chunks → OGG bytes via ffmpeg."""
        import subprocess
        import tempfile
        import os

        if not chunks:
            return None

        # Concatenate all chunks into single audio buffer
        audio_arrays = []
        for sr, audio in chunks:
            audio_arrays.append(audio)

        if not audio_arrays:
            return None

        combined = np.concatenate(audio_arrays)
        combined = np.clip(combined, -1, 1)

        # Write to WAV first
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_f:
            wav_path = wav_f.name

        import wave as wave_module
        with wave_module.open(wav_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(24000)  # Moonshine default
            # Convert float32 → int16
            pcm = (combined * 32767).astype(np.int16).tobytes()
            wf.writeframes(pcm)

        # Convert WAV to OGG
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as ogg_f:
            ogg_path = ogg_f.name

        subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path, "-ar", "24000", "-ac", "1", "-b:a", "32k", ogg_path],
            capture_output=True, check=True
        )
        os.unlink(wav_path)

        with open(ogg_path, "rb") as f:
            data = f.read()

        os.unlink(ogg_path)
        return data if data else None

    def _update_memory_from_response(self, uid: str, response: str):
        """Update student memory based on LLM response content."""
        # Infer topics from response
        # This is simple keyword-based — could be enhanced with LLM
        topic_keywords = {
            "verbos": ["conjugate", "verbo", "verbo", "tense"],
            "vocabulario": ["significa", "palabra", "vocabulario"],
            "gramatica": ["gramatical", "subjonctivo", "subjuntivo"],
            "pronunciacion": ["pronuncia", "sonido", "pronounce"],
        }
        for topic, keywords in topic_keywords.items():
            if any(kw in response.lower() for kw in keywords):
                self.memory.add_weak_area(uid, topic)

    def _update_memory_from_transcript(self, uid: str, transcript: str):
        """Extract potential vocabulary from student's message."""
        # Simple word extraction — could be more sophisticated
        words = transcript.split()
        long_words = [w.strip(".,!?¿¡\"'") for w in words if len(w) > 5]
        if long_words:
            self.memory.add_vocabulary(uid, long_words)

    # ── Run ─────────────────────────────────────────────────────────────

    def run(self):
        """Start the Telegram bot."""
        token = self.config.get("bot_token", "")
        if not token or token == "your-telegram-bot-token":
            logger.error("No bot_token in config.json or BOT_TOKEN env var")
            return

        self.app = Application.builder().token(token).build()
        dp = self.app.dispatcher

        dp.add_handler(CommandHandler("start", self.cmd_start))
        dp.add_handler(CommandHandler("progress", self.cmd_progress))
        dp.add_handler(CommandHandler("reset", self.cmd_reset))
        dp.add_handler(CommandHandler("level", self.cmd_level))
        dp.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self.handle_voice))
        dp.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))

        logger.info(f"🚀 Spanish Tutor Bot starting ...")
        logger.info(f"Model: {self.config['ollama_model']}")
        logger.info(f"Language: {self.config.get('language_code', 'es')}")
        self.app.run_polling()


if __name__ == "__main__":
    bot = TutorBot()
    bot.run()
