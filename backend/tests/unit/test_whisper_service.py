import pytest
from unittest.mock import patch, MagicMock
from app.services.whisper_service import WhisperService


class TestWhisperService:
    def test_transcribe_sync_returns_transcript(self):
        """_transcribe_sync joins segment text into a single string."""
        svc = WhisperService()

        seg1 = MagicMock()
        seg1.text = "  Bonjour, ceci est un test.  "
        seg2 = MagicMock()
        seg2.text = "Merci beaucoup."

        info = MagicMock()
        info.language = "fr"
        info.language_probability = 0.99

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([seg1, seg2], info)
        svc._model = mock_model

        result = svc._transcribe_sync("/tmp/audio.m4a", language="fr")
        assert result["transcript"] == "Bonjour, ceci est un test. Merci beaucoup."
        mock_model.transcribe.assert_called_once_with(
            "/tmp/audio.m4a",
            language="fr",
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )

    def test_transcribe_sync_auto_language_passes_none(self):
        """language='auto' is passed as None to faster-whisper."""
        svc = WhisperService()

        info = MagicMock()
        info.language = "en"
        info.language_probability = 0.95

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([], info)
        svc._model = mock_model

        svc._transcribe_sync("/tmp/audio.webm", language="auto")
        call_kwargs = mock_model.transcribe.call_args
        assert call_kwargs[1]["language"] is None

    def test_transcribe_sync_empty_segments(self):
        """No segments produces an empty transcript."""
        svc = WhisperService()

        info = MagicMock()
        info.language = "fr"
        info.language_probability = 0.5

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([], info)
        svc._model = mock_model

        result = svc._transcribe_sync("/tmp/silence.m4a")
        assert result["transcript"] == ""

    @pytest.mark.asyncio
    async def test_transcribe_wraps_sync_in_executor(self):
        """transcribe() runs sync work in a thread executor and returns result."""
        svc = WhisperService()

        info = MagicMock()
        info.language = "fr"
        info.language_probability = 0.99

        seg = MagicMock()
        seg.text = "Hello world."

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([seg], info)
        svc._model = mock_model

        result = await svc.transcribe("/tmp/test.ogg", language="en")
        assert result["transcript"] == "Hello world."

    @pytest.mark.asyncio
    async def test_transcribe_raises_runtime_error_on_failure(self):
        """transcribe() converts unexpected errors to RuntimeError."""
        svc = WhisperService()
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = ValueError("bad audio")
        svc._model = mock_model

        with pytest.raises(RuntimeError, match="Whisper transcription failed"):
            await svc.transcribe("/tmp/bad.ogg")
