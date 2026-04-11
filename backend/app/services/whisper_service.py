import asyncio
import logging
import os
import re

logger = logging.getLogger(__name__)

WHISPER_BINARY = os.getenv("WHISPER_BINARY", "/usr/local/bin/whisper-cpp")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "/models/ggml-small.bin")
WHISPER_TIMEOUT = int(os.getenv("WHISPER_TIMEOUT", "30"))


class WhisperService:
    """Wraps whisper.cpp CLI for server-side audio transcription."""

    def _build_command(self, audio_path: str, language: str = "auto") -> list[str]:
        return [
            WHISPER_BINARY,
            "-m", WHISPER_MODEL,
            "-f", audio_path,
            "--language", language,
            "--no-timestamps",
            "--print-progress", "false",
        ]

    def _parse_output(self, raw: str) -> dict:
        """Parse whisper.cpp output into clean transcript."""
        if not raw.strip():
            return {"transcript": ""}
        # Remove timestamp lines like [00:00:00.000 --> 00:00:03.000]
        lines = raw.strip().split("\n")
        cleaned = []
        for line in lines:
            # Strip timestamp prefix if present
            text = re.sub(r"\[[\d:.]+\s*-->\s*[\d:.]+\]\s*", "", line).strip()
            if text:
                cleaned.append(text)
        return {"transcript": " ".join(cleaned)}

    async def transcribe(self, audio_path: str, language: str = "auto") -> dict:
        """Transcribe an audio file using whisper.cpp.

        Args:
            audio_path: path to audio file
            language: ISO 639-1 code (e.g. 'fr', 'en') or 'auto' for detection
        Returns: {"transcript": str}
        Raises: RuntimeError on whisper failure.
        """
        cmd = self._build_command(audio_path, language=language)
        logger.info(f"Whisper transcription: {audio_path} (lang={language})")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=WHISPER_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Whisper transcription timed out after {WHISPER_TIMEOUT}s")

        if proc.returncode != 0:
            error_msg = stderr.decode().strip()
            raise RuntimeError(f"Whisper failed (exit {proc.returncode}): {error_msg}")

        result = self._parse_output(stdout.decode())
        logger.info(f"Transcription complete: {len(result['transcript'])} chars")
        return result


whisper_service = WhisperService()
