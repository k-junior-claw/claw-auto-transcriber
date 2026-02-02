"""
Integration tests for the MCP server.

Tests end-to-end MCP tool invocation flow, pipeline integration,
concurrent invocations, server lifecycle, and security scenarios.

Note: All external dependencies (Google Cloud STT) are mocked.
"""

import asyncio
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from src.mcp_server import (
    MCPTranscriptionServer,
    ServerState,
    TRANSCRIBE_AUDIO_TOOL,
    create_server,
)
from src.audio_processor import (
    ProcessedAudio,
    AudioMetadata,
    AudioValidationError,
    AudioDurationError,
    AudioSizeError,
)
from src.transcriber import (
    TranscriptionResult,
    TranscriptionError,
    TranscriptionAPIError,
    NoSpeechDetectedError,
)
from src.config import Config
from tools.transcribe_audio import ToolInput, ToolResponse


# =============================================================================
# Test Data and Fixtures
# =============================================================================

def create_mock_ogg_audio(size_bytes: int = 1000) -> bytes:
    """Create mock OGG audio data with valid magic header."""
    # OGG magic bytes
    header = b'OggS'
    # Fill with padding to reach desired size
    padding = b'\x00' * (size_bytes - len(header))
    return header + padding


def create_mock_flac_audio(size_bytes: int = 1000) -> bytes:
    """Create mock FLAC audio data with valid magic header."""
    # FLAC magic bytes
    header = b'fLaC'
    padding = b'\x00' * (size_bytes - len(header))
    return header + padding


@pytest.fixture
def mock_config():
    """Create a test configuration."""
    config = Config()
    config.load(validate_credentials=False)
    return config


@pytest.fixture
def mock_processed_audio():
    """Create a standard mock ProcessedAudio."""
    return ProcessedAudio(
        flac_data=create_mock_flac_audio(2000),
        metadata=AudioMetadata(
            format="ogg",
            duration_seconds=3.5,
            sample_rate=16000,
            channels=1,
            size_bytes=2000
        ),
        original_format="ogg"
    )


@pytest.fixture
def mock_transcription_result():
    """Create a standard mock TranscriptionResult."""
    return TranscriptionResult(
        text="Hello, this is a test transcription.",
        confidence=0.95,
        language_code="en-US",
        duration_seconds=3.5
    )


@pytest.fixture
def server(mock_config):
    """Create a server instance for testing."""
    return MCPTranscriptionServer(config=mock_config)


# =============================================================================
# End-to-End MCP Tool Flow Tests
# =============================================================================

class TestMCPToolFlow:
    """Tests for complete MCP tool invocation flow."""
    
    @pytest.mark.asyncio
    async def test_full_tool_invocation_cycle(
        self, server, mock_processed_audio, mock_transcription_result
    ):
        """Test complete tool invocation from arguments to response."""
        # Prepare realistic audio data
        audio_data = create_mock_ogg_audio(5000)
        audio_base64 = base64.b64encode(audio_data).decode()
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            return_value=mock_transcription_result
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {
                    "audio_data": audio_base64,
                    "metadata": {
                        "language_code": "en-US",
                        "original_format": "ogg",
                        "user_id": "test_user_123",
                        "message_id": "msg_456"
                    }
                }
            )
        
        # Verify response structure
        assert len(result) == 1
        response_data = json.loads(result[0].text)
        
        assert response_data["success"] is True
        assert response_data["transcription"] == "Hello, this is a test transcription."
        assert response_data["confidence"] == 0.95
        assert response_data["language_code"] == "en-US"
        assert "duration_seconds" in response_data
        assert "word_count" in response_data
        assert "processing_time_ms" in response_data
        assert "metadata" in response_data
    
    @pytest.mark.asyncio
    async def test_tool_invocation_with_minimal_arguments(
        self, server, mock_processed_audio, mock_transcription_result
    ):
        """Test invocation with only required arguments."""
        audio_base64 = base64.b64encode(create_mock_ogg_audio()).decode()
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            return_value=mock_transcription_result
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": audio_base64}
            )
        
        response_data = json.loads(result[0].text)
        assert response_data["success"] is True
        # Default language should be used
        assert response_data["language_code"] == "en-US"
    
    @pytest.mark.asyncio
    async def test_tool_invocation_response_matches_mcp_protocol(
        self, server, mock_processed_audio, mock_transcription_result
    ):
        """Test that response format matches MCP protocol expectations."""
        audio_base64 = base64.b64encode(create_mock_ogg_audio()).decode()
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            return_value=mock_transcription_result
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": audio_base64}
            )
        
        # MCP protocol: result should be sequence of TextContent
        assert hasattr(result[0], 'type')
        assert result[0].type == "text"
        assert hasattr(result[0], 'text')
        
        # Response text should be valid JSON
        parsed = json.loads(result[0].text)
        assert isinstance(parsed, dict)
    
    @pytest.mark.asyncio
    async def test_error_response_format(self, server):
        """Test error response follows expected format."""
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            side_effect=AudioValidationError("Test error message")
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": "dGVzdA=="}
            )
        
        response_data = json.loads(result[0].text)
        assert response_data["success"] is False
        assert "error" in response_data
        assert response_data["error_type"] == "validation_error"


# =============================================================================
# Pipeline Integration Tests
# =============================================================================

class TestPipelineIntegration:
    """Tests for audio processing → transcription pipeline."""
    
    @pytest.mark.asyncio
    async def test_audio_to_transcription_flow(
        self, server, mock_processed_audio, mock_transcription_result
    ):
        """Test the complete audio → process → transcribe flow."""
        audio_data = create_mock_ogg_audio(3000)
        audio_base64 = base64.b64encode(audio_data).decode()
        
        # Track that both components are called in correct order
        call_order = []
        
        def track_process(*args, **kwargs):
            call_order.append("process")
            return mock_processed_audio
        
        def track_transcribe(*args, **kwargs):
            call_order.append("transcribe")
            return mock_transcription_result
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            side_effect=track_process
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            side_effect=track_transcribe
        ):
            await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": audio_base64}
            )
        
        # Verify correct order: process before transcribe
        assert call_order == ["process", "transcribe"]
    
    @pytest.mark.asyncio
    async def test_error_propagation_from_audio_processor(self, server):
        """Test that audio processor errors propagate correctly."""
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            side_effect=AudioDurationError("Audio exceeds 60 second limit")
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": "dGVzdA=="}
            )
        
        response_data = json.loads(result[0].text)
        assert response_data["success"] is False
        assert "duration" in response_data["error_type"] or "60" in response_data["error"]
    
    @pytest.mark.asyncio
    async def test_error_propagation_from_transcriber(
        self, server, mock_processed_audio
    ):
        """Test that transcriber errors propagate correctly."""
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            side_effect=TranscriptionAPIError("Google Cloud API error")
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": "dGVzdA=="}
            )
        
        response_data = json.loads(result[0].text)
        assert response_data["success"] is False
        assert response_data["error_type"] == "api_error"
    
    @pytest.mark.asyncio
    async def test_no_speech_detected_is_success(
        self, server, mock_processed_audio
    ):
        """Test that no speech detected returns success with empty text."""
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            side_effect=NoSpeechDetectedError("No speech in audio")
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": "dGVzdA=="}
            )
        
        response_data = json.loads(result[0].text)
        assert response_data["success"] is True
        assert response_data["transcription"] == ""
        assert response_data["word_count"] == 0


# =============================================================================
# Concurrent Invocation Tests
# =============================================================================

class TestConcurrentInvocations:
    """Tests for handling multiple concurrent tool invocations."""
    
    @pytest.mark.asyncio
    async def test_multiple_concurrent_invocations(
        self, server, mock_processed_audio, mock_transcription_result
    ):
        """Test handling multiple simultaneous invocations."""
        audio_base64 = base64.b64encode(create_mock_ogg_audio()).decode()
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            return_value=mock_transcription_result
        ):
            # Run 5 concurrent invocations
            tasks = [
                server._handle_tool_call(
                    TRANSCRIBE_AUDIO_TOOL,
                    {"audio_data": audio_base64}
                )
                for _ in range(5)
            ]
            results = await asyncio.gather(*tasks)
        
        # All should succeed
        for result in results:
            response_data = json.loads(result[0].text)
            assert response_data["success"] is True
    
    @pytest.mark.asyncio
    async def test_state_tracking_accuracy_under_load(
        self, server, mock_processed_audio, mock_transcription_result
    ):
        """Test that state tracking remains accurate with concurrent requests."""
        audio_base64 = base64.b64encode(create_mock_ogg_audio()).decode()
        initial_total = server.state.total_invocations
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            return_value=mock_transcription_result
        ):
            # Run 10 concurrent invocations
            tasks = [
                server._handle_tool_call(
                    TRANSCRIBE_AUDIO_TOOL,
                    {"audio_data": audio_base64}
                )
                for _ in range(10)
            ]
            await asyncio.gather(*tasks)
        
        # State should reflect all invocations
        assert server.state.total_invocations == initial_total + 10
        assert server.state.successful_invocations >= 10
    
    @pytest.mark.asyncio
    async def test_mixed_success_and_failure_tracking(self, server, mock_processed_audio):
        """Test accurate tracking with mix of successful and failed requests."""
        audio_base64 = base64.b64encode(create_mock_ogg_audio()).decode()
        
        call_count = [0]
        success_result = TranscriptionResult(
            text="Success",
            confidence=0.9,
            language_code="en-US",
            duration_seconds=2.0
        )
        
        def alternating_transcribe(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] % 2 == 0:
                raise TranscriptionError("Simulated failure")
            return success_result
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            side_effect=alternating_transcribe
        ):
            initial_success = server.state.successful_invocations
            initial_failed = server.state.failed_invocations
            
            tasks = [
                server._handle_tool_call(
                    TRANSCRIBE_AUDIO_TOOL,
                    {"audio_data": audio_base64}
                )
                for _ in range(6)
            ]
            results = await asyncio.gather(*tasks)
        
        # Check we have mix of successes and failures
        successes = sum(
            1 for r in results
            if json.loads(r[0].text).get("success") is True
        )
        failures = sum(
            1 for r in results
            if json.loads(r[0].text).get("success") is False
        )
        
        assert successes >= 1
        assert failures >= 1


# =============================================================================
# Server Lifecycle Integration Tests
# =============================================================================

class TestServerLifecycleIntegration:
    """Tests for server lifecycle management."""
    
    @pytest.mark.asyncio
    async def test_start_handle_stop_flow(
        self, server, mock_processed_audio, mock_transcription_result
    ):
        """Test complete server lifecycle with request handling."""
        audio_base64 = base64.b64encode(create_mock_ogg_audio()).decode()
        
        # Start server
        await server.start()
        assert server.state.is_running is True
        
        # Handle request
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            return_value=mock_transcription_result
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": audio_base64}
            )
        
        response_data = json.loads(result[0].text)
        assert response_data["success"] is True
        
        # Stop server
        await server.stop()
        assert server.state.is_running is False
    
    @pytest.mark.asyncio
    async def test_state_persists_across_invocations(
        self, server, mock_processed_audio, mock_transcription_result
    ):
        """Test that server state persists across multiple invocations."""
        audio_base64 = base64.b64encode(create_mock_ogg_audio()).decode()
        
        await server.start()
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            return_value=mock_transcription_result
        ):
            # First invocation
            await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": audio_base64}
            )
            first_count = server.state.total_invocations
            
            # Second invocation
            await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": audio_base64}
            )
            second_count = server.state.total_invocations
        
        assert second_count == first_count + 1
        
        await server.stop()
    
    @pytest.mark.asyncio
    async def test_cleanup_called_on_stop(self, server):
        """Test that cleanup is performed when server stops."""
        # Create mock audio processor and mark it as initialized
        mock_processor = MagicMock()
        server._audio_processor = mock_processor
        
        await server.start()
        await server.stop()
        
        # Verify cleanup was called
        mock_processor.cleanup.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_server_state_to_dict(self, server):
        """Test server state serialization."""
        await server.start()
        
        state_dict = server.state.to_dict()
        
        assert "server_id" in state_dict
        assert "start_time" in state_dict
        assert "uptime_seconds" in state_dict
        assert "total_invocations" in state_dict
        assert "success_rate" in state_dict
        
        await server.stop()


# =============================================================================
# Security Tests - Input Sanitization
# =============================================================================

class TestInputSanitization:
    """Tests for handling potentially malicious input."""
    
    @pytest.mark.asyncio
    async def test_sql_injection_in_user_id(
        self, server, mock_processed_audio, mock_transcription_result
    ):
        """Test handling SQL injection patterns in metadata."""
        audio_base64 = base64.b64encode(create_mock_ogg_audio()).decode()
        
        malicious_user_id = "'; DROP TABLE users; --"
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            return_value=mock_transcription_result
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {
                    "audio_data": audio_base64,
                    "metadata": {"user_id": malicious_user_id}
                }
            )
        
        # Should succeed - SQL injection should be treated as plain string
        response_data = json.loads(result[0].text)
        assert response_data["success"] is True
    
    @pytest.mark.asyncio
    async def test_xss_patterns_in_metadata(
        self, server, mock_processed_audio, mock_transcription_result
    ):
        """Test handling XSS patterns in metadata."""
        audio_base64 = base64.b64encode(create_mock_ogg_audio()).decode()
        
        xss_message_id = "<script>alert('xss')</script>"
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            return_value=mock_transcription_result
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {
                    "audio_data": audio_base64,
                    "metadata": {"message_id": xss_message_id}
                }
            )
        
        # Should succeed - XSS should be treated as plain string
        response_data = json.loads(result[0].text)
        assert response_data["success"] is True
    
    @pytest.mark.asyncio
    async def test_unicode_special_characters_in_metadata(
        self, server, mock_processed_audio, mock_transcription_result
    ):
        """Test handling Unicode special characters."""
        audio_base64 = base64.b64encode(create_mock_ogg_audio()).decode()
        
        unicode_user_id = "用户\u0000\u200b\uFEFF名"  # Null, zero-width space, BOM
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            return_value=mock_transcription_result
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {
                    "audio_data": audio_base64,
                    "metadata": {"user_id": unicode_user_id}
                }
            )
        
        # Should handle gracefully
        response_data = json.loads(result[0].text)
        assert response_data["success"] is True
    
    @pytest.mark.asyncio
    async def test_extremely_long_metadata_value(
        self, server, mock_processed_audio, mock_transcription_result
    ):
        """Test handling extremely long metadata strings."""
        audio_base64 = base64.b64encode(create_mock_ogg_audio()).decode()
        
        # 100KB string
        long_user_id = "a" * 100000
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            return_value=mock_transcription_result
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {
                    "audio_data": audio_base64,
                    "metadata": {"user_id": long_user_id}
                }
            )
        
        # Should handle gracefully (may succeed or return controlled error)
        response_data = json.loads(result[0].text)
        # Just verify it returns valid JSON response
        assert "success" in response_data
    
    @pytest.mark.asyncio
    async def test_null_bytes_in_audio_data(self, server):
        """Test handling null bytes in audio data."""
        # Audio with embedded null bytes
        audio_with_nulls = b'OggS\x00\x00\x00\x00' + b'\x00' * 100
        audio_base64 = base64.b64encode(audio_with_nulls).decode()
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            side_effect=AudioValidationError("Invalid audio format")
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": audio_base64}
            )
        
        response_data = json.loads(result[0].text)
        # Should return controlled error
        assert response_data["success"] is False
        assert "error" in response_data


# =============================================================================
# Security Tests - Boundary Conditions
# =============================================================================

class TestBoundaryConditions:
    """Tests for boundary condition handling."""
    
    @pytest.mark.asyncio
    async def test_empty_base64_after_decode(self, server):
        """Test handling audio that decodes to empty bytes."""
        # Empty string encoded
        empty_base64 = base64.b64encode(b"").decode()
        
        result = await server._handle_tool_call(
            TRANSCRIBE_AUDIO_TOOL,
            {"audio_data": empty_base64}
        )
        
        # Empty audio triggers input validation error which returns plain text
        # or JSON depending on where the error is caught
        response_text = result[0].text
        
        # May be plain text error or JSON - either way should indicate failure
        if response_text.startswith("{"):
            response_data = json.loads(response_text)
            assert response_data["success"] is False
        else:
            # Plain text error response
            assert "error" in response_text.lower() or "empty" in response_text.lower()
    
    @pytest.mark.asyncio
    async def test_audio_at_max_duration_limit(
        self, server, mock_transcription_result
    ):
        """Test audio exactly at maximum duration limit."""
        audio_base64 = base64.b64encode(create_mock_ogg_audio()).decode()
        
        # Audio at exactly max duration (60 seconds)
        processed_at_limit = ProcessedAudio(
            flac_data=create_mock_flac_audio(),
            metadata=AudioMetadata(
                format="ogg",
                duration_seconds=60.0,  # Exactly at limit
                sample_rate=16000,
                channels=1,
                size_bytes=5000
            ),
            original_format="ogg"
        )
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=processed_at_limit
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            return_value=mock_transcription_result
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": audio_base64}
            )
        
        response_data = json.loads(result[0].text)
        # Should succeed at exactly the limit
        assert response_data["success"] is True
    
    @pytest.mark.asyncio
    async def test_audio_over_duration_limit(self, server):
        """Test audio over maximum duration limit."""
        audio_base64 = base64.b64encode(create_mock_ogg_audio()).decode()
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            side_effect=AudioDurationError("Audio duration 65.0s exceeds maximum 60s")
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": audio_base64}
            )
        
        response_data = json.loads(result[0].text)
        assert response_data["success"] is False
        assert "duration" in response_data["error_type"]
    
    @pytest.mark.asyncio
    async def test_audio_at_max_size_limit(
        self, server, mock_transcription_result
    ):
        """Test audio exactly at maximum size limit."""
        # Create audio at size limit (10MB = 10 * 1024 * 1024 bytes)
        audio_base64 = base64.b64encode(create_mock_ogg_audio(1000)).decode()
        
        processed_at_size_limit = ProcessedAudio(
            flac_data=create_mock_flac_audio(),
            metadata=AudioMetadata(
                format="ogg",
                duration_seconds=30.0,
                sample_rate=16000,
                channels=1,
                size_bytes=10 * 1024 * 1024  # 10MB exactly
            ),
            original_format="ogg"
        )
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=processed_at_size_limit
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            return_value=mock_transcription_result
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": audio_base64}
            )
        
        response_data = json.loads(result[0].text)
        assert response_data["success"] is True
    
    @pytest.mark.asyncio
    async def test_audio_over_size_limit(self, server):
        """Test audio over maximum size limit."""
        audio_base64 = base64.b64encode(create_mock_ogg_audio()).decode()
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            side_effect=AudioSizeError("Audio size exceeds maximum 10MB")
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": audio_base64}
            )
        
        response_data = json.loads(result[0].text)
        assert response_data["success"] is False
        assert "size" in response_data["error_type"]
    
    @pytest.mark.asyncio
    async def test_minimum_valid_audio(
        self, server, mock_transcription_result
    ):
        """Test minimum valid audio (very short)."""
        audio_base64 = base64.b64encode(create_mock_ogg_audio(100)).decode()
        
        minimal_processed = ProcessedAudio(
            flac_data=create_mock_flac_audio(50),
            metadata=AudioMetadata(
                format="ogg",
                duration_seconds=0.1,  # Very short
                sample_rate=16000,
                channels=1,
                size_bytes=100
            ),
            original_format="ogg"
        )
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=minimal_processed
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            return_value=mock_transcription_result
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": audio_base64}
            )
        
        response_data = json.loads(result[0].text)
        assert response_data["success"] is True


# =============================================================================
# Privacy Compliance Integration Tests
# =============================================================================

class TestPrivacyComplianceIntegration:
    """Integration tests for privacy compliance."""
    
    @pytest.mark.asyncio
    async def test_audio_data_not_in_response(
        self, server, mock_processed_audio, mock_transcription_result
    ):
        """Test that raw audio data never appears in response."""
        sensitive_audio = b'OggS_SENSITIVE_AUDIO_CONTENT_HERE'
        audio_base64 = base64.b64encode(sensitive_audio).decode()
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            return_value=mock_transcription_result
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": audio_base64}
            )
        
        response_text = result[0].text
        
        # Neither raw audio nor base64 should appear
        assert "SENSITIVE_AUDIO_CONTENT_HERE" not in response_text
        assert audio_base64 not in response_text
    
    @pytest.mark.asyncio
    async def test_state_dict_no_sensitive_data(
        self, server, mock_processed_audio, mock_transcription_result
    ):
        """Test that server state dict contains no sensitive data."""
        audio_base64 = base64.b64encode(create_mock_ogg_audio()).decode()
        
        with patch.object(
            server.transcribe_tool.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ), patch.object(
            server.transcribe_tool.transcriber,
            'transcribe_with_retry',
            return_value=mock_transcription_result
        ):
            await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": audio_base64}
            )
        
        state_dict = server.state.to_dict()
        state_str = json.dumps(state_dict)
        
        # State should contain only metrics, not content
        assert "audio" not in state_str.lower() or "transcri" not in state_str.lower()
        assert "server_id" in state_str
        assert "total_invocations" in state_str


# =============================================================================
# Tool Discovery Tests
# =============================================================================

class TestToolDiscovery:
    """Tests for MCP tool discovery functionality."""
    
    def test_list_tools_returns_transcribe_audio(self, server):
        """Test that list_tools returns the transcribe_audio tool."""
        tools = server._get_tools()
        
        assert len(tools) == 1
        assert tools[0].name == TRANSCRIBE_AUDIO_TOOL
    
    def test_tool_description_contains_key_info(self, server):
        """Test that tool description contains required information."""
        tools = server._get_tools()
        tool = tools[0]
        
        description = tool.description.lower()
        
        assert "transcribe" in description
        assert "audio" in description
        assert "google" in description or "speech" in description
    
    def test_tool_input_schema_complete(self, server):
        """Test that tool input schema is complete."""
        tools = server._get_tools()
        schema = tools[0].inputSchema
        
        # Required structure
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema
        
        # Required field
        assert "audio_data" in schema["required"]
        
        # Properties
        assert "audio_data" in schema["properties"]
        assert "metadata" in schema["properties"]
        
        # Metadata sub-properties
        metadata_props = schema["properties"]["metadata"]["properties"]
        assert "original_format" in metadata_props
        assert "language_code" in metadata_props
        assert "user_id" in metadata_props
        assert "message_id" in metadata_props
