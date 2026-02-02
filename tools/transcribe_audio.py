"""
Transcribe Audio Tool for Claw Auto-Transcriber MCP Server.

This module defines the transcribe_audio tool that:
- Provides JSON schema for MCP tool registration
- Validates tool invocation inputs
- Executes the transcription pipeline (audio_processor → transcriber)
- Formats responses with metadata

CRITICAL SECURITY NOTES:
1. Audio content is NEVER logged
2. Transcription text is NEVER logged
3. Only metadata (duration, confidence, etc.) is logged
"""

import base64
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from src.config import Config, get_config
from src.logger import MCPLogger, get_logger
from src.audio_processor import (
    AudioProcessor,
    ProcessedAudio,
    AudioProcessingError,
    AudioValidationError,
    AudioConversionError,
    AudioDurationError,
    AudioSizeError,
    AudioFormatError,
)
from src.transcriber import (
    Transcriber,
    TranscriptionResult,
    TranscriptionError,
    TranscriptionAPIError,
    TranscriptionTimeoutError,
    TranscriptionQuotaError,
    NoSpeechDetectedError,
)


# Tool metadata
TOOL_NAME = "transcribe_audio"
TOOL_DESCRIPTION = (
    "Transcribe audio/voice messages to text using Google Cloud Speech-to-Text. "
    "Accepts base64-encoded audio in OGG, MP3, WAV, or FLAC format. "
    "Returns transcription text with confidence score and metadata."
)


class ToolInputError(Exception):
    """Raised when tool input validation fails."""
    pass


class ToolExecutionError(Exception):
    """Raised when tool execution fails."""
    pass


@dataclass
class ToolInput:
    """
    Validated input for the transcribe_audio tool.
    
    Attributes:
        audio_data: Raw decoded audio bytes
        language_code: BCP-47 language code (e.g., "en-US")
        original_format: Optional format hint ("ogg", "mp3", etc.)
        user_id: Optional user identifier for tracking
        message_id: Optional message identifier for tracking
    """
    audio_data: str  # Base64-encoded audio (kept as string for AudioProcessor)
    language_code: str
    original_format: Optional[str] = None
    user_id: Optional[str] = None
    message_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (safe for logging - no audio content)."""
        return {
            "language_code": self.language_code,
            "original_format": self.original_format,
            "user_id": self.user_id,
            "message_id": self.message_id,
            "audio_data_length": len(self.audio_data) if self.audio_data else 0,
        }


@dataclass
class ToolResponse:
    """
    Response from the transcribe_audio tool.
    
    Attributes:
        success: Whether transcription succeeded
        transcription: Transcribed text (None if failed)
        confidence: Confidence score 0.0 to 1.0 (None if failed)
        language_code: Language used for transcription
        duration_seconds: Audio duration in seconds
        word_count: Number of words in transcription
        processing_time_ms: Total processing time in milliseconds
        error: Error message if failed (None if success)
        error_type: Error type classification (None if success)
    """
    success: bool
    transcription: Optional[str] = None
    confidence: Optional[float] = None
    language_code: str = "en-US"
    duration_seconds: float = 0.0
    word_count: int = 0
    processing_time_ms: float = 0.0
    error: Optional[str] = None
    error_type: Optional[str] = None
    invocation_id: Optional[str] = None
    original_format: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON response."""
        result = {
            "success": self.success,
            "transcription": self.transcription,
            "confidence": round(self.confidence, 3) if self.confidence is not None else None,
            "language_code": self.language_code,
            "duration_seconds": round(self.duration_seconds, 2),
            "word_count": self.word_count,
            "processing_time_ms": round(self.processing_time_ms, 2),
        }
        
        # Add optional metadata
        metadata = {}
        if self.invocation_id:
            metadata["invocation_id"] = self.invocation_id
        if self.original_format:
            metadata["original_format"] = self.original_format
        if metadata:
            result["metadata"] = metadata
        
        # Add error info if present
        if self.error:
            result["error"] = self.error
        if self.error_type:
            result["error_type"] = self.error_type
        
        return result
    
    def to_log_dict(self) -> Dict[str, Any]:
        """Convert to dictionary safe for logging (no transcription text)."""
        return {
            "success": self.success,
            "confidence": round(self.confidence, 3) if self.confidence is not None else None,
            "language_code": self.language_code,
            "duration_seconds": round(self.duration_seconds, 2),
            "word_count": self.word_count,
            "processing_time_ms": round(self.processing_time_ms, 2),
            "has_error": self.error is not None,
            "error_type": self.error_type,
        }


def get_tool_schema() -> Dict[str, Any]:
    """
    Get the JSON schema for the transcribe_audio tool.
    
    This schema is used for MCP tool registration and defines
    the expected input parameters.
    
    Returns:
        Dictionary containing the tool schema
    """
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "inputSchema": {
            "type": "object",
            "properties": {
                "audio_data": {
                    "type": "string",
                    "description": (
                        "Base64-encoded audio file. Supports OGG (Telegram voice), "
                        "MP3, WAV, and FLAC formats."
                    ),
                },
                "metadata": {
                    "type": "object",
                    "description": "Optional metadata about the audio",
                    "properties": {
                        "original_format": {
                            "type": "string",
                            "enum": ["ogg", "mp3", "wav", "flac"],
                            "description": "Original audio format hint",
                        },
                        "duration_seconds": {
                            "type": "number",
                            "description": "Expected duration in seconds",
                        },
                        "language_code": {
                            "type": "string",
                            "description": "BCP-47 language code (e.g., 'en-US')",
                        },
                        "user_id": {
                            "type": "string",
                            "description": "User identifier for tracking",
                        },
                        "message_id": {
                            "type": "string",
                            "description": "Message identifier for tracking",
                        },
                    },
                },
            },
            "required": ["audio_data"],
        },
    }


class TranscribeAudioTool:
    """
    Main tool class for the transcribe_audio MCP tool.
    
    Handles the complete transcription pipeline:
    1. Validate and parse input arguments
    2. Process audio (validation, conversion to FLAC)
    3. Transcribe using Google Cloud Speech-to-Text
    4. Format response with metadata
    
    Usage:
        tool = TranscribeAudioTool()
        
        # Validate input
        tool_input = tool.validate_input({"audio_data": "..."})
        
        # Execute transcription
        response = tool.execute(tool_input, invocation_id="inv_123")
        
        # Get formatted response
        result = response.to_dict()
    """
    
    def __init__(
        self,
        config: Optional[Config] = None,
        logger: Optional[MCPLogger] = None,
        audio_processor: Optional[AudioProcessor] = None,
        transcriber: Optional[Transcriber] = None
    ):
        """
        Initialize the tool.
        
        Args:
            config: Optional configuration instance
            logger: Optional logger instance
            audio_processor: Optional audio processor (for testing)
            transcriber: Optional transcriber (for testing)
        """
        self._config = config
        self._logger = logger or get_logger("transcribe_audio_tool")
        self._audio_processor = audio_processor
        self._transcriber = transcriber
    
    @property
    def config(self) -> Config:
        """Get configuration (lazy loading)."""
        if self._config is None:
            self._config = get_config()
        return self._config
    
    @property
    def audio_processor(self) -> AudioProcessor:
        """Get or create audio processor."""
        if self._audio_processor is None:
            self._audio_processor = AudioProcessor(
                config=self.config,
                logger=self._logger.with_context(component="audio_processor")
            )
        return self._audio_processor
    
    @property
    def transcriber(self) -> Transcriber:
        """Get or create transcriber."""
        if self._transcriber is None:
            self._transcriber = Transcriber(
                config=self.config,
                logger=self._logger.with_context(component="transcriber")
            )
        return self._transcriber
    
    @staticmethod
    def get_schema() -> Dict[str, Any]:
        """Get the tool schema for MCP registration."""
        return get_tool_schema()
    
    def validate_input(self, arguments: Dict[str, Any]) -> ToolInput:
        """
        Validate and parse tool invocation arguments.
        
        Args:
            arguments: Raw arguments from tool invocation
        
        Returns:
            Validated ToolInput instance
        
        Raises:
            ToolInputError: If validation fails
        """
        # Check required audio_data
        if "audio_data" not in arguments:
            raise ToolInputError("Missing required parameter: audio_data")
        
        audio_data = arguments["audio_data"]
        
        # Validate audio_data is a non-empty string
        if not isinstance(audio_data, str):
            raise ToolInputError("audio_data must be a base64-encoded string")
        
        if not audio_data.strip():
            raise ToolInputError("audio_data cannot be empty")
        
        # Validate base64 encoding
        try:
            decoded = base64.b64decode(audio_data)
            if len(decoded) == 0:
                raise ToolInputError("Decoded audio data is empty")
        except Exception as e:
            if isinstance(e, ToolInputError):
                raise
            raise ToolInputError(f"Invalid base64 encoding: {type(e).__name__}")
        
        # Extract metadata
        metadata = arguments.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        
        # Get language code with default
        language_code = metadata.get("language_code")
        if not language_code:
            language_code = self.config.audio.default_language
        
        return ToolInput(
            audio_data=audio_data,
            language_code=language_code,
            original_format=metadata.get("original_format"),
            user_id=metadata.get("user_id"),
            message_id=metadata.get("message_id"),
        )
    
    def execute(
        self,
        tool_input: ToolInput,
        invocation_id: Optional[str] = None
    ) -> ToolResponse:
        """
        Execute the transcription pipeline.
        
        Args:
            tool_input: Validated tool input
            invocation_id: Optional invocation ID for tracking
        
        Returns:
            ToolResponse with transcription result or error
        """
        start_time = time.perf_counter()
        
        self._logger.debug(
            "Executing transcription",
            invocation_id=invocation_id,
            language_code=tool_input.language_code,
            original_format=tool_input.original_format
        )
        
        try:
            # Step 1: Process audio
            processed = self.audio_processor.process_audio(
                audio_data=tool_input.audio_data,
                expected_format=tool_input.original_format,
                is_base64=True
            )
            
            self._logger.debug(
                "Audio processed",
                invocation_id=invocation_id,
                duration_seconds=processed.metadata.duration_seconds,
                original_format=processed.original_format
            )
            
            # Step 2: Transcribe
            result = self.transcriber.transcribe_with_retry(
                audio_data=processed.flac_data,
                language_code=tool_input.language_code
            )
            
            processing_time_ms = (time.perf_counter() - start_time) * 1000
            
            # Build success response
            response = ToolResponse(
                success=True,
                transcription=result.text,
                confidence=result.confidence,
                language_code=result.language_code,
                duration_seconds=processed.metadata.duration_seconds,
                word_count=len(result.text.split()) if result.text else 0,
                processing_time_ms=processing_time_ms,
                invocation_id=invocation_id,
                original_format=processed.original_format,
            )
            
            self._logger.info(
                "Transcription completed",
                invocation_id=invocation_id,
                **response.to_log_dict()
            )
            
            return response
            
        except NoSpeechDetectedError:
            # No speech is a valid result, not an error
            processing_time_ms = (time.perf_counter() - start_time) * 1000
            
            self._logger.info(
                "No speech detected in audio",
                invocation_id=invocation_id
            )
            
            return ToolResponse(
                success=True,
                transcription="",
                confidence=0.0,
                language_code=tool_input.language_code,
                duration_seconds=0.0,  # Unknown without processed audio
                word_count=0,
                processing_time_ms=processing_time_ms,
                invocation_id=invocation_id,
            )
            
        except AudioValidationError as e:
            return self._create_error_response(
                error=str(e),
                error_type="validation_error",
                invocation_id=invocation_id,
                start_time=start_time,
                language_code=tool_input.language_code
            )
            
        except AudioDurationError as e:
            return self._create_error_response(
                error=str(e),
                error_type="duration_error",
                invocation_id=invocation_id,
                start_time=start_time,
                language_code=tool_input.language_code
            )
            
        except AudioSizeError as e:
            return self._create_error_response(
                error=str(e),
                error_type="size_error",
                invocation_id=invocation_id,
                start_time=start_time,
                language_code=tool_input.language_code
            )
            
        except AudioFormatError as e:
            return self._create_error_response(
                error=str(e),
                error_type="format_error",
                invocation_id=invocation_id,
                start_time=start_time,
                language_code=tool_input.language_code
            )
            
        except AudioConversionError as e:
            return self._create_error_response(
                error=f"Failed to process audio: {str(e)}",
                error_type="conversion_error",
                invocation_id=invocation_id,
                start_time=start_time,
                language_code=tool_input.language_code
            )
            
        except AudioProcessingError as e:
            return self._create_error_response(
                error=f"Audio processing failed: {str(e)}",
                error_type="processing_error",
                invocation_id=invocation_id,
                start_time=start_time,
                language_code=tool_input.language_code
            )
            
        except TranscriptionTimeoutError as e:
            return self._create_error_response(
                error="Transcription request timed out. Please try again.",
                error_type="timeout_error",
                invocation_id=invocation_id,
                start_time=start_time,
                language_code=tool_input.language_code
            )
            
        except TranscriptionQuotaError as e:
            return self._create_error_response(
                error="Transcription service quota exceeded. Please try again later.",
                error_type="quota_error",
                invocation_id=invocation_id,
                start_time=start_time,
                language_code=tool_input.language_code
            )
            
        except TranscriptionAPIError as e:
            return self._create_error_response(
                error="Transcription service error. Please try again.",
                error_type="api_error",
                invocation_id=invocation_id,
                start_time=start_time,
                language_code=tool_input.language_code
            )
            
        except TranscriptionError as e:
            return self._create_error_response(
                error=f"Transcription failed: {str(e)}",
                error_type="transcription_error",
                invocation_id=invocation_id,
                start_time=start_time,
                language_code=tool_input.language_code
            )
            
        except Exception as e:
            self._logger.exception(
                "Unexpected error during transcription",
                invocation_id=invocation_id
            )
            return self._create_error_response(
                error="An unexpected error occurred",
                error_type="internal_error",
                invocation_id=invocation_id,
                start_time=start_time,
                language_code=tool_input.language_code
            )
    
    def _create_error_response(
        self,
        error: str,
        error_type: str,
        invocation_id: Optional[str],
        start_time: float,
        language_code: str
    ) -> ToolResponse:
        """Create an error response."""
        processing_time_ms = (time.perf_counter() - start_time) * 1000
        
        self._logger.error(
            "Transcription failed",
            invocation_id=invocation_id,
            error_type=error_type
        )
        
        return ToolResponse(
            success=False,
            language_code=language_code,
            processing_time_ms=processing_time_ms,
            error=error,
            error_type=error_type,
            invocation_id=invocation_id,
        )


# Module-level convenience functions

def validate_tool_input(arguments: Dict[str, Any]) -> ToolInput:
    """
    Validate tool input arguments.
    
    Convenience function that creates a temporary tool instance.
    
    Args:
        arguments: Raw arguments from tool invocation
    
    Returns:
        Validated ToolInput instance
    
    Raises:
        ToolInputError: If validation fails
    """
    tool = TranscribeAudioTool()
    return tool.validate_input(arguments)
