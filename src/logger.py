"""
Logger Module for Claw Auto-Transcriber MCP Server.

Provides:
- Structured logging (JSON format for production)
- Performance timing utilities
- Context-aware logging
- Privacy-preserving logging (NO audio content logged)

CRITICAL: This logger is designed to NEVER log audio content or transcription text.
Only metadata is logged for debugging and monitoring purposes.
"""

import logging
import json
import time
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional, Any, Dict, Callable
from functools import wraps
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict

from src.config import LogLevel, LogFormat, get_config


# Privacy-sensitive fields that should NEVER be logged
SENSITIVE_FIELDS = frozenset({
    "audio_data",
    "audio_bytes", 
    "audio_content",
    "transcription",
    "transcription_text",
    "transcript",
    "text_content",
    "speech_content",
    "raw_audio",
    "flac_data",
    "ogg_data",
    "private_key",
    "api_key",
    "credentials",
    "password",
    "secret",
    "token",
})


@dataclass
class LogContext:
    """Context information for log entries."""
    component: str = "mcp_server"
    operation: Optional[str] = None
    invocation_id: Optional[str] = None
    connection_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        result = {
            "component": self.component,
        }
        if self.operation:
            result["operation"] = self.operation
        if self.invocation_id:
            result["invocation_id"] = self.invocation_id
        if self.connection_id:
            result["connection_id"] = self.connection_id
        if self.extra:
            result.update(self.extra)
        return result


@dataclass
class PerformanceMetrics:
    """Performance timing metrics."""
    operation: str
    start_time: float = field(default_factory=time.perf_counter)
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    success: bool = True
    error_type: Optional[str] = None
    
    def finish(self, success: bool = True, error: Optional[Exception] = None) -> "PerformanceMetrics":
        """Mark the operation as finished and calculate duration."""
        self.end_time = time.perf_counter()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.success = success
        if error:
            self.error_type = type(error).__name__
        return self
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "operation": self.operation,
            "duration_ms": round(self.duration_ms, 2) if self.duration_ms else None,
            "success": self.success,
            "error_type": self.error_type,
        }


def sanitize_for_logging(data: Any, max_depth: int = 5) -> Any:
    """
    Sanitize data for logging by removing sensitive fields.
    
    Args:
        data: Data to sanitize (dict, list, or other)
        max_depth: Maximum recursion depth
    
    Returns:
        Sanitized data safe for logging
    """
    if max_depth <= 0:
        return "<max_depth_exceeded>"
    
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            key_lower = key.lower()
            if any(sensitive in key_lower for sensitive in SENSITIVE_FIELDS):
                result[key] = "<redacted>"
            else:
                result[key] = sanitize_for_logging(value, max_depth - 1)
        return result
    
    elif isinstance(data, (list, tuple)):
        return [sanitize_for_logging(item, max_depth - 1) for item in data]
    
    elif isinstance(data, bytes):
        # Never log raw bytes - could be audio data
        return f"<bytes:{len(data)}>"
    
    elif isinstance(data, str) and len(data) > 1000:
        # Truncate long strings - could be base64 audio
        return f"<string:{len(data)}_chars>"
    
    return data


class StructuredJsonFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.
    
    Produces log entries in JSON format suitable for log aggregation
    and analysis tools.
    """
    
    def __init__(self, include_timestamp: bool = True):
        """Initialize the formatter."""
        super().__init__()
        self.include_timestamp = include_timestamp
    
    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON."""
        log_entry = {
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        
        if self.include_timestamp:
            log_entry["timestamp"] = datetime.now(timezone.utc).isoformat()
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
            }
        
        # Add extra fields from record
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "message", "taskName"
            }:
                extra_fields[key] = value
        
        if extra_fields:
            # Sanitize extra fields before logging
            log_entry["metadata"] = sanitize_for_logging(extra_fields)
        
        return json.dumps(log_entry)


class StructuredTextFormatter(logging.Formatter):
    """
    Human-readable text formatter for development.
    
    Produces log entries in a readable format while still including
    structured metadata.
    """
    
    def __init__(self):
        """Initialize the formatter."""
        super().__init__(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    
    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as text."""
        base_message = super().format(record)
        
        # Add extra fields if present
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "message", "asctime", "taskName"
            }:
                extra_fields[key] = value
        
        if extra_fields:
            sanitized = sanitize_for_logging(extra_fields)
            extra_str = " | " + " ".join(f"{k}={v}" for k, v in sanitized.items())
            return base_message + extra_str
        
        return base_message


class MCPLogger:
    """
    Main logger class for the MCP Server.
    
    Provides a consistent interface for logging across all modules
    with built-in privacy protection and performance tracking.
    
    Usage:
        logger = MCPLogger("audio_processor")
        logger.info("Processing audio", audio_size=45000, format="ogg")
        
        with logger.timed_operation("convert_audio") as metrics:
            # ... do work ...
        logger.log_performance(metrics)
    """
    
    def __init__(
        self,
        name: str,
        context: Optional[LogContext] = None,
        level: Optional[LogLevel] = None
    ):
        """
        Initialize the logger.
        
        Args:
            name: Logger name (typically module name)
            context: Optional default context for all log entries
            level: Optional log level override
        """
        self.name = name
        self.context = context or LogContext(component=name)
        
        # Get or create the underlying logger
        self._logger = logging.getLogger(f"claw.{name}")
        
        # Set level from config or parameter
        try:
            config = get_config()
            log_level = level or config.logging.level
            log_format = config.logging.format
        except Exception:
            log_level = level or LogLevel.INFO
            log_format = LogFormat.JSON
        
        self._logger.setLevel(getattr(logging, log_level.value))
        
        # Configure handler if not already configured
        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            
            if log_format == LogFormat.JSON:
                handler.setFormatter(StructuredJsonFormatter())
            else:
                handler.setFormatter(StructuredTextFormatter())
            
            self._logger.addHandler(handler)
        
        # Prevent propagation to root logger
        self._logger.propagate = False
    
    def _prepare_extra(self, **kwargs) -> Dict[str, Any]:
        """Prepare extra fields for logging."""
        extra = self.context.to_dict()
        extra.update(kwargs)
        return sanitize_for_logging(extra)
    
    def debug(self, message: str, **kwargs) -> None:
        """Log a debug message."""
        self._logger.debug(message, extra=self._prepare_extra(**kwargs))
    
    def info(self, message: str, **kwargs) -> None:
        """Log an info message."""
        self._logger.info(message, extra=self._prepare_extra(**kwargs))
    
    def warning(self, message: str, **kwargs) -> None:
        """Log a warning message."""
        self._logger.warning(message, extra=self._prepare_extra(**kwargs))
    
    def error(self, message: str, exc_info: bool = False, **kwargs) -> None:
        """Log an error message."""
        self._logger.error(message, exc_info=exc_info, extra=self._prepare_extra(**kwargs))
    
    def critical(self, message: str, exc_info: bool = False, **kwargs) -> None:
        """Log a critical message."""
        self._logger.critical(message, exc_info=exc_info, extra=self._prepare_extra(**kwargs))
    
    def exception(self, message: str, **kwargs) -> None:
        """Log an exception with traceback."""
        self._logger.exception(message, extra=self._prepare_extra(**kwargs))
    
    @contextmanager
    def timed_operation(self, operation: str, **extra_context):
        """
        Context manager for timing operations.
        
        Usage:
            with logger.timed_operation("audio_conversion") as metrics:
                # ... do work ...
            # metrics.duration_ms is now set
        
        Args:
            operation: Name of the operation being timed
            **extra_context: Additional context to include in logs
        
        Yields:
            PerformanceMetrics instance
        """
        metrics = PerformanceMetrics(operation=operation)
        
        try:
            yield metrics
            metrics.finish(success=True)
        except Exception as e:
            metrics.finish(success=False, error=e)
            raise
        finally:
            self.log_performance(metrics, **extra_context)
    
    def log_performance(self, metrics: PerformanceMetrics, **kwargs) -> None:
        """
        Log performance metrics.
        
        Args:
            metrics: PerformanceMetrics instance
            **kwargs: Additional context
        """
        extra = {**metrics.to_dict(), **kwargs}
        
        if metrics.success:
            self.info(f"Operation completed: {metrics.operation}", **extra)
        else:
            self.warning(f"Operation failed: {metrics.operation}", **extra)
    
    def log_tool_invocation(
        self,
        tool_name: str,
        invocation_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log a tool invocation event.
        
        Note: This logs ONLY metadata, never the actual audio or transcription.
        
        Args:
            tool_name: Name of the invoked tool
            invocation_id: Unique ID for this invocation
            metadata: Optional metadata (will be sanitized)
        """
        self.info(
            "Tool invoked",
            event="tool_invoked",
            tool_name=tool_name,
            invocation_id=invocation_id,
            **(sanitize_for_logging(metadata) if metadata else {})
        )
    
    def log_tool_response(
        self,
        tool_name: str,
        invocation_id: str,
        success: bool,
        duration_ms: float,
        error_type: Optional[str] = None
    ) -> None:
        """
        Log a tool response event.
        
        Note: This logs ONLY status and timing, never the transcription content.
        
        Args:
            tool_name: Name of the tool
            invocation_id: Unique ID for this invocation
            success: Whether the invocation succeeded
            duration_ms: Processing time in milliseconds
            error_type: Type of error if failed
        """
        self.info(
            "Tool response sent",
            event="tool_response",
            tool_name=tool_name,
            invocation_id=invocation_id,
            success=success,
            duration_ms=round(duration_ms, 2),
            error_type=error_type
        )
    
    def with_context(self, **kwargs) -> "MCPLogger":
        """
        Create a new logger with additional context.
        
        Args:
            **kwargs: Additional context fields
        
        Returns:
            New MCPLogger instance with updated context
        """
        new_context = LogContext(
            component=self.context.component,
            operation=kwargs.get("operation", self.context.operation),
            invocation_id=kwargs.get("invocation_id", self.context.invocation_id),
            connection_id=kwargs.get("connection_id", self.context.connection_id),
            extra={**self.context.extra, **{k: v for k, v in kwargs.items() 
                   if k not in ("operation", "invocation_id", "connection_id")}}
        )
        
        new_logger = MCPLogger(self.name)
        new_logger.context = new_context
        return new_logger


def get_logger(name: str, **context_kwargs) -> MCPLogger:
    """
    Get a logger instance for a module.
    
    Args:
        name: Module or component name
        **context_kwargs: Optional context fields
    
    Returns:
        Configured MCPLogger instance
    """
    context = LogContext(component=name, **context_kwargs) if context_kwargs else None
    return MCPLogger(name, context=context)


def generate_invocation_id() -> str:
    """Generate a unique invocation ID."""
    return f"inv_{uuid.uuid4().hex[:12]}"


def generate_connection_id() -> str:
    """Generate a unique connection ID."""
    return f"conn_{uuid.uuid4().hex[:8]}"


def timed(logger: Optional[MCPLogger] = None, operation: Optional[str] = None):
    """
    Decorator for timing function execution.
    
    Args:
        logger: Optional logger instance (uses function name if not provided)
        operation: Optional operation name (uses function name if not provided)
    
    Usage:
        @timed()
        def my_function():
            ...
        
        @timed(logger=my_logger, operation="custom_name")
        async def my_async_function():
            ...
    """
    def decorator(func: Callable) -> Callable:
        func_logger = logger or get_logger(func.__module__)
        op_name = operation or func.__name__
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            with func_logger.timed_operation(op_name):
                return func(*args, **kwargs)
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            with func_logger.timed_operation(op_name):
                return await func(*args, **kwargs)
        
        # Return appropriate wrapper based on function type
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# Configure the root logger for the application
def configure_root_logger(level: LogLevel = LogLevel.INFO, format: LogFormat = LogFormat.JSON) -> None:
    """
    Configure the root logger for the application.
    
    This should be called once at application startup.
    
    Args:
        level: Log level
        format: Log format (JSON or TEXT)
    """
    root_logger = logging.getLogger("claw")
    root_logger.setLevel(getattr(logging, level.value))
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Add new handler
    handler = logging.StreamHandler(sys.stderr)
    
    if format == LogFormat.JSON:
        handler.setFormatter(StructuredJsonFormatter())
    else:
        handler.setFormatter(StructuredTextFormatter())
    
    root_logger.addHandler(handler)
    root_logger.propagate = False
