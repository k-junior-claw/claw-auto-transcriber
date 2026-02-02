"""
MCP Server for Claw Auto-Transcriber.

Implements the Model Context Protocol (MCP) server that exposes
the `transcribe_audio` tool for voice/audio transcription.

This module provides:
- MCP server initialization and lifecycle management
- Tool registration (transcribe_audio)
- Connection handling
- Request/response processing
- Error handling and graceful shutdown

Usage:
    # Run as standalone server
    python mcp_server.py
    
    # Or import and use programmatically
    from mcp_server import create_server, run_server
    server = create_server()
    await run_server(server)

SECURITY NOTES:
- Audio content is NEVER logged
- All audio processing is ephemeral
- Immediate cleanup after transcription
"""

import asyncio
import signal
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    CallToolResult,
    INVALID_PARAMS,
    INTERNAL_ERROR,
)

from src.config import Config, init_config, get_config, ConfigurationError, CredentialError
from src.logger import (
    get_logger,
    MCPLogger,
    configure_root_logger,
    generate_invocation_id,
    generate_connection_id,
    LogLevel,
    LogFormat,
)
from src.audio_processor import (
    AudioProcessor,
    AudioProcessingError,
    AudioValidationError,
    AudioConversionError,
    AudioDurationError,
    AudioSizeError,
    AudioFormatError,
    cleanup_temp_files,
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
from tools.transcribe_audio import (
    TranscribeAudioTool,
    ToolInput,
    ToolResponse,
    ToolInputError,
)


# Tool name constant
TRANSCRIBE_AUDIO_TOOL = "transcribe_audio"


@dataclass
class ServerState:
    """Runtime state for the MCP server."""
    server_id: str
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    active_connections: int = 0
    total_invocations: int = 0
    successful_invocations: int = 0
    failed_invocations: int = 0
    is_running: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (safe for logging)."""
        return {
            "server_id": self.server_id,
            "start_time": self.start_time.isoformat(),
            "uptime_seconds": (datetime.now(timezone.utc) - self.start_time).total_seconds(),
            "active_connections": self.active_connections,
            "total_invocations": self.total_invocations,
            "successful_invocations": self.successful_invocations,
            "failed_invocations": self.failed_invocations,
            "success_rate": (
                self.successful_invocations / self.total_invocations * 100
                if self.total_invocations > 0 else 0
            ),
        }


class MCPTranscriptionServer:
    """
    Main MCP Server class for audio transcription.
    
    Wraps the MCP Server SDK and provides the transcribe_audio tool
    for voice message transcription.
    
    Attributes:
        config: Server configuration
        state: Runtime server state
        server: MCP Server instance
    """
    
    def __init__(
        self,
        config: Optional[Config] = None,
        logger: Optional[MCPLogger] = None
    ):
        """
        Initialize the MCP transcription server.
        
        Args:
            config: Optional configuration instance
            logger: Optional logger instance
        """
        self._config = config
        self._logger = logger or get_logger("mcp_server")
        self._audio_processor: Optional[AudioProcessor] = None
        self._transcriber: Optional[Transcriber] = None
        self._transcribe_tool: Optional[TranscribeAudioTool] = None
        
        # Initialize state
        self.state = ServerState(
            server_id=f"claw-transcriber-{generate_connection_id()}"
        )
        
        # Create MCP server instance
        self.server = Server(self.server_name)
        
        # Register handlers
        self._register_handlers()
    
    @property
    def config(self) -> Config:
        """Get configuration."""
        if self._config is None:
            self._config = get_config()
        return self._config
    
    @property
    def server_name(self) -> str:
        """Get the server name from config."""
        try:
            return self.config.mcp_server.name
        except Exception:
            return "claw-auto-transcriber"
    
    @property
    def audio_processor(self) -> AudioProcessor:
        """Get or create the audio processor."""
        if self._audio_processor is None:
            self._audio_processor = AudioProcessor(
                config=self.config,
                logger=self._logger.with_context(component="audio_processor")
            )
        return self._audio_processor
    
    @property
    def transcriber(self) -> Transcriber:
        """Get or create the transcriber."""
        if self._transcriber is None:
            self._transcriber = Transcriber(
                config=self.config,
                logger=self._logger.with_context(component="transcriber")
            )
        return self._transcriber
    
    @property
    def transcribe_tool(self) -> TranscribeAudioTool:
        """Get or create the transcribe audio tool."""
        if self._transcribe_tool is None:
            self._transcribe_tool = TranscribeAudioTool(
                config=self.config,
                logger=self._logger.with_context(component="transcribe_tool"),
                audio_processor=self.audio_processor,
                transcriber=self.transcriber
            )
        return self._transcribe_tool
    
    def _register_handlers(self) -> None:
        """Register MCP protocol handlers."""
        
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """Return list of available tools."""
            return self._get_tools()
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> Sequence[TextContent]:
            """Handle tool invocation."""
            return await self._handle_tool_call(name, arguments)
    
    def _get_tools(self) -> list[Tool]:
        """
        Get the list of available tools.
        
        Returns:
            List of Tool definitions
        """
        return [
            Tool(
                name=TRANSCRIBE_AUDIO_TOOL,
                description=(
                    "Transcribe audio/voice messages to text using Google Cloud "
                    "Speech-to-Text. Accepts base64-encoded audio in OGG, MP3, WAV, "
                    "or FLAC format. Returns transcription text with confidence score."
                ),
                inputSchema={
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
            ),
        ]
    
    async def _handle_tool_call(
        self,
        name: str,
        arguments: dict
    ) -> Sequence[TextContent]:
        """
        Handle a tool invocation.
        
        Args:
            name: Tool name
            arguments: Tool arguments
        
        Returns:
            Sequence of TextContent with the result
        
        Raises:
            Various exceptions mapped to MCP error codes
        """
        invocation_id = generate_invocation_id()
        
        self._logger.log_tool_invocation(
            tool_name=name,
            invocation_id=invocation_id,
            metadata={
                "has_audio_data": "audio_data" in arguments,
                "has_metadata": "metadata" in arguments,
            }
        )
        
        self.state.total_invocations += 1
        
        try:
            if name == TRANSCRIBE_AUDIO_TOOL:
                # Note: success/failure tracking is done inside _handle_transcribe_audio
                # based on the tool response's success flag
                result = await self._handle_transcribe_audio(arguments, invocation_id)
                return result
            else:
                # Don't increment failed_invocations here - the exception handler will do it
                raise ValueError(f"Unknown tool: {name}")
                
        except AudioValidationError as e:
            self.state.failed_invocations += 1
            self._logger.error(
                "Audio validation failed",
                invocation_id=invocation_id,
                error_type="validation"
            )
            return [TextContent(
                type="text",
                text=f"Error: Invalid audio - {str(e)}"
            )]
            
        except AudioDurationError as e:
            self.state.failed_invocations += 1
            self._logger.error(
                "Audio duration exceeded",
                invocation_id=invocation_id,
                error_type="duration"
            )
            return [TextContent(
                type="text",
                text=f"Error: {str(e)}"
            )]
            
        except AudioSizeError as e:
            self.state.failed_invocations += 1
            self._logger.error(
                "Audio size exceeded",
                invocation_id=invocation_id,
                error_type="size"
            )
            return [TextContent(
                type="text",
                text=f"Error: {str(e)}"
            )]
            
        except AudioFormatError as e:
            self.state.failed_invocations += 1
            self._logger.error(
                "Audio format unsupported",
                invocation_id=invocation_id,
                error_type="format"
            )
            return [TextContent(
                type="text",
                text=f"Error: {str(e)}"
            )]
            
        except AudioConversionError as e:
            self.state.failed_invocations += 1
            self._logger.error(
                "Audio conversion failed",
                invocation_id=invocation_id,
                error_type="conversion"
            )
            return [TextContent(
                type="text",
                text=f"Error: Failed to process audio - {str(e)}"
            )]
            
        except AudioProcessingError as e:
            self.state.failed_invocations += 1
            self._logger.error(
                "Audio processing failed",
                invocation_id=invocation_id,
                error_type="processing"
            )
            return [TextContent(
                type="text",
                text=f"Error: Audio processing failed - {str(e)}"
            )]
            
        except ToolInputError as e:
            self.state.failed_invocations += 1
            self._logger.error(
                "Tool input validation failed",
                invocation_id=invocation_id,
                error_type="input_validation"
            )
            return [TextContent(
                type="text",
                text=f"Error: Invalid input - {str(e)}"
            )]
            
        except TranscriptionTimeoutError as e:
            self.state.failed_invocations += 1
            self._logger.error(
                "Transcription timed out",
                invocation_id=invocation_id,
                error_type="timeout"
            )
            return [TextContent(
                type="text",
                text="Error: Transcription request timed out. Please try again."
            )]
            
        except TranscriptionQuotaError as e:
            self.state.failed_invocations += 1
            self._logger.error(
                "Transcription quota exceeded",
                invocation_id=invocation_id,
                error_type="quota"
            )
            return [TextContent(
                type="text",
                text="Error: Transcription service quota exceeded. Please try again later."
            )]
            
        except TranscriptionAPIError as e:
            self.state.failed_invocations += 1
            self._logger.error(
                "Transcription API error",
                invocation_id=invocation_id,
                error_type="api"
            )
            return [TextContent(
                type="text",
                text="Error: Transcription service error. Please try again."
            )]
            
        except TranscriptionError as e:
            self.state.failed_invocations += 1
            self._logger.error(
                "Transcription failed",
                invocation_id=invocation_id,
                error_type="transcription"
            )
            return [TextContent(
                type="text",
                text=f"Error: Transcription failed - {str(e)}"
            )]
            
        except Exception as e:
            self.state.failed_invocations += 1
            self._logger.exception(
                "Unexpected error during tool execution",
                invocation_id=invocation_id
            )
            return [TextContent(
                type="text",
                text=f"Error: An unexpected error occurred"
            )]
    
    async def _handle_transcribe_audio(
        self,
        arguments: dict,
        invocation_id: str
    ) -> Sequence[TextContent]:
        """
        Handle the transcribe_audio tool invocation.
        
        Args:
            arguments: Tool arguments including audio_data
            invocation_id: Unique invocation ID
        
        Returns:
            Sequence of TextContent with transcription result
        """
        import json
        
        # Validate input using the tool
        tool_input = self.transcribe_tool.validate_input(arguments)
        
        # Execute transcription pipeline
        response = self.transcribe_tool.execute(tool_input, invocation_id=invocation_id)
        
        # Track success/failure based on tool response
        if response.success:
            self.state.successful_invocations += 1
        else:
            self.state.failed_invocations += 1
        
        # Log response metadata (NOT transcription content)
        self._logger.log_tool_response(
            tool_name=TRANSCRIBE_AUDIO_TOOL,
            invocation_id=invocation_id,
            success=response.success,
            duration_ms=response.processing_time_ms
        )
        
        return [TextContent(
            type="text",
            text=json.dumps(response.to_dict(), indent=2)
        )]
    
    async def start(self) -> None:
        """Start the MCP server."""
        self._logger.info(
            "Starting MCP server",
            server_id=self.state.server_id,
            server_name=self.server_name
        )
        self.state.is_running = True
    
    async def stop(self) -> None:
        """Stop the MCP server and cleanup resources."""
        self._logger.info(
            "Stopping MCP server",
            **self.state.to_dict()
        )
        
        # Cleanup audio processor temp files
        if self._audio_processor:
            self._audio_processor.cleanup()
        
        self.state.is_running = False
        
        self._logger.info("MCP server stopped")


def create_server(config: Optional[Config] = None) -> MCPTranscriptionServer:
    """
    Create a new MCP transcription server instance.
    
    Args:
        config: Optional configuration instance
    
    Returns:
        Configured MCPTranscriptionServer instance
    """
    return MCPTranscriptionServer(config=config)


async def run_server(server: Optional[MCPTranscriptionServer] = None) -> None:
    """
    Run the MCP server using stdio transport.
    
    This is the main entry point for running the server in production.
    The server communicates via stdin/stdout using the MCP protocol.
    
    Args:
        server: Optional server instance (creates new one if not provided)
    """
    if server is None:
        server = create_server()
    
    logger = get_logger("mcp_server_runner")
    
    # Setup signal handlers for graceful shutdown
    shutdown_event = asyncio.Event()
    
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating shutdown")
        shutdown_event.set()
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await server.start()
        
        # Run with stdio transport
        async with stdio_server() as (read_stream, write_stream):
            logger.info("Server connected via stdio")
            
            await server.server.run(
                read_stream,
                write_stream,
                server.server.create_initialization_options()
            )
            
    except Exception as e:
        logger.exception("Server error")
        raise
    finally:
        await server.stop()


def main() -> None:
    """
    Main entry point for the MCP server.
    
    Initializes configuration, logging, and runs the server.
    """
    # Initialize configuration
    try:
        config = init_config(validate_credentials=False)
    except (ConfigurationError, CredentialError) as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Configure logging
    configure_root_logger(
        level=config.logging.level,
        format=config.logging.format
    )
    
    logger = get_logger("main")
    logger.info(
        "Claw Auto-Transcriber MCP Server starting",
        version="1.0.0",
        server_name=config.mcp_server.name
    )
    
    # Ensure temp directory exists
    config.ensure_temp_dir()
    
    # Run the server
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
    except Exception as e:
        logger.exception("Server failed")
        sys.exit(1)
    
    logger.info("Server shutdown complete")


if __name__ == "__main__":
    main()
