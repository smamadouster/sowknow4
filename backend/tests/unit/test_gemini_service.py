"""
Unit tests for Gemini Flash service
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from google.generativeai.types import GenerateContentResponse, GenerationConfig, ContentType

from app.services.gemini_service import (
    GeminiService,
    GeminiUsageMetadata,
    GeminiCacheManager
)


@pytest.fixture
def mock_gemini_client():
    """Create a mock Gemini client"""
    with patch("app.services.gemini_service.genai") as mock_genai:
        mock_model = MagicMock()
        mock_genai.configure.return_value = None
        mock_genai.GenerativeModel.return_value = mock_model
        yield mock_genai, mock_model


@pytest.fixture
def gemini_service():
    """Create a GeminiService instance for testing"""
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test_api_key"}):
        service = GeminiService()
        return service


@pytest.fixture
def cache_manager():
    """Create a GeminiCacheManager instance for testing"""
    return GeminiCacheManager()


class TestGeminiUsageMetadata:
    """Test suite for GeminiUsageMetadata class"""

    def test_initialization_default_values(self):
        """Test metadata initialization with default values"""
        metadata = GeminiUsageMetadata()
        assert metadata.prompt_tokens == 0
        assert metadata.cached_tokens == 0
        assert metadata.completion_tokens == 0
        assert metadata.total_tokens == 0
        assert metadata.cache_hit is False

    def test_initialization_with_values(self):
        """Test metadata initialization with custom values"""
        metadata = GeminiUsageMetadata(
            prompt_tokens=1000,
            cached_tokens=500,
            completion_tokens=2000,
            total_tokens=3500,
            cache_hit=True
        )
        assert metadata.prompt_tokens == 1000
        assert metadata.cached_tokens == 500
        assert metadata.completion_tokens == 2000
        assert metadata.total_tokens == 3500
        assert metadata.cache_hit is True

    def test_to_dict(self):
        """Test converting metadata to dictionary"""
        metadata = GeminiUsageMetadata(
            prompt_tokens=1000,
            cached_tokens=500,
            completion_tokens=2000,
            total_tokens=3500,
            cache_hit=True
        )
        result = metadata.to_dict()
        assert result == {
            "prompt_tokens": 1000,
            "cached_tokens": 500,
            "completion_tokens": 2000,
            "total_tokens": 3500,
            "cache_hit": True
        }

    def test_from_gemini_response_with_full_metadata(self):
        """Test extracting metadata from Gemini response with full metadata"""
        mock_response = Mock()
        mock_usage_metadata = Mock()
        mock_usage_metadata.prompt_token_count = 1000
        mock_usage_metadata.cached_content_token_count = 500
        mock_usage_metadata.candidates_token_count = 2000
        mock_usage_metadata.total_token_count = 3500
        mock_response.usage_metadata = mock_usage_metadata

        metadata = GeminiUsageMetadata.from_gemini_response(mock_response)

        assert metadata.prompt_tokens == 1000
        assert metadata.cached_tokens == 500
        assert metadata.completion_tokens == 2000
        assert metadata.total_tokens == 3500
        assert metadata.cache_hit is True

    def test_from_gemini_response_without_metadata(self):
        """Test extracting metadata from Gemini response without metadata"""
        mock_response = Mock()
        mock_response.usage_metadata = None

        metadata = GeminiUsageMetadata.from_gemini_response(mock_response)

        assert metadata.prompt_tokens == 0
        assert metadata.cached_tokens == 0
        assert metadata.completion_tokens == 0
        assert metadata.total_tokens == 0
        assert metadata.cache_hit is False

    def test_from_gemini_response_with_zero_cached_tokens(self):
        """Test that cache_hit is False when cached tokens are zero"""
        mock_response = Mock()
        mock_usage_metadata = Mock()
        mock_usage_metadata.prompt_token_count = 1000
        mock_usage_metadata.cached_content_token_count = 0
        mock_usage_metadata.candidates_token_count = 2000
        mock_usage_metadata.total_token_count = 3000
        mock_response.usage_metadata = mock_usage_metadata

        metadata = GeminiUsageMetadata.from_gemini_response(mock_response)

        assert metadata.cache_hit is False


class TestGeminiCacheManager:
    """Test suite for GeminiCacheManager class"""

    def test_initialization(self, cache_manager):
        """Test cache manager initialization"""
        assert cache_manager.cache_entries == {}
        assert cache_manager.cache_ttl == 3600

    def test_generate_cache_key(self, cache_manager):
        """Test cache key generation"""
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "What is the weather?"}
        ]
        key = cache_manager._generate_cache_key(messages)
        assert key.startswith("gemini_cache_")
        assert isinstance(key, str)

    def test_generate_cache_key_deterministic(self, cache_manager):
        """Test that cache key generation is deterministic"""
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"}
        ]
        key1 = cache_manager._generate_cache_key(messages)
        key2 = cache_manager._generate_cache_key(messages)
        assert key1 == key2

    def test_generate_cache_key_different_messages(self, cache_manager):
        """Test that different messages generate different keys"""
        messages1 = [
            {"role": "user", "content": "Hello"}
        ]
        messages2 = [
            {"role": "user", "content": "Goodbye"}
        ]
        key1 = cache_manager._generate_cache_key(messages1)
        key2 = cache_manager._generate_cache_key(messages2)
        assert key1 != key2

    @pytest.mark.asyncio
    async def test_get_or_create_cached_content_no_cache(self, cache_manager):
        """Test get_or_create when no cache exists"""
        mock_model = MagicMock()
        result = await cache_manager.get_or_create_cached_content(
            mock_model,
            "System instruction",
            []
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_get_or_create_cached_content_cache_hit(self, cache_manager):
        """Test get_or_create when cache exists and is valid"""
        mock_model = MagicMock()
        cache_key = "test_key"
        cache_manager.cache_entries[cache_key] = {
            "cache_name": "test_cache",
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(seconds=3600),
            "content_hash": 123
        }

        with patch.object(cache_manager, "_generate_cache_key", return_value=cache_key):
            result = await cache_manager.get_or_create_cached_content(
                mock_model,
                "System instruction",
                []
            )
        assert result == "test_cache"

    @pytest.mark.asyncio
    async def test_get_or_create_cached_content_cache_expired(self, cache_manager):
        """Test get_or_create when cache exists but is expired"""
        mock_model = MagicMock()
        cache_key = "test_key"
        cache_manager.cache_entries[cache_key] = {
            "cache_name": "test_cache",
            "created_at": datetime.utcnow() - timedelta(seconds=7200),
            "expires_at": datetime.utcnow() - timedelta(seconds=1),
            "content_hash": 123
        }

        with patch.object(cache_manager, "_generate_cache_key", return_value=cache_key):
            result = await cache_manager.get_or_create_cached_content(
                mock_model,
                "System instruction",
                []
            )
        assert result is None
        assert cache_key not in cache_manager.cache_entries

    @pytest.mark.asyncio
    async def test_create_cached_content(self, cache_manager):
        """Test creating new cached content"""
        mock_model = MagicMock()
        system_instruction = "You are a helpful assistant"
        conversation_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"}
        ]
        current_query = "How are you?"

        result = await cache_manager.create_cached_content(
            mock_model,
            system_instruction,
            conversation_history,
            current_query
        )

        assert result is not None
        assert result.startswith("sowknow_cache_")
        assert len(cache_manager.cache_entries) == 1

    @pytest.mark.asyncio
    async def test_cleanup_expired_cache(self, cache_manager):
        """Test cleanup of expired cache entries"""
        # Add both valid and expired entries
        cache_manager.cache_entries["valid_key"] = {
            "cache_name": "valid_cache",
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(seconds=3600),
            "content_hash": 1
        }
        cache_manager.cache_entries["expired_key"] = {
            "cache_name": "expired_cache",
            "created_at": datetime.utcnow() - timedelta(seconds=7200),
            "expires_at": datetime.utcnow() - timedelta(seconds=1),
            "content_hash": 2
        }

        await cache_manager.cleanup_expired_cache()

        assert "valid_key" in cache_manager.cache_entries
        assert "expired_key" not in cache_manager.cache_entries

    def test_get_cache_stats(self, cache_manager):
        """Test getting cache statistics"""
        cache_manager.cache_entries["cache1"] = {
            "cache_name": "cache_1",
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(seconds=3600),
            "content_hash": 1
        }
        cache_manager.cache_entries["cache2"] = {
            "cache_name": "cache_2",
            "created_at": datetime.utcnow() - timedelta(seconds=7200),
            "expires_at": datetime.utcnow() - timedelta(seconds=1),
            "content_hash": 2
        }

        stats = cache_manager.get_cache_stats()

        assert stats["total_entries"] == 2
        assert stats["active_entries"] == 1
        assert stats["ttl_seconds"] == 3600


class TestGeminiService:
    """Test suite for GeminiService class"""

    def test_initialization_with_api_key(self):
        """Test service initialization with API key"""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test_key"}):
            with patch("app.services.gemini_service.genai") as mock_genai:
                service = GeminiService()
                assert service.api_key == "test_key"
                assert service.model_name == "gemini-2.0-flash-exp"
                assert service.max_tokens == 1000000
                assert isinstance(service.cache_manager, GeminiCacheManager)

    def test_initialization_without_api_key(self):
        """Test service initialization without API key"""
        with patch.dict("os.environ", {}, clear=True):
            with patch("app.services.gemini_service.genai") as mock_genai:
                service = GeminiService()
                assert service.api_key is None
                assert service.model is None

    def test_convert_messages_to_gemini_format_with_system(self):
        """Test converting messages with system prompt"""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test_key"}):
            with patch("app.services.gemini_service.genai"):
                service = GeminiService()
                messages = [
                    {"role": "system", "content": "You are helpful"},
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi"}
                ]
                contents, system_instruction = service._convert_messages_to_gemini_format(messages)

                assert system_instruction == "You are helpful"
                assert len(contents) == 2
                assert contents[0]["role"] == "user"
                assert contents[1]["role"] == "model"

    def test_convert_messages_to_gemini_format_without_system(self):
        """Test converting messages without system prompt"""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test_key"}):
            with patch("app.services.gemini_service.genai"):
                service = GeminiService()
                messages = [
                    {"role": "user", "content": "Hello"}
                ]
                contents, system_instruction = service._convert_messages_to_gemini_format(messages)

                assert system_instruction is None
                assert len(contents) == 1
                assert contents[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_chat_completion_non_streaming(self, gemini_service):
        """Test non-streaming chat completion"""
        # Mock the model response
        mock_response = Mock()
        mock_candidate = Mock()
        mock_content = Mock()
        mock_part = Mock()
        mock_part.text = "This is a test response"
        mock_content.parts = [mock_part]
        mock_candidate.content = mock_content
        mock_response.candidates = [mock_candidate]

        # Mock usage metadata
        mock_usage = Mock()
        mock_usage.prompt_token_count = 100
        mock_usage.cached_content_token_count = 50
        mock_usage.candidates_token_count = 200
        mock_usage.total_token_count = 350
        mock_response.usage_metadata = mock_usage

        with patch.object(gemini_service, "model") as mock_model:
            mock_model._generation_config = GenerationConfig(temperature=0.7, max_output_tokens=8192)
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor.return_value = mock_response

                results = []
                async for chunk in gemini_service.chat_completion(
                    messages=[{"role": "user", "content": "Hello"}],
                    stream=False
                ):
                    results.append(chunk)

                assert len(results) == 2
                assert results[0] == "This is a test response"
                assert results[1].startswith("\n__USAGE__:")

    @pytest.mark.asyncio
    async def test_chat_completion_streaming(self, gemini_service):
        """Test streaming chat completion"""
        # Mock streaming response
        mock_chunk1 = Mock()
        mock_candidate1 = Mock()
        mock_content1 = Mock()
        mock_part1 = Mock()
        mock_part1.text = "Hello "
        mock_content1.parts = [mock_part1]
        mock_candidate1.content = mock_content1
        mock_chunk1.candidates = [mock_candidate1]

        mock_chunk2 = Mock()
        mock_candidate2 = Mock()
        mock_content2 = Mock()
        mock_part2 = Mock()
        mock_part2.text = "world!"
        mock_content2.parts = [mock_part2]
        mock_candidate2.content = mock_content2
        mock_chunk2.candidates = [mock_candidate2]

        mock_response = iter([mock_chunk1, mock_chunk2])

        with patch.object(gemini_service, "model") as mock_model:
            mock_model._generation_config = GenerationConfig(temperature=0.7, max_output_tokens=8192)
            mock_model.generate_content.return_value = mock_response

            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor.return_value = mock_response

                results = []
                async for chunk in gemini_service.chat_completion(
                    messages=[{"role": "user", "content": "Hello"}],
                    stream=True
                ):
                    results.append(chunk)

                assert len(results) == 2
                assert results[0] == "Hello "
                assert results[1] == "world!"

    @pytest.mark.asyncio
    async def test_chat_completion_without_api_key(self):
        """Test chat completion when API key is not configured"""
        with patch.dict("os.environ", {}, clear=True):
            with patch("app.services.gemini_service.genai"):
                service = GeminiService()

                results = []
                async for chunk in service.chat_completion(
                    messages=[{"role": "user", "content": "Hello"}],
                    stream=False
                ):
                    results.append(chunk)

                assert len(results) == 1
                assert "API key not configured" in results[0]

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, gemini_service):
        """Test health check when service is healthy"""
        mock_response = Mock()
        mock_candidate = Mock()
        mock_response.candidates = [mock_candidate]

        with patch.object(gemini_service, "model") as mock_model:
            mock_model.generate_content.return_value = mock_response

            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor.return_value = mock_response

                health = await gemini_service.health_check()

                assert health["service"] == "gemini"
                assert health["status"] == "healthy"
                assert health["api_configured"] is True
                assert health["api_reachable"] is True

    @pytest.mark.asyncio
    async def test_health_check_no_api_key(self):
        """Test health check when API key is not configured"""
        with patch.dict("os.environ", {}, clear=True):
            with patch("app.services.gemini_service.genai"):
                service = GeminiService()
                health = await service.health_check()

                assert health["service"] == "gemini"
                assert health["status"] == "unhealthy"
                assert health["api_configured"] is False
                assert "API key not configured" in health["error"]

    @pytest.mark.asyncio
    async def test_health_check_api_unreachable(self, gemini_service):
        """Test health check when API is unreachable"""
        with patch.object(gemini_service, "model") as mock_model:
            mock_model.generate_content.side_effect = Exception("Connection error")

            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor.side_effect = Exception("Connection error")

                health = await gemini_service.health_check()

                assert health["service"] == "gemini"
                assert health["status"] == "unhealthy"
                assert health["api_reachable"] is False
                assert "Connection error" in health["error"]

    @pytest.mark.asyncio
    async def test_get_usage_stats(self, gemini_service):
        """Test getting usage statistics"""
        stats = await gemini_service.get_usage_stats()

        assert stats["service"] == "gemini"
        assert stats["model"] == "gemini-2.0-flash-exp"
        assert "cache_stats" in stats
        assert "config" in stats
        assert stats["config"]["max_tokens"] == 1000000
        assert stats["config"]["cache_ttl"] == 3600
        assert stats["config"]["daily_budget_cap"] == 50.0

    @pytest.mark.asyncio
    async def test_cleanup_cache(self, gemini_service):
        """Test cache cleanup"""
        with patch.object(gemini_service.cache_manager, "cleanup_expired_cache") as mock_cleanup:
            await gemini_service.cleanup_cache()
            mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_completion_with_error(self, gemini_service):
        """Test chat completion when an error occurs"""
        with patch.object(gemini_service, "model") as mock_model:
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor.side_effect = Exception("API Error")

                results = []
                async for chunk in gemini_service.chat_completion(
                    messages=[{"role": "user", "content": "Hello"}],
                    stream=False
                ):
                    results.append(chunk)

                assert len(results) == 1
                assert "API Error" in results[0]

    @pytest.mark.asyncio
    async def test_usage_metadata_extraction(self, gemini_service):
        """Test extraction of usage metadata from response"""
        mock_response = Mock()
        mock_candidate = Mock()
        mock_content = Mock()
        mock_part = Mock()
        mock_part.text = "Response text"
        mock_content.parts = [mock_part]
        mock_candidate.content = mock_content
        mock_response.candidates = [mock_candidate]

        mock_usage = Mock()
        mock_usage.prompt_token_count = 500
        mock_usage.cached_content_token_count = 200
        mock_usage.candidates_token_count = 300
        mock_usage.total_token_count = 1000
        mock_response.usage_metadata = mock_usage

        with patch.object(gemini_service, "model"):
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor.return_value = mock_response

                results = []
                async for chunk in gemini_service.chat_completion(
                    messages=[{"role": "user", "content": "Test"}],
                    stream=False
                ):
                    results.append(chunk)

                # Last chunk should contain usage metadata
                usage_chunk = results[-1]
                assert "__USAGE__" in usage_chunk

                import json
                usage_data = json.loads(usage_chunk.split("__USAGE__: ")[1])
                assert usage_data["prompt_tokens"] == 500
                assert usage_data["cached_tokens"] == 200
                assert usage_data["completion_tokens"] == 300
                assert usage_data["total_tokens"] == 1000
                assert usage_data["cache_hit"] is True
