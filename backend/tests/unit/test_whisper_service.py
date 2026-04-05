import pytest
from unittest.mock import patch, AsyncMock
from app.services.whisper_service import WhisperService


class TestWhisperService:
    def test_build_command(self):
        """Whisper CLI command is built correctly."""
        svc = WhisperService()
        cmd = svc._build_command("/tmp/audio.ogg")
        assert "/usr/local/bin/whisper-cpp" in cmd[0] or "whisper" in cmd[0]
        assert "/tmp/audio.ogg" in cmd
        assert "--language" in cmd
        assert "auto" in cmd

    def test_parse_output_extracts_text(self):
        """Raw whisper output is parsed to clean transcript."""
        svc = WhisperService()
        raw = "[00:00:00.000 --> 00:00:03.000]  Bonjour, ceci est un test.\n[00:00:03.000 --> 00:00:05.000]  Merci beaucoup."
        result = svc._parse_output(raw)
        assert result["transcript"] == "Bonjour, ceci est un test. Merci beaucoup."

    def test_parse_output_empty(self):
        """Empty output returns empty transcript."""
        svc = WhisperService()
        result = svc._parse_output("")
        assert result["transcript"] == ""

    @pytest.mark.asyncio
    @patch("app.services.whisper_service.asyncio.create_subprocess_exec")
    async def test_transcribe_calls_subprocess(self, mock_exec):
        """transcribe() calls whisper-cpp and returns parsed result."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"[00:00:00.000 --> 00:00:02.000]  Hello world.\n",
            b"",
        )
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        svc = WhisperService()
        result = await svc.transcribe("/tmp/test.ogg")
        assert result["transcript"] == "Hello world."
        mock_exec.assert_called_once()
