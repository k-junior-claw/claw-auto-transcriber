"""
Standalone CLI for Claw Auto-Transcriber.

This CLI runs independently of the MCP server and reuses the same
audio processing and transcription pipeline exposed by the
`transcribe_audio` MCP tool.

Usage:
    claw-transcriber-cli <mediaPath> <outputBase>

Where:
    - mediaPath   : Path to the input audio file (e.g. /tmp/in.ogg)
    - outputBase  : Base path for the output (e.g. /tmp/out/my_new)

The CLI will write:
    <outputBase>.txt

containing ONLY the transcription text (no metadata).
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path
from typing import Optional

from src.config import get_config
from src.logger import get_logger
from tools.transcribe_audio import (
    TranscribeAudioTool,
    ToolInputError,
)


def run_cli(media_path: Path, output_base: Path) -> int:
    """
    Core CLI logic.

    Args:
        media_path: Path to the input audio file.
        output_base: Base path (without extension) for the output file.

    Returns:
        Exit code (0 on success, non-zero on error).
    """
    logger = get_logger("cli")

    media_path = media_path.expanduser().resolve()
    output_base = output_base.expanduser().resolve()

    if not media_path.is_file():
        print(f"Input file does not exist or is not a file: {media_path}", file=sys.stderr)
        return 1

    try:
        audio_bytes = media_path.read_bytes()
    except Exception as exc:  # pragma: no cover - extremely unlikely filesystem errors
        print(f"Failed to read input file: {exc}", file=sys.stderr)
        return 1

    if not audio_bytes:
        print("Input file is empty", file=sys.stderr)
        return 1

    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

    # Load configuration to get default language and supported formats.
    config = get_config()
    language_code = config.audio.default_language

    tool = TranscribeAudioTool(
        config=config,
        logger=logger.with_context(component="cli_transcribe_tool"),
    )

    arguments = {
        "audio_data": audio_base64,
        "metadata": {
            # Default to ogg as requested; actual format is still validated
            # by AudioProcessor based on magic bytes.
            "original_format": "ogg",
            "language_code": language_code,
        },
    }

    try:
        tool_input = tool.validate_input(arguments)
    except ToolInputError as exc:
        print(f"Invalid input for transcription: {exc}", file=sys.stderr)
        return 1

    response = tool.execute(tool_input, invocation_id=None)

    if not response.success:
        error_msg = response.error or "Transcription failed"
        print(f"Transcription error: {error_msg}", file=sys.stderr)
        return 1

    transcription = response.transcription or ""

    output_path = output_base.with_suffix(".txt")
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Write strictly the transcription text, no extra metadata.
        output_path.write_text(transcription, encoding="utf-8")
    except Exception as exc:  # pragma: no cover - unlikely filesystem errors
        print(f"Failed to write output file: {exc}", file=sys.stderr)
        return 1

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog="claw-transcriber-cli",
        description=(
            "Standalone CLI for Claw Auto-Transcriber. "
            "Transcribes an audio file and writes the transcription to a .txt file."
        ),
    )
    parser.add_argument(
        "mediaPath",
        help="Path to the input audio file (e.g. /tmp/in.ogg)",
    )
    parser.add_argument(
        "outputBase",
        help=(
            "Base path for the output text file (e.g. /tmp/out/my_new). "
            "The CLI will write <outputBase>.txt"
        ),
    )
    return parser


def cli(argv: Optional[list[str]] = None) -> int:
    """
    Parse command-line arguments and run the CLI.

    Args:
        argv: Optional list of arguments. If None, uses sys.argv[1:].

    Returns:
        Exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    media_path = Path(args.mediaPath)
    output_base = Path(args.outputBase)

    return run_cli(media_path, output_base)


def main() -> None:
    """Entry point for console_scripts."""
    try:
        exit_code = cli()
    except KeyboardInterrupt:  # pragma: no cover - manual interruption
        exit_code = 1
    sys.exit(exit_code)

if __name__ == "__main__":
    main()