"""
Tools package for Claw Auto-Transcriber MCP Server.

This package contains tool definitions that are exposed via the MCP protocol.
Each tool is a self-contained module that defines:
- Tool schema (input/output)
- Input validation
- Response formatting

Available tools:
- transcribe_audio: Transcribe audio/voice messages to text
- transcribe-audio-async: Async transcription via filesystem queues
"""

from typing import List

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
from tools.transcribe_audio_async import (
    TranscribeAudioAsyncTool,
    AsyncToolInput,
    AsyncToolResponse,
    ToolInputError as AsyncToolInputError,
    ToolExecutionError as AsyncToolExecutionError,
    get_tool_schema as get_async_tool_schema,
    validate_tool_input as validate_async_tool_input,
    TOOL_NAME as ASYNC_TOOL_NAME,
    TOOL_DESCRIPTION as ASYNC_TOOL_DESCRIPTION,
)

# List of available tool names
AVAILABLE_TOOLS: List[str] = [
    "transcribe_audio",
    "transcribe-audio-async",
]

__all__ = [
    # Tool class and data types
    "TranscribeAudioTool",
    "ToolInput",
    "ToolResponse",
    # Exceptions
    "ToolInputError",
    "ToolExecutionError",
    # Functions
    "get_tool_schema",
    "validate_tool_input",
    # Constants
    "TOOL_NAME",
    "TOOL_DESCRIPTION",
    "TranscribeAudioAsyncTool",
    "AsyncToolInput",
    "AsyncToolResponse",
    "AsyncToolInputError",
    "AsyncToolExecutionError",
    "get_async_tool_schema",
    "validate_async_tool_input",
    "ASYNC_TOOL_NAME",
    "ASYNC_TOOL_DESCRIPTION",
    "AVAILABLE_TOOLS",
]
