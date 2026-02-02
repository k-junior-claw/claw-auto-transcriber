"""
Tests for the tools module.

Tests:
- Tool schema validation
- Input validation
- Tool execution (mocked)
- Response formatting
- Error scenarios
- No speech detected handling

Note: These tests use mocks for external dependencies (audio processing, transcription).
"""

import base64
import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from tools.transcribe_audio import (
    TranscribeAudioTool,
    ToolInput,
    ToolResponse,
    ToolInputError,
    ToolExecutionError,
    get_tool_schema,
    validate_tool_input,
    TOOL_NAME,
    TOOL_DESCRIPTION,
)
from src.audio_processor import (
    ProcessedAudio,
    AudioMetadata,
    AudioValidationError,
    AudioConversionError,
    AudioDurationError,
    AudioSizeError,
    AudioFormatError,
    AudioProcessingError,
)
from src.transcriber import (
    TranscriptionResult,
    TranscriptionError,
    TranscriptionAPIError,
    TranscriptionTimeoutError,
    TranscriptionQuotaError,
    NoSpeechDetectedError,
)
from src.config import Config


class TestToolConstants:
    """Tests for tool constants."""
    
    def test_tool_name(self):
        """Test tool name constant."""
        assert TOOL_NAME == "transcribe_audio"
    
    def test_tool_description(self):
        """Test tool description contains key information."""
        assert "Transcribe" in TOOL_DESCRIPTION
        assert "audio" in TOOL_DESCRIPTION.lower()
        assert "Google Cloud" in TOOL_DESCRIPTION


class TestToolInput:
    """Tests for ToolInput dataclass."""
    
    def test_create_with_required_only(self):
        """Test creating ToolInput with only required fields."""
        tool_input = ToolInput(
            audio_data="dGVzdA==",
            language_code="en-US"
        )
        
        assert tool_input.audio_data == "dGVzdA=="
        assert tool_input.language_code == "en-US"
        assert tool_input.original_format is None
        assert tool_input.user_id is None
        assert tool_input.message_id is None
    
    def test_create_with_all_fields(self):
        """Test creating ToolInput with all fields."""
        tool_input = ToolInput(
            audio_data="dGVzdA==",
            language_code="es-ES",
            original_format="ogg",
            user_id="user123",
            message_id="msg456"
        )
        
        assert tool_input.audio_data == "dGVzdA=="
        assert tool_input.language_code == "es-ES"
        assert tool_input.original_format == "ogg"
        assert tool_input.user_id == "user123"
        assert tool_input.message_id == "msg456"
    
    def test_to_dict_excludes_audio_content(self):
        """Test that to_dict doesn't include actual audio content."""
        tool_input = ToolInput(
            audio_data="SENSITIVE_AUDIO_DATA_BASE64",
            language_code="en-US"
        )
        
        result = tool_input.to_dict()
        
        assert "SENSITIVE_AUDIO_DATA_BASE64" not in str(result)
        assert "audio_data_length" in result
        assert result["audio_data_length"] == len("SENSITIVE_AUDIO_DATA_BASE64")


class TestToolResponse:
    """Tests for ToolResponse dataclass."""
    
    def test_create_success_response(self):
        """Test creating a success response."""
        response = ToolResponse(
            success=True,
            transcription="Hello world",
            confidence=0.95,
            language_code="en-US",
            duration_seconds=2.5,
            word_count=2,
            processing_time_ms=1234.5
        )
        
        assert response.success is True
        assert response.transcription == "Hello world"
        assert response.confidence == 0.95
        assert response.error is None
    
    def test_create_error_response(self):
        """Test creating an error response."""
        response = ToolResponse(
            success=False,
            language_code="en-US",
            error="Audio format not supported",
            error_type="format_error"
        )
        
        assert response.success is False
        assert response.transcription is None
        assert response.error == "Audio format not supported"
        assert response.error_type == "format_error"
    
    def test_to_dict_success(self):
        """Test to_dict for success response."""
        response = ToolResponse(
            success=True,
            transcription="Test transcription",
            confidence=0.9123456,
            language_code="en-US",
            duration_seconds=3.456789,
            word_count=2,
            processing_time_ms=1500.123,
            invocation_id="inv_123",
            original_format="ogg"
        )
        
        result = response.to_dict()
        
        assert result["success"] is True
        assert result["transcription"] == "Test transcription"
        assert result["confidence"] == 0.912  # Rounded to 3 decimal places
        assert result["duration_seconds"] == 3.46  # Rounded to 2 decimal places
        assert result["metadata"]["invocation_id"] == "inv_123"
        assert "error" not in result  # No error field for success
    
    def test_to_dict_error(self):
        """Test to_dict for error response."""
        response = ToolResponse(
            success=False,
            language_code="en-US",
            processing_time_ms=100.5,
            error="Something went wrong",
            error_type="internal_error"
        )
        
        result = response.to_dict()
        
        assert result["success"] is False
        assert result["error"] == "Something went wrong"
        assert result["error_type"] == "internal_error"
        assert result["transcription"] is None
    
    def test_to_log_dict_excludes_transcription(self):
        """Test that to_log_dict doesn't include transcription text."""
        response = ToolResponse(
            success=True,
            transcription="SENSITIVE_TRANSCRIPTION_TEXT",
            confidence=0.95,
            language_code="en-US",
            duration_seconds=2.5,
            word_count=3,
            processing_time_ms=1500
        )
        
        result = response.to_log_dict()
        
        assert "SENSITIVE_TRANSCRIPTION_TEXT" not in str(result)
        assert "transcription" not in result
        assert result["word_count"] == 3


class TestGetToolSchema:
    """Tests for get_tool_schema function."""
    
    def test_schema_has_required_fields(self):
        """Test schema contains all required fields."""
        schema = get_tool_schema()
        
        assert schema["name"] == TOOL_NAME
        assert "description" in schema
        assert "inputSchema" in schema
    
    def test_schema_input_properties(self):
        """Test input schema has correct properties."""
        schema = get_tool_schema()
        input_schema = schema["inputSchema"]
        
        assert input_schema["type"] == "object"
        assert "audio_data" in input_schema["properties"]
        assert "metadata" in input_schema["properties"]
        assert "audio_data" in input_schema["required"]
    
    def test_schema_audio_data_property(self):
        """Test audio_data property definition."""
        schema = get_tool_schema()
        audio_data = schema["inputSchema"]["properties"]["audio_data"]
        
        assert audio_data["type"] == "string"
        assert "description" in audio_data
        assert "base64" in audio_data["description"].lower()
    
    def test_schema_metadata_property(self):
        """Test metadata property definition."""
        schema = get_tool_schema()
        metadata = schema["inputSchema"]["properties"]["metadata"]
        
        assert metadata["type"] == "object"
        assert "original_format" in metadata["properties"]
        assert "language_code" in metadata["properties"]
        assert "user_id" in metadata["properties"]
        assert "message_id" in metadata["properties"]
    
    def test_schema_format_enum(self):
        """Test format enum values."""
        schema = get_tool_schema()
        format_prop = schema["inputSchema"]["properties"]["metadata"]["properties"]["original_format"]
        
        assert "enum" in format_prop
        assert "ogg" in format_prop["enum"]
        assert "mp3" in format_prop["enum"]
        assert "wav" in format_prop["enum"]
        assert "flac" in format_prop["enum"]


class TestTranscribeAudioTool:
    """Tests for TranscribeAudioTool class."""
    
    @pytest.fixture
    def tool(self):
        """Create a tool instance with mocked dependencies."""
        config = Config()
        config.load(validate_credentials=False)
        return TranscribeAudioTool(config=config)
    
    @pytest.fixture
    def valid_audio_base64(self):
        """Provide valid base64-encoded test data."""
        return base64.b64encode(b"OggS" + b"\x00" * 100).decode()
    
    @pytest.fixture
    def mock_processed_audio(self):
        """Create mock ProcessedAudio."""
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
    
    @pytest.fixture
    def mock_transcription_result(self):
        """Create mock TranscriptionResult."""
        return TranscriptionResult(
            text="Hello world",
            confidence=0.95,
            language_code="en-US",
            duration_seconds=2.5
        )
    
    def test_get_schema_static_method(self):
        """Test get_schema static method."""
        schema = TranscribeAudioTool.get_schema()
        
        assert schema["name"] == TOOL_NAME
        assert "inputSchema" in schema


class TestToolInputValidation:
    """Tests for input validation."""
    
    @pytest.fixture
    def tool(self):
        """Create a tool instance."""
        config = Config()
        config.load(validate_credentials=False)
        return TranscribeAudioTool(config=config)
    
    @pytest.fixture
    def valid_audio_base64(self):
        """Provide valid base64-encoded test data."""
        return base64.b64encode(b"test_audio_data").decode()
    
    def test_validate_valid_input(self, tool, valid_audio_base64):
        """Test validation of valid input."""
        arguments = {
            "audio_data": valid_audio_base64,
            "metadata": {
                "language_code": "es-ES",
                "original_format": "ogg"
            }
        }
        
        result = tool.validate_input(arguments)
        
        assert isinstance(result, ToolInput)
        assert result.audio_data == valid_audio_base64
        assert result.language_code == "es-ES"
        assert result.original_format == "ogg"
    
    def test_validate_missing_audio_data(self, tool):
        """Test validation fails without audio_data."""
        with pytest.raises(ToolInputError) as exc_info:
            tool.validate_input({})
        
        assert "audio_data" in str(exc_info.value)
    
    def test_validate_empty_audio_data(self, tool):
        """Test validation fails with empty audio_data."""
        with pytest.raises(ToolInputError) as exc_info:
            tool.validate_input({"audio_data": ""})
        
        assert "empty" in str(exc_info.value).lower()
    
    def test_validate_whitespace_audio_data(self, tool):
        """Test validation fails with whitespace-only audio_data."""
        with pytest.raises(ToolInputError) as exc_info:
            tool.validate_input({"audio_data": "   "})
        
        assert "empty" in str(exc_info.value).lower()
    
    def test_validate_invalid_base64(self, tool):
        """Test validation fails with invalid base64."""
        with pytest.raises(ToolInputError) as exc_info:
            tool.validate_input({"audio_data": "not-valid-base64!!!"})
        
        assert "base64" in str(exc_info.value).lower()
    
    def test_validate_non_string_audio_data(self, tool):
        """Test validation fails with non-string audio_data."""
        with pytest.raises(ToolInputError) as exc_info:
            tool.validate_input({"audio_data": 12345})
        
        assert "string" in str(exc_info.value).lower()
    
    def test_validate_default_language_code(self, tool, valid_audio_base64):
        """Test default language code is used when not provided."""
        result = tool.validate_input({"audio_data": valid_audio_base64})
        
        assert result.language_code == "en-US"  # Default from config
    
    def test_validate_invalid_metadata_type(self, tool, valid_audio_base64):
        """Test validation handles invalid metadata type gracefully."""
        result = tool.validate_input({
            "audio_data": valid_audio_base64,
            "metadata": "invalid"
        })
        
        # Should use defaults when metadata is invalid
        assert result.language_code == "en-US"
        assert result.original_format is None


class TestToolExecution:
    """Tests for tool execution."""
    
    @pytest.fixture
    def mock_audio_processor(self):
        """Create a mock AudioProcessor."""
        mock = MagicMock()
        mock.process_audio.return_value = ProcessedAudio(
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
        return mock
    
    @pytest.fixture
    def mock_transcriber(self):
        """Create a mock Transcriber."""
        mock = MagicMock()
        mock.transcribe_with_retry.return_value = TranscriptionResult(
            text="Hello world",
            confidence=0.95,
            language_code="en-US",
            duration_seconds=2.5
        )
        return mock
    
    @pytest.fixture
    def tool_with_mocks(self, mock_audio_processor, mock_transcriber):
        """Create a tool with mocked dependencies."""
        config = Config()
        config.load(validate_credentials=False)
        return TranscribeAudioTool(
            config=config,
            audio_processor=mock_audio_processor,
            transcriber=mock_transcriber
        )
    
    @pytest.fixture
    def valid_input(self):
        """Create valid tool input."""
        return ToolInput(
            audio_data=base64.b64encode(b"test").decode(),
            language_code="en-US"
        )
    
    def test_execute_success(self, tool_with_mocks, valid_input):
        """Test successful execution."""
        response = tool_with_mocks.execute(valid_input, invocation_id="inv_123")
        
        assert response.success is True
        assert response.transcription == "Hello world"
        assert response.confidence == 0.95
        assert response.word_count == 2
        assert response.invocation_id == "inv_123"
        assert response.processing_time_ms > 0
    
    def test_execute_calls_audio_processor(self, tool_with_mocks, valid_input, mock_audio_processor):
        """Test that execute calls audio processor."""
        tool_with_mocks.execute(valid_input)
        
        mock_audio_processor.process_audio.assert_called_once()
    
    def test_execute_calls_transcriber(self, tool_with_mocks, valid_input, mock_transcriber):
        """Test that execute calls transcriber."""
        tool_with_mocks.execute(valid_input)
        
        mock_transcriber.transcribe_with_retry.assert_called_once()
    
    def test_execute_passes_language_code(self, tool_with_mocks, mock_transcriber):
        """Test that language code is passed to transcriber."""
        tool_input = ToolInput(
            audio_data=base64.b64encode(b"test").decode(),
            language_code="es-ES"
        )
        
        tool_with_mocks.execute(tool_input)
        
        call_kwargs = mock_transcriber.transcribe_with_retry.call_args[1]
        assert call_kwargs["language_code"] == "es-ES"


class TestToolExecutionErrors:
    """Tests for tool execution error handling."""
    
    @pytest.fixture
    def mock_audio_processor(self):
        """Create a mock AudioProcessor."""
        return MagicMock()
    
    @pytest.fixture
    def mock_transcriber(self):
        """Create a mock Transcriber."""
        return MagicMock()
    
    @pytest.fixture
    def tool_with_mocks(self, mock_audio_processor, mock_transcriber):
        """Create a tool with mocked dependencies."""
        config = Config()
        config.load(validate_credentials=False)
        return TranscribeAudioTool(
            config=config,
            audio_processor=mock_audio_processor,
            transcriber=mock_transcriber
        )
    
    @pytest.fixture
    def valid_input(self):
        """Create valid tool input."""
        return ToolInput(
            audio_data=base64.b64encode(b"test").decode(),
            language_code="en-US"
        )
    
    def test_handle_audio_validation_error(self, tool_with_mocks, valid_input, mock_audio_processor):
        """Test handling AudioValidationError."""
        mock_audio_processor.process_audio.side_effect = AudioValidationError("Invalid audio")
        
        response = tool_with_mocks.execute(valid_input)
        
        assert response.success is False
        assert response.error_type == "validation_error"
        assert "Invalid audio" in response.error
    
    def test_handle_audio_duration_error(self, tool_with_mocks, valid_input, mock_audio_processor):
        """Test handling AudioDurationError."""
        mock_audio_processor.process_audio.side_effect = AudioDurationError("Audio too long")
        
        response = tool_with_mocks.execute(valid_input)
        
        assert response.success is False
        assert response.error_type == "duration_error"
    
    def test_handle_audio_size_error(self, tool_with_mocks, valid_input, mock_audio_processor):
        """Test handling AudioSizeError."""
        mock_audio_processor.process_audio.side_effect = AudioSizeError("File too large")
        
        response = tool_with_mocks.execute(valid_input)
        
        assert response.success is False
        assert response.error_type == "size_error"
    
    def test_handle_audio_format_error(self, tool_with_mocks, valid_input, mock_audio_processor):
        """Test handling AudioFormatError."""
        mock_audio_processor.process_audio.side_effect = AudioFormatError("Unsupported format")
        
        response = tool_with_mocks.execute(valid_input)
        
        assert response.success is False
        assert response.error_type == "format_error"
    
    def test_handle_audio_conversion_error(self, tool_with_mocks, valid_input, mock_audio_processor):
        """Test handling AudioConversionError."""
        mock_audio_processor.process_audio.side_effect = AudioConversionError("FFmpeg error")
        
        response = tool_with_mocks.execute(valid_input)
        
        assert response.success is False
        assert response.error_type == "conversion_error"
        assert "process" in response.error.lower()
    
    def test_handle_transcription_timeout_error(self, tool_with_mocks, valid_input, mock_audio_processor, mock_transcriber):
        """Test handling TranscriptionTimeoutError."""
        mock_audio_processor.process_audio.return_value = ProcessedAudio(
            flac_data=b"fLaC_test",
            metadata=AudioMetadata("ogg", 2.0, 16000, 1, 1000),
            original_format="ogg"
        )
        mock_transcriber.transcribe_with_retry.side_effect = TranscriptionTimeoutError("Timeout")
        
        response = tool_with_mocks.execute(valid_input)
        
        assert response.success is False
        assert response.error_type == "timeout_error"
        assert "timed out" in response.error.lower()
    
    def test_handle_transcription_quota_error(self, tool_with_mocks, valid_input, mock_audio_processor, mock_transcriber):
        """Test handling TranscriptionQuotaError."""
        mock_audio_processor.process_audio.return_value = ProcessedAudio(
            flac_data=b"fLaC_test",
            metadata=AudioMetadata("ogg", 2.0, 16000, 1, 1000),
            original_format="ogg"
        )
        mock_transcriber.transcribe_with_retry.side_effect = TranscriptionQuotaError("Quota exceeded")
        
        response = tool_with_mocks.execute(valid_input)
        
        assert response.success is False
        assert response.error_type == "quota_error"
        assert "quota" in response.error.lower()
    
    def test_handle_transcription_api_error(self, tool_with_mocks, valid_input, mock_audio_processor, mock_transcriber):
        """Test handling TranscriptionAPIError."""
        mock_audio_processor.process_audio.return_value = ProcessedAudio(
            flac_data=b"fLaC_test",
            metadata=AudioMetadata("ogg", 2.0, 16000, 1, 1000),
            original_format="ogg"
        )
        mock_transcriber.transcribe_with_retry.side_effect = TranscriptionAPIError("API error")
        
        response = tool_with_mocks.execute(valid_input)
        
        assert response.success is False
        assert response.error_type == "api_error"
    
    def test_handle_unexpected_error(self, tool_with_mocks, valid_input, mock_audio_processor):
        """Test handling unexpected exceptions."""
        mock_audio_processor.process_audio.side_effect = RuntimeError("Unexpected!")
        
        response = tool_with_mocks.execute(valid_input)
        
        assert response.success is False
        assert response.error_type == "internal_error"
        assert "unexpected" in response.error.lower()


class TestNoSpeechDetected:
    """Tests for no speech detected handling."""
    
    @pytest.fixture
    def mock_audio_processor(self):
        """Create a mock AudioProcessor."""
        mock = MagicMock()
        mock.process_audio.return_value = ProcessedAudio(
            flac_data=b"fLaC_test",
            metadata=AudioMetadata("ogg", 2.0, 16000, 1, 1000),
            original_format="ogg"
        )
        return mock
    
    @pytest.fixture
    def mock_transcriber(self):
        """Create a mock Transcriber that raises NoSpeechDetectedError."""
        mock = MagicMock()
        mock.transcribe_with_retry.side_effect = NoSpeechDetectedError("No speech")
        return mock
    
    @pytest.fixture
    def tool_with_mocks(self, mock_audio_processor, mock_transcriber):
        """Create a tool with mocked dependencies."""
        config = Config()
        config.load(validate_credentials=False)
        return TranscribeAudioTool(
            config=config,
            audio_processor=mock_audio_processor,
            transcriber=mock_transcriber
        )
    
    @pytest.fixture
    def valid_input(self):
        """Create valid tool input."""
        return ToolInput(
            audio_data=base64.b64encode(b"test").decode(),
            language_code="en-US"
        )
    
    def test_no_speech_is_success(self, tool_with_mocks, valid_input):
        """Test that no speech detected is treated as success."""
        response = tool_with_mocks.execute(valid_input)
        
        assert response.success is True
        assert response.error is None
    
    def test_no_speech_returns_empty_transcription(self, tool_with_mocks, valid_input):
        """Test that no speech returns empty transcription."""
        response = tool_with_mocks.execute(valid_input)
        
        assert response.transcription == ""
        assert response.word_count == 0
        assert response.confidence == 0.0


class TestModuleFunctions:
    """Tests for module-level convenience functions."""
    
    def test_validate_tool_input_valid(self):
        """Test validate_tool_input with valid input."""
        audio_data = base64.b64encode(b"test").decode()
        
        result = validate_tool_input({"audio_data": audio_data})
        
        assert isinstance(result, ToolInput)
    
    def test_validate_tool_input_invalid(self):
        """Test validate_tool_input with invalid input."""
        with pytest.raises(ToolInputError):
            validate_tool_input({})


class TestPrivacyCompliance:
    """Tests to verify privacy requirements."""
    
    @pytest.fixture
    def tool(self):
        """Create a tool instance."""
        config = Config()
        config.load(validate_credentials=False)
        return TranscribeAudioTool(config=config)
    
    def test_tool_input_to_dict_no_audio(self):
        """Test ToolInput.to_dict doesn't expose audio."""
        tool_input = ToolInput(
            audio_data="SUPER_SECRET_AUDIO_BASE64",
            language_code="en-US"
        )
        
        result = tool_input.to_dict()
        result_str = json.dumps(result)
        
        assert "SUPER_SECRET_AUDIO_BASE64" not in result_str
    
    def test_tool_response_to_log_dict_no_transcription(self):
        """Test ToolResponse.to_log_dict doesn't expose transcription."""
        response = ToolResponse(
            success=True,
            transcription="PRIVATE_USER_SPEECH_CONTENT",
            confidence=0.95,
            language_code="en-US",
            duration_seconds=2.0,
            word_count=3,
            processing_time_ms=1000
        )
        
        result = response.to_log_dict()
        result_str = json.dumps(result)
        
        assert "PRIVATE_USER_SPEECH_CONTENT" not in result_str


class TestToolIntegration:
    """Integration tests for the tool with mocked MCP server components."""
    
    @pytest.fixture
    def mock_audio_processor(self):
        """Create a mock AudioProcessor."""
        mock = MagicMock()
        mock.process_audio.return_value = ProcessedAudio(
            flac_data=b"fLaC_test_data",
            metadata=AudioMetadata(
                format="ogg",
                duration_seconds=3.5,
                sample_rate=16000,
                channels=1,
                size_bytes=8000
            ),
            original_format="ogg"
        )
        return mock
    
    @pytest.fixture
    def mock_transcriber(self):
        """Create a mock Transcriber."""
        mock = MagicMock()
        mock.transcribe_with_retry.return_value = TranscriptionResult(
            text="What is the weather today?",
            confidence=0.92,
            language_code="en-US",
            duration_seconds=3.5
        )
        return mock
    
    @pytest.fixture
    def tool(self, mock_audio_processor, mock_transcriber):
        """Create a tool with mocked dependencies."""
        config = Config()
        config.load(validate_credentials=False)
        return TranscribeAudioTool(
            config=config,
            audio_processor=mock_audio_processor,
            transcriber=mock_transcriber
        )
    
    def test_full_flow(self, tool):
        """Test the full validation → execution → response flow."""
        # Create raw arguments like MCP server would receive
        audio_base64 = base64.b64encode(b"OggS" + b"\x00" * 100).decode()
        arguments = {
            "audio_data": audio_base64,
            "metadata": {
                "language_code": "en-US",
                "original_format": "ogg",
                "user_id": "user123"
            }
        }
        
        # Validate
        tool_input = tool.validate_input(arguments)
        assert tool_input.language_code == "en-US"
        assert tool_input.user_id == "user123"
        
        # Execute
        response = tool.execute(tool_input, invocation_id="inv_test")
        
        # Verify response
        assert response.success is True
        assert response.transcription == "What is the weather today?"
        assert response.confidence == 0.92
        assert response.word_count == 5
        
        # Verify response can be serialized
        result_dict = response.to_dict()
        assert json.dumps(result_dict)  # Should not raise
        
        # Verify log dict doesn't contain transcription
        log_dict = response.to_log_dict()
        assert "What is the weather today?" not in str(log_dict)
