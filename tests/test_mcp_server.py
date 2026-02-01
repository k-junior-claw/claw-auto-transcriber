"""
Tests for the MCP server module.

Tests:
- Server initialization
- Tool registration
- Tool invocation handling
- Error handling
- Server lifecycle
- State management

Note: These tests use mocks for external dependencies (audio processing, etc.)
"""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from mcp_server import (
    MCPTranscriptionServer,
    ServerState,
    TRANSCRIBE_AUDIO_TOOL,
    create_server,
    run_server,
)
from audio_processor import (
    ProcessedAudio,
    AudioMetadata,
    AudioValidationError,
    AudioConversionError,
    AudioDurationError,
    AudioSizeError,
    AudioFormatError,
    AudioProcessingError,
)
from config import Config


class TestServerState:
    """Tests for ServerState dataclass."""
    
    def test_default_values(self):
        """Test default state values."""
        state = ServerState(server_id="test-001")
        
        assert state.server_id == "test-001"
        assert state.active_connections == 0
        assert state.total_invocations == 0
        assert state.is_running is False
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        state = ServerState(
            server_id="test-001",
            total_invocations=10,
            successful_invocations=8,
            failed_invocations=2
        )
        state.is_running = True
        
        result = state.to_dict()
        
        assert result["server_id"] == "test-001"
        assert result["total_invocations"] == 10
        assert result["success_rate"] == 80.0
        assert "uptime_seconds" in result
    
    def test_success_rate_no_invocations(self):
        """Test success rate with no invocations."""
        state = ServerState(server_id="test")
        
        result = state.to_dict()
        
        assert result["success_rate"] == 0


class TestMCPTranscriptionServer:
    """Tests for MCPTranscriptionServer class."""
    
    @pytest.fixture
    def server(self):
        """Create a server instance for testing."""
        config = Config()
        config.load(validate_credentials=False)
        return MCPTranscriptionServer(config=config)
    
    def test_server_initialization(self, server):
        """Test server initializes correctly."""
        assert server.server is not None
        assert server.state is not None
        assert "claw-transcriber" in server.state.server_id
    
    def test_server_name_from_config(self, server):
        """Test server name comes from config."""
        assert server.server_name == "claw-auto-transcriber"
    
    def test_get_tools(self, server):
        """Test getting available tools."""
        tools = server._get_tools()
        
        assert len(tools) == 1
        assert tools[0].name == TRANSCRIBE_AUDIO_TOOL
        assert "transcribe" in tools[0].description.lower()
    
    def test_tool_schema(self, server):
        """Test tool schema is correct."""
        tools = server._get_tools()
        tool = tools[0]
        
        schema = tool.inputSchema
        
        assert schema["type"] == "object"
        assert "audio_data" in schema["properties"]
        assert "metadata" in schema["properties"]
        assert "audio_data" in schema["required"]


class TestToolInvocation:
    """Tests for tool invocation handling."""
    
    @pytest.fixture
    def server(self):
        """Create a server instance for testing."""
        config = Config()
        config.load(validate_credentials=False)
        return MCPTranscriptionServer(config=config)
    
    @pytest.fixture
    def mock_processed_audio(self):
        """Create a mock ProcessedAudio object."""
        return ProcessedAudio(
            flac_data=b"fLaC_test_data",
            metadata=AudioMetadata(
                format="ogg",
                duration_seconds=2.5,
                sample_rate=16000,
                channels=1,
                size_bytes=5000
            ),
            original_format="ogg"
        )
    
    @pytest.mark.asyncio
    async def test_handle_transcribe_audio_success(self, server, mock_processed_audio):
        """Test successful transcribe_audio invocation."""
        with patch.object(
            server.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": "dGVzdA=="}  # base64 "test"
            )
        
        assert len(result) == 1
        response = json.loads(result[0].text)
        assert response["status"] == "processed"
        assert response["metadata"]["audio_duration_seconds"] == 2.5
        assert server.state.successful_invocations == 1
    
    @pytest.mark.asyncio
    async def test_handle_transcribe_audio_missing_param(self, server):
        """Test invocation with missing audio_data parameter."""
        result = await server._handle_tool_call(
            TRANSCRIBE_AUDIO_TOOL,
            {}  # Missing audio_data
        )
        
        assert len(result) == 1
        assert "Missing required parameter" in result[0].text
        assert server.state.failed_invocations == 1
    
    @pytest.mark.asyncio
    async def test_handle_unknown_tool(self, server):
        """Test invocation of unknown tool."""
        result = await server._handle_tool_call(
            "unknown_tool",
            {"data": "test"}
        )
        
        assert len(result) == 1
        assert "unexpected error" in result[0].text.lower()
        assert server.state.failed_invocations == 1
    
    @pytest.mark.asyncio
    async def test_handle_validation_error(self, server):
        """Test handling AudioValidationError."""
        with patch.object(
            server.audio_processor,
            'process_audio',
            side_effect=AudioValidationError("Invalid audio format")
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": "dGVzdA=="}
            )
        
        assert "Invalid audio" in result[0].text
        assert server.state.failed_invocations == 1
    
    @pytest.mark.asyncio
    async def test_handle_duration_error(self, server):
        """Test handling AudioDurationError."""
        with patch.object(
            server.audio_processor,
            'process_audio',
            side_effect=AudioDurationError("Audio too long: 120s")
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": "dGVzdA=="}
            )
        
        assert "120s" in result[0].text or "too long" in result[0].text.lower()
        assert server.state.failed_invocations == 1
    
    @pytest.mark.asyncio
    async def test_handle_size_error(self, server):
        """Test handling AudioSizeError."""
        with patch.object(
            server.audio_processor,
            'process_audio',
            side_effect=AudioSizeError("File too large")
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": "dGVzdA=="}
            )
        
        assert "too large" in result[0].text.lower() or "size" in result[0].text.lower()
    
    @pytest.mark.asyncio
    async def test_handle_format_error(self, server):
        """Test handling AudioFormatError."""
        with patch.object(
            server.audio_processor,
            'process_audio',
            side_effect=AudioFormatError("Unsupported format")
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": "dGVzdA=="}
            )
        
        assert "Unsupported format" in result[0].text or "format" in result[0].text.lower()
    
    @pytest.mark.asyncio
    async def test_handle_conversion_error(self, server):
        """Test handling AudioConversionError."""
        with patch.object(
            server.audio_processor,
            'process_audio',
            side_effect=AudioConversionError("FFmpeg error")
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": "dGVzdA=="}
            )
        
        assert "Failed to process" in result[0].text
    
    @pytest.mark.asyncio
    async def test_handle_generic_processing_error(self, server):
        """Test handling generic AudioProcessingError."""
        with patch.object(
            server.audio_processor,
            'process_audio',
            side_effect=AudioProcessingError("Generic error")
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": "dGVzdA=="}
            )
        
        assert "processing failed" in result[0].text.lower()
    
    @pytest.mark.asyncio
    async def test_handle_unexpected_error(self, server):
        """Test handling unexpected exceptions."""
        with patch.object(
            server.audio_processor,
            'process_audio',
            side_effect=RuntimeError("Unexpected!")
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": "dGVzdA=="}
            )
        
        assert "unexpected error" in result[0].text.lower()
    
    @pytest.mark.asyncio
    async def test_invocation_with_metadata(self, server, mock_processed_audio):
        """Test invocation with metadata."""
        with patch.object(
            server.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {
                    "audio_data": "dGVzdA==",
                    "metadata": {
                        "original_format": "ogg",
                        "language_code": "es-ES",
                        "user_id": "user123"
                    }
                }
            )
        
        response = json.loads(result[0].text)
        assert response["metadata"]["language_code"] == "es-ES"


class TestServerLifecycle:
    """Tests for server lifecycle management."""
    
    @pytest.fixture
    def server(self):
        """Create a server instance for testing."""
        config = Config()
        config.load(validate_credentials=False)
        return MCPTranscriptionServer(config=config)
    
    @pytest.mark.asyncio
    async def test_start(self, server):
        """Test server start."""
        await server.start()
        
        assert server.state.is_running is True
    
    @pytest.mark.asyncio
    async def test_stop(self, server):
        """Test server stop."""
        server.state.is_running = True
        server._audio_processor = MagicMock()
        
        await server.stop()
        
        assert server.state.is_running is False
        server._audio_processor.cleanup.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_stop_without_processor(self, server):
        """Test stop when audio processor not initialized."""
        server.state.is_running = True
        server._audio_processor = None
        
        # Should not raise
        await server.stop()
        
        assert server.state.is_running is False


class TestCreateServer:
    """Tests for create_server factory function."""
    
    def test_create_server_default(self):
        """Test creating server with defaults."""
        server = create_server()
        
        assert server is not None
        assert isinstance(server, MCPTranscriptionServer)
    
    def test_create_server_with_config(self):
        """Test creating server with custom config."""
        config = Config()
        config.load(validate_credentials=False)
        config.mcp_server.name = "custom-server"
        
        server = create_server(config=config)
        
        assert server.server_name == "custom-server"


class TestStateTracking:
    """Tests for server state tracking."""
    
    @pytest.fixture
    def server(self):
        """Create a server instance for testing."""
        config = Config()
        config.load(validate_credentials=False)
        return MCPTranscriptionServer(config=config)
    
    @pytest.fixture
    def mock_processed_audio(self):
        """Create a mock ProcessedAudio object."""
        return ProcessedAudio(
            flac_data=b"fLaC_test_data",
            metadata=AudioMetadata(
                format="ogg",
                duration_seconds=2.0,
                sample_rate=16000,
                channels=1,
                size_bytes=4000
            ),
            original_format="ogg"
        )
    
    @pytest.mark.asyncio
    async def test_invocation_count_increments(self, server, mock_processed_audio):
        """Test that invocation count increments."""
        initial = server.state.total_invocations
        
        with patch.object(
            server.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ):
            await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": "dGVzdA=="}
            )
        
        assert server.state.total_invocations == initial + 1
    
    @pytest.mark.asyncio
    async def test_success_count_increments(self, server, mock_processed_audio):
        """Test that success count increments on success."""
        initial = server.state.successful_invocations
        
        with patch.object(
            server.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ):
            await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": "dGVzdA=="}
            )
        
        assert server.state.successful_invocations == initial + 1
    
    @pytest.mark.asyncio
    async def test_failure_count_increments(self, server):
        """Test that failure count increments on failure."""
        initial = server.state.failed_invocations
        
        with patch.object(
            server.audio_processor,
            'process_audio',
            side_effect=AudioValidationError("Error")
        ):
            await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": "dGVzdA=="}
            )
        
        assert server.state.failed_invocations == initial + 1


class TestToolSchema:
    """Tests for tool schema definition."""
    
    @pytest.fixture
    def server(self):
        """Create a server instance for testing."""
        config = Config()
        config.load(validate_credentials=False)
        return MCPTranscriptionServer(config=config)
    
    def test_transcribe_audio_schema_audio_data(self, server):
        """Test audio_data property in schema."""
        tools = server._get_tools()
        schema = tools[0].inputSchema
        
        audio_data = schema["properties"]["audio_data"]
        
        assert audio_data["type"] == "string"
        assert "base64" in audio_data["description"].lower()
    
    def test_transcribe_audio_schema_metadata(self, server):
        """Test metadata property in schema."""
        tools = server._get_tools()
        schema = tools[0].inputSchema
        
        metadata = schema["properties"]["metadata"]
        
        assert metadata["type"] == "object"
        assert "original_format" in metadata["properties"]
        assert "duration_seconds" in metadata["properties"]
        assert "language_code" in metadata["properties"]
    
    def test_transcribe_audio_schema_required(self, server):
        """Test required fields in schema."""
        tools = server._get_tools()
        schema = tools[0].inputSchema
        
        assert "audio_data" in schema["required"]
        assert "metadata" not in schema["required"]  # Optional


class TestPrivacyCompliance:
    """Tests to verify privacy requirements."""
    
    @pytest.fixture
    def server(self):
        """Create a server instance for testing."""
        config = Config()
        config.load(validate_credentials=False)
        return MCPTranscriptionServer(config=config)
    
    @pytest.fixture
    def mock_processed_audio(self):
        """Create a mock ProcessedAudio object."""
        return ProcessedAudio(
            flac_data=b"fLaC_sensitive_audio_data",
            metadata=AudioMetadata(
                format="ogg",
                duration_seconds=2.0,
                sample_rate=16000,
                channels=1,
                size_bytes=4000
            ),
            original_format="ogg"
        )
    
    @pytest.mark.asyncio
    async def test_response_does_not_include_audio(self, server, mock_processed_audio):
        """Test that response doesn't include raw audio data."""
        with patch.object(
            server.audio_processor,
            'process_audio',
            return_value=mock_processed_audio
        ):
            result = await server._handle_tool_call(
                TRANSCRIBE_AUDIO_TOOL,
                {"audio_data": "dGVzdA=="}
            )
        
        response_text = result[0].text
        
        # Should not contain the raw audio data
        assert "sensitive_audio_data" not in response_text
        assert "dGVzdA==" not in response_text  # Input base64
