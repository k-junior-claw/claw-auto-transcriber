"""
Tools package for Claw Auto-Transcriber MCP Server.

This package contains tool definitions that are exposed via the MCP protocol.
Each tool is a self-contained module that defines:
- Tool schema (input/output)
- Input validation
- Response formatting

Available tools:
- transcribe_audio: Transcribe audio/voice messages to text
"""

from typing import List

# List of available tool names
AVAILABLE_TOOLS: List[str] = [
    "transcribe_audio",
]

__all__ = ["AVAILABLE_TOOLS"]
