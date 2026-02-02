"""
Tests for the logger module.

Tests:
- Structured logging (JSON and text formats)
- Sensitive data sanitization
- Performance timing
- Context management
- Tool invocation logging
"""

import json
import logging
import time
from unittest.mock import patch, MagicMock

import pytest

from src.logger import (
    MCPLogger,
    LogContext,
    PerformanceMetrics,
    sanitize_for_logging,
    get_logger,
    generate_invocation_id,
    generate_connection_id,
    timed,
    configure_root_logger,
    StructuredJsonFormatter,
    StructuredTextFormatter,
    SENSITIVE_FIELDS,
)
from src.config import LogLevel, LogFormat


class TestSanitizeForLogging:
    """Tests for the sanitize_for_logging function."""
    
    def test_sanitize_sensitive_dict_keys(self):
        """Test that sensitive keys are redacted."""
        data = {
            "audio_data": "base64encodedaudio",
            "transcription": "Hello world",
            "user_id": "user123",
            "password": "secret123",
        }
        
        result = sanitize_for_logging(data)
        
        assert result["audio_data"] == "<redacted>"
        assert result["transcription"] == "<redacted>"
        assert result["user_id"] == "user123"  # Not in sensitive list
        assert result["password"] == "<redacted>"
    
    def test_sanitize_nested_dict(self):
        """Test sanitization of nested dictionaries."""
        data = {
            "outer": {
                "audio_content": "sensitive",
                "normal": "value"
            }
        }
        
        result = sanitize_for_logging(data)
        
        assert result["outer"]["audio_content"] == "<redacted>"
        assert result["outer"]["normal"] == "value"
    
    def test_sanitize_list(self):
        """Test sanitization of lists."""
        data = [
            {"audio_data": "sensitive", "id": 1},
            {"audio_data": "also_sensitive", "id": 2}
        ]
        
        result = sanitize_for_logging(data)
        
        assert result[0]["audio_data"] == "<redacted>"
        assert result[0]["id"] == 1
        assert result[1]["audio_data"] == "<redacted>"
    
    def test_sanitize_bytes(self):
        """Test that bytes are replaced with size indicator."""
        data = {
            "content": b"some binary data"
        }
        
        result = sanitize_for_logging(data)
        
        assert "<bytes:" in result["content"]
    
    def test_sanitize_long_string(self):
        """Test that long strings are truncated."""
        data = {
            "content": "x" * 2000  # Long string that might be base64 audio
        }
        
        result = sanitize_for_logging(data)
        
        assert "<string:" in result["content"]
        assert "2000" in result["content"]
    
    def test_sanitize_max_depth(self):
        """Test max depth handling."""
        data = {"a": {"b": {"c": {"d": {"e": {"f": "deep"}}}}}}
        
        result = sanitize_for_logging(data, max_depth=3)
        
        # Should stop at some point and return max_depth_exceeded
        assert "<max_depth_exceeded>" in str(result)
    
    def test_sanitize_primitive_values(self):
        """Test that primitive values pass through."""
        assert sanitize_for_logging(42) == 42
        assert sanitize_for_logging("hello") == "hello"
        assert sanitize_for_logging(3.14) == 3.14
        assert sanitize_for_logging(True) is True
        assert sanitize_for_logging(None) is None


class TestLogContext:
    """Tests for LogContext."""
    
    def test_default_values(self):
        """Test default context values."""
        context = LogContext()
        
        assert context.component == "mcp_server"
        assert context.operation is None
        assert context.invocation_id is None
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        context = LogContext(
            component="audio_processor",
            operation="convert",
            invocation_id="inv_123",
            extra={"custom": "value"}
        )
        
        result = context.to_dict()
        
        assert result["component"] == "audio_processor"
        assert result["operation"] == "convert"
        assert result["invocation_id"] == "inv_123"
        assert result["custom"] == "value"
    
    def test_to_dict_excludes_none(self):
        """Test that None values are excluded."""
        context = LogContext(component="test")
        
        result = context.to_dict()
        
        assert "operation" not in result
        assert "invocation_id" not in result


class TestPerformanceMetrics:
    """Tests for PerformanceMetrics."""
    
    def test_timing(self):
        """Test performance timing."""
        metrics = PerformanceMetrics(operation="test_op")
        
        time.sleep(0.01)  # Small delay
        metrics.finish()
        
        assert metrics.duration_ms is not None
        assert metrics.duration_ms >= 10  # At least 10ms
        assert metrics.success is True
    
    def test_finish_with_error(self):
        """Test finishing with error."""
        metrics = PerformanceMetrics(operation="test_op")
        
        error = ValueError("Test error")
        metrics.finish(success=False, error=error)
        
        assert metrics.success is False
        assert metrics.error_type == "ValueError"
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        metrics = PerformanceMetrics(operation="test_op")
        metrics.finish()
        
        result = metrics.to_dict()
        
        assert result["operation"] == "test_op"
        assert "duration_ms" in result
        assert result["success"] is True


class TestStructuredJsonFormatter:
    """Tests for StructuredJsonFormatter."""
    
    def test_format_basic_message(self):
        """Test formatting a basic log message."""
        formatter = StructuredJsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        result = formatter.format(record)
        parsed = json.loads(result)
        
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "Test message"
        assert parsed["logger"] == "test"
        assert "timestamp" in parsed
    
    def test_format_with_exception(self):
        """Test formatting with exception info."""
        formatter = StructuredJsonFormatter()
        
        try:
            raise ValueError("Test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
        
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="Error occurred",
            args=(),
            exc_info=exc_info
        )
        
        result = formatter.format(record)
        parsed = json.loads(result)
        
        assert "exception" in parsed
        assert parsed["exception"]["type"] == "ValueError"
    
    def test_format_without_timestamp(self):
        """Test formatting without timestamp."""
        formatter = StructuredJsonFormatter(include_timestamp=False)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None
        )
        
        result = formatter.format(record)
        parsed = json.loads(result)
        
        assert "timestamp" not in parsed


class TestStructuredTextFormatter:
    """Tests for StructuredTextFormatter."""
    
    def test_format_basic_message(self):
        """Test formatting a basic log message."""
        formatter = StructuredTextFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        result = formatter.format(record)
        
        assert "[INFO]" in result
        assert "test" in result
        assert "Test message" in result


class TestMCPLogger:
    """Tests for MCPLogger."""
    
    def test_create_logger(self):
        """Test creating a logger."""
        logger = MCPLogger("test_component")
        
        assert logger.name == "test_component"
        assert logger.context.component == "test_component"
    
    def test_log_levels(self):
        """Test different log levels."""
        logger = MCPLogger("test", level=LogLevel.DEBUG)
        
        with patch.object(logger._logger, 'debug') as mock_debug:
            logger.debug("Debug message")
            mock_debug.assert_called_once()
        
        with patch.object(logger._logger, 'info') as mock_info:
            logger.info("Info message")
            mock_info.assert_called_once()
        
        with patch.object(logger._logger, 'warning') as mock_warning:
            logger.warning("Warning message")
            mock_warning.assert_called_once()
        
        with patch.object(logger._logger, 'error') as mock_error:
            logger.error("Error message")
            mock_error.assert_called_once()
    
    def test_timed_operation_success(self):
        """Test timed_operation context manager on success."""
        logger = MCPLogger("test")
        
        with patch.object(logger, 'info') as mock_info:
            with logger.timed_operation("test_op") as metrics:
                time.sleep(0.01)
            
            assert metrics.success is True
            assert metrics.duration_ms >= 10
            mock_info.assert_called()
    
    def test_timed_operation_failure(self):
        """Test timed_operation context manager on failure."""
        logger = MCPLogger("test")
        
        with patch.object(logger, 'warning') as mock_warning:
            with pytest.raises(ValueError):
                with logger.timed_operation("test_op") as metrics:
                    raise ValueError("Test error")
            
            assert metrics.success is False
            assert metrics.error_type == "ValueError"
            mock_warning.assert_called()
    
    def test_log_tool_invocation(self):
        """Test logging tool invocation."""
        logger = MCPLogger("test")
        
        with patch.object(logger, 'info') as mock_info:
            logger.log_tool_invocation(
                tool_name="transcribe_audio",
                invocation_id="inv_123",
                metadata={"audio_size": 1000}
            )
            
            mock_info.assert_called_once()
            call_kwargs = mock_info.call_args
            assert "tool_invoked" in str(call_kwargs)
    
    def test_log_tool_response(self):
        """Test logging tool response."""
        logger = MCPLogger("test")
        
        with patch.object(logger, 'info') as mock_info:
            logger.log_tool_response(
                tool_name="transcribe_audio",
                invocation_id="inv_123",
                success=True,
                duration_ms=150.5
            )
            
            mock_info.assert_called_once()
    
    def test_with_context(self):
        """Test creating logger with additional context."""
        logger = MCPLogger("test")
        
        new_logger = logger.with_context(
            operation="convert",
            invocation_id="inv_456"
        )
        
        assert new_logger.context.operation == "convert"
        assert new_logger.context.invocation_id == "inv_456"
        # Original logger should be unchanged
        assert logger.context.operation is None


class TestGetLogger:
    """Tests for get_logger function."""
    
    def test_get_logger_creates_instance(self):
        """Test get_logger creates an MCPLogger."""
        logger = get_logger("test_module")
        
        assert isinstance(logger, MCPLogger)
        assert logger.name == "test_module"
    
    def test_get_logger_with_context(self):
        """Test get_logger with context kwargs."""
        logger = get_logger("test_module", operation="process")
        
        assert logger.context.operation == "process"


class TestGenerateIds:
    """Tests for ID generation functions."""
    
    def test_generate_invocation_id(self):
        """Test invocation ID generation."""
        id1 = generate_invocation_id()
        id2 = generate_invocation_id()
        
        assert id1.startswith("inv_")
        assert id2.startswith("inv_")
        assert id1 != id2  # Should be unique
    
    def test_generate_connection_id(self):
        """Test connection ID generation."""
        id1 = generate_connection_id()
        id2 = generate_connection_id()
        
        assert id1.startswith("conn_")
        assert id2.startswith("conn_")
        assert id1 != id2


class TestTimedDecorator:
    """Tests for the @timed decorator."""
    
    def test_timed_sync_function(self):
        """Test timing a synchronous function."""
        @timed()
        def slow_function():
            time.sleep(0.01)
            return "done"
        
        result = slow_function()
        
        assert result == "done"
    
    @pytest.mark.asyncio
    async def test_timed_async_function(self):
        """Test timing an async function."""
        @timed()
        async def slow_async_function():
            import asyncio
            await asyncio.sleep(0.01)
            return "async_done"
        
        result = await slow_async_function()
        
        assert result == "async_done"


class TestConfigureRootLogger:
    """Tests for configure_root_logger function."""
    
    def test_configure_json_format(self):
        """Test configuring root logger with JSON format."""
        configure_root_logger(level=LogLevel.INFO, format=LogFormat.JSON)
        
        root = logging.getLogger("claw")
        assert root.level == logging.INFO
        assert len(root.handlers) > 0
    
    def test_configure_text_format(self):
        """Test configuring root logger with TEXT format."""
        configure_root_logger(level=LogLevel.DEBUG, format=LogFormat.TEXT)
        
        root = logging.getLogger("claw")
        assert root.level == logging.DEBUG


class TestSensitiveFieldsCoverage:
    """Tests to ensure all sensitive fields are properly handled."""
    
    def test_all_sensitive_fields_redacted(self):
        """Test that all fields in SENSITIVE_FIELDS are redacted."""
        # Create a dict with all sensitive fields
        data = {field: f"sensitive_{field}" for field in SENSITIVE_FIELDS}
        data["safe_field"] = "not_sensitive"
        
        result = sanitize_for_logging(data)
        
        for field in SENSITIVE_FIELDS:
            assert result[field] == "<redacted>", f"Field {field} was not redacted"
        
        assert result["safe_field"] == "not_sensitive"
