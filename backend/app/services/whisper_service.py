import asyncio
import logging
import os

logger = logging.getLogger(__name__)

WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small")
# Shares the model cache volume already mounted at /models in worker containers
WHISPER_MODEL_DIR = os.getenv("HF_HOME", "/models")

# Valid model sizes for runtime switching
VALID_MODEL_SIZES = {"tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en", "large-v1", "large-v2", "large-v3"}


class WhisperService:
    """Audio transcription using faster-whisper (CTranslate2, CPU int8).

    Model is lazy-loaded on first request and cached for the process lifetime.
    First call downloads ~460 MB from HuggingFace to WHISPER_MODEL_DIR.
    """

    _model = None
    _current_size = WHISPER_MODEL_SIZE

    @property
    def current_model_size(self) -> str:
        return self._current_size

    def reload_model(self, size: str) -> None:
        """Unload current model and load a new one. Call this sparingly."""
        size = size.strip().lower()
        if size not in VALID_MODEL_SIZES:
            raise ValueError(f"Invalid model size '{size}'. Valid: {VALID_MODEL_SIZES}")

        if self._model is not None:
            logger.info("Unloading current whisper model: %s", self._current_size)
            del self._model
            self._model = None

        from faster_whisper import WhisperModel
        logger.info("Loading whisper model: %s (this may take a moment)", size)
        self._model = WhisperModel(
            size,
            device="cpu",
            compute_type="int8",
            download_root=WHISPER_MODEL_DIR,
        )
        self._current_size = size
        logger.info("Whisper model ready: %s", size)

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            logger.info("Loading whisper model: %s (this may take a moment on first run)", self._current_size)
            self._model = WhisperModel(
                self._current_size,
                device="cpu",
                compute_type="int8",
                download_root=WHISPER_MODEL_DIR,
            )
            logger.info("Whisper model ready")
        return self._model

    def _transcribe_sync(self, audio_path: str, language: str = "auto") -> dict:
        model = self._get_model()
        lang = None if language == "auto" else language
        segments, info = model.transcribe(
            audio_path,
            language=lang,
            condition_on_previous_text=False,  # prevents "BonjourBonjour..." hallucination
            vad_filter=True,                   # skip silence, reduces hallucination on short clips
            vad_parameters={"min_silence_duration_ms": 150},  # faster VAD, less clipping on short phrases
            beam_size=1,                       # greedy decoding — much faster, slight accuracy trade-off
            best_of=1,
        )
        transcript = " ".join(seg.text.strip() for seg in segments).strip()
        logger.info(
            "Transcription complete: %d chars (detected lang=%s prob=%.2f)",
            len(transcript), info.language, info.language_probability,
        )
        return {"transcript": transcript}

    async def transcribe(self, audio_path: str, language: str = "auto") -> dict:
        """Transcribe an audio file. Runs sync work in a thread-pool executor.

        Args:
            audio_path: path to audio file (webm, mp4/m4a, ogg, wav)
            language: ISO 639-1 code ('fr', 'en') or 'auto' for detection
        Returns: {"transcript": str}
        Raises: RuntimeError on failure.
        """
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, self._transcribe_sync, audio_path, language)
        except Exception as e:
            raise RuntimeError(f"Whisper transcription failed: {e}") from e


whisper_service = WhisperService()
