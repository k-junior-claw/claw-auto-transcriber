"""
Claw Auto-Transcriber MCP Server.

This package provides an MCP (Model Context Protocol) server for audio
transcription using Google Cloud Speech-to-Text.

Modules:
    config: Configuration management
    logger: Structured logging utilities
    audio_processor: Audio validation and conversion
    transcriber: Google Cloud Speech-to-Text integration
    mcp_server: MCP server implementation
"""

from src.config import (
    Config,
    ConfigurationError,
    CredentialError,
    get_config,
    init_config,
)
from src.logger import (
    MCPLogger,
    get_logger,
    generate_invocation_id,
    generate_connection_id,
)
from src.audio_processor import (
    AudioProcessor,
    AudioProcessingError,
    AudioValidationError,
    process_audio,
    validate_audio,
)
from src.transcriber import (
    Transcriber,
    TranscriptionResult,
    TranscriptionError,
    TranscriptionAPIError,
    TranscriptionTimeoutError,
    TranscriptionQuotaError,
    NoSpeechDetectedError,
    get_transcriber,
    transcribe,
    transcribe_with_retry,
)
from src.mcp_server import (
    MCPTranscriptionServer,
    create_server,
    run_server,
    main,
)

__version__ = "1.0.0"
__all__ = [
    # Config
    "Config",
    "ConfigurationError",
    "CredentialError",
    "get_config",
    "init_config",
    # Logger
    "MCPLogger",
    "get_logger",
    "generate_invocation_id",
    "generate_connection_id",
    # Audio Processor
    "AudioProcessor",
    "AudioProcessingError",
    "AudioValidationError",
    "process_audio",
    "validate_audio",
    # Transcriber
    "Transcriber",
    "TranscriptionResult",
    "TranscriptionError",
    "TranscriptionAPIError",
    "TranscriptionTimeoutError",
    "TranscriptionQuotaError",
    "NoSpeechDetectedError",
    "get_transcriber",
    "transcribe",
    "transcribe_with_retry",
    # MCP Server
    "MCPTranscriptionServer",
    "create_server",
    "run_server",
    "main",
]
