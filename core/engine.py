"""
Voice engine — STT (Moonshine) + LLM (Ollama) + TTS (Kokoro) pipeline.
Reusable across languages.
"""
from pathlib import Path

import numpy as np
from fastrtc import get_stt_model, get_tts_model
from ollama import chat
from loguru import logger


class VoiceEngine:
    """Local voice pipeline that turns audio bytes → text → LLM → audio bytes."""

    def __init__(self, model: str, system_prompt: str, tts_voice: str = "en", max_tokens: int = 500):
        logger.info(f"Loading STT model (Moonshine) ...")
        self.stt = get_stt_model()
        logger.info(f"Loading TTS model (Kokoro, voice={tts_voice}) ...")
        self.tts = get_tts_model()
        self.llm_model = model
        self.system_prompt = system_prompt
        self.tts_voice = tts_voice
        self.max_tokens = max_tokens
        self._conversation_history: dict[str, list] = {}  # user_id → messages
        logger.info("Engine ready.")

    def _get_history(self, user_id: str) -> list:
        if user_id not in self._conversation_history:
            self._conversation_history[user_id] = [
                {"role": "system", "content": self.system_prompt}
            ]
        return self._conversation_history[user_id]

    def transcribe(self, audio_data: tuple[int, np.ndarray]) -> str:
        """Transcribe audio bytes to text using Moonshine."""
        sr, audio = audio_data

        # Ensure mono float32
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32) / 32768.0
        if audio.ndim == 2:
            audio = audio.mean(axis=1)

        result = self.stt.transcribe(audio, sampling_rate=sr)
        text = result.get("text", "").strip()
        logger.debug(f"STT: {text}")
        return text

    def llm_respond(self, user_id: str, prompt: str, memory_context: str = "") -> str:
        """Get LLM response with conversation history."""
        messages = self._get_history(user_id)
        messages.append({"role": "user", "content": prompt})

        # Trim history if too long (keep last 20 messages)
        if len(messages) > 22:  # system + 20
            messages = [messages[0]] + messages[-20:]
            self._conversation_history[user_id] = messages

        response = chat(
            model=self.llm_model,
            messages=messages,
            options={"num_predict": self.max_tokens},
        )
        reply = response["message"]["content"]
        messages.append({"role": "assistant", "content": reply})
        logger.debug(f"LLM: {reply}")
        return reply

    def synthesize(self, text: str) -> list[tuple[int, np.ndarray]]:
        """Generate audio chunks from text using Kokoro."""
        chunks = list(self.tts.stream_tts_sync(text))
        logger.debug(f"TTS: generated {len(chunks)} audio chunks")
        return chunks

    def full_pipeline(self, user_id: str, audio_data: tuple[int, np.ndarray]) -> str:
        """Full pipeline: audio → text → LLM → text. Returns response text."""
        transcript = self.transcribe(audio_data)
        if not transcript:
            return "Sorry, I didn't catch that. Could you repeat?"

        response = self.llm_respond(user_id, transcript)
        return response

    def text_only(self, user_id: str, text: str) -> str:
        """Chat via text — skip STT."""
        return self.llm_respond(user_id, text)

    def clear_history(self, user_id: str):
        """Reset conversation history for a user."""
        self._conversation_history[user_id] = [
            {"role": "system", "content": self.system_prompt}
        ]
        logger.info(f"Cleared history for {user_id}")
