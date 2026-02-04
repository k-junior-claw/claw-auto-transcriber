"""
Async transcription tool for Claw Auto-Transcriber MCP Server.

Provides filesystem-based asynchronous transcription with VAD chunking.
"""

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.async_queue import AsyncQueue
from src.config import Config, get_config
from src.logger import MCPLogger, get_logger
from src.vad_chunker import VADChunker, VADChunkerError, ChunkSegment


TOOL_NAME = "transcribe-audio-async"
TOOL_DESCRIPTION = (
    "Asynchronous audio transcription using filesystem queues. "
    "Accepts an absolute input path to an OGG file and returns "
    "a job ID with chunk list."
)


class ToolInputError(Exception):
    """Raised when tool input validation fails."""


class ToolExecutionError(Exception):
    """Raised when tool execution fails."""


@dataclass
class AsyncToolInput:
    """Validated input for the async transcription tool."""
    input_path: Path
    output_dir: Optional[Path]
    chunk_duration: int
    enable_vad: bool
    vad_aggressiveness: int


@dataclass
class AsyncToolResponse:
    """Response for async transcription tool."""
    job_id: str
    status: str
    original_file: str
    chunks: List[Dict[str, Any]]
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "original_file": self.original_file,
            "chunks": self.chunks,
            "error": self.error,
        }


def get_tool_schema() -> Dict[str, Any]:
    """Get JSON schema for async transcription tool."""
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "inputSchema": {
            "type": "object",
            "properties": {
                "input_path": {
                    "type": "string",
                    "description": "Absolute path to source OGG audio file",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Optional output directory override",
                },
                "chunk_duration": {
                    "type": "number",
                    "description": "Target chunk duration in seconds",
                },
                "enable_vad": {
                    "type": "boolean",
                    "description": "Enable VAD-based chunking (default: true)",
                },
                "vad_aggressiveness": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 3,
                    "description": "WebRTC VAD aggressiveness (0-3)",
                },
            },
            "required": ["input_path"],
        },
    }


class TranscribeAudioAsyncTool:
    """Main tool class for transcribe-audio-async."""

    def __init__(
        self,
        config: Optional[Config] = None,
        logger: Optional[MCPLogger] = None,
        queue: Optional[AsyncQueue] = None,
        chunker: Optional[VADChunker] = None,
    ):
        self._config = config
        self._logger = logger or get_logger("transcribe_audio_async")
        self._queue = queue
        self._chunker = chunker

    @property
    def config(self) -> Config:
        if self._config is None:
            self._config = get_config()
        return self._config

    @property
    def queue(self) -> AsyncQueue:
        if self._queue is None:
            self._queue = AsyncQueue(config=self.config)
        return self._queue

    @property
    def chunker(self) -> VADChunker:
        if self._chunker is None:
            self._chunker = VADChunker(config=self.config)
        return self._chunker

    @staticmethod
    def get_schema() -> Dict[str, Any]:
        return get_tool_schema()

    def validate_input(self, arguments: Dict[str, Any]) -> AsyncToolInput:
        if "input_path" not in arguments:
            raise ToolInputError("Missing required parameter: input_path")

        input_path = arguments["input_path"]
        if not isinstance(input_path, str) or not input_path.strip():
            raise ToolInputError("input_path must be a non-empty string")

        path = Path(input_path)
        if not path.is_absolute():
            raise ToolInputError("input_path must be an absolute path")
        if not path.exists() or not path.is_file():
            raise ToolInputError("input_path does not point to a readable file")
        if path.is_symlink():
            raise ToolInputError("input_path must not be a symlink")
        if path.suffix.lower() != ".ogg":
            raise ToolInputError("input_path must point to an OGG file")

        if not self.queue.is_within_input_dir(path):
            raise ToolInputError("input_path must be within ASYNC_INPUT_DIR")

        try:
            size_bytes = path.stat().st_size
        except OSError:
            raise ToolInputError("Unable to stat input_path")

        if size_bytes <= 0:
            raise ToolInputError("input_path points to an empty file")
        if size_bytes > self.config.async_transcription.max_file_size:
            raise ToolInputError("input file exceeds ASYNC_MAX_FILE_SIZE")

        output_dir = arguments.get("output_dir")
        parsed_output_dir: Optional[Path] = None
        if output_dir is not None:
            if not isinstance(output_dir, str) or not output_dir.strip():
                raise ToolInputError("output_dir must be a non-empty string")
            parsed_output_dir = Path(output_dir)
            if not parsed_output_dir.is_absolute():
                raise ToolInputError("output_dir must be an absolute path")
            if parsed_output_dir.exists() and parsed_output_dir.is_symlink():
                raise ToolInputError("output_dir must not be a symlink")
            if (
                self.config.async_transcription.output_dir.resolve()
                not in parsed_output_dir.resolve().parents
                and parsed_output_dir.resolve()
                != self.config.async_transcription.output_dir.resolve()
            ):
                raise ToolInputError("output_dir must be within ASYNC_OUTPUT_DIR")

        chunk_duration = int(
            arguments.get("chunk_duration", self.config.async_transcription.chunk_duration)
        )
        if chunk_duration <= 0 or chunk_duration > 30:
            raise ToolInputError("chunk_duration must be between 1 and 30 seconds")

        enable_vad = arguments.get("enable_vad", True)
        if not isinstance(enable_vad, bool):
            raise ToolInputError("enable_vad must be a boolean")

        vad_aggressiveness = int(
            arguments.get("vad_aggressiveness", self.config.async_transcription.vad_aggressiveness)
        )
        if vad_aggressiveness < 0 or vad_aggressiveness > 3:
            raise ToolInputError("vad_aggressiveness must be between 0 and 3")

        return AsyncToolInput(
            input_path=path,
            output_dir=parsed_output_dir,
            chunk_duration=chunk_duration,
            enable_vad=enable_vad,
            vad_aggressiveness=vad_aggressiveness,
        )

    def execute(self, tool_input: AsyncToolInput) -> AsyncToolResponse:
        self.queue.ensure_directories()
        job_id = self._generate_job_id()

        try:
            audio, segments = self.chunker.chunk_audio(
                tool_input.input_path,
                chunk_duration=tool_input.chunk_duration,
                enable_vad=tool_input.enable_vad,
                vad_aggressiveness=tool_input.vad_aggressiveness,
            )
        except VADChunkerError as exc:
            raise ToolExecutionError(str(exc)) from exc

        duration_seconds = len(audio) / 1000.0
        if duration_seconds > self.config.async_transcription.max_duration:
            raise ToolExecutionError("audio duration exceeds ASYNC_MAX_DURATION")

        if not segments:
            segments = [ChunkSegment(start_ms=0, end_ms=len(audio))]

        input_dir = self.queue.paths.input_dir
        chunk_paths = self.chunker.export_chunks(audio, segments, input_dir, job_id)

        self._cleanup_source(tool_input.input_path, chunk_paths)

        output_dir = tool_input.output_dir or self.config.async_transcription.output_dir
        chunks = self._build_chunk_response(job_id, segments, output_dir)
        self._write_job_metadata(job_id, tool_input, chunks)

        return AsyncToolResponse(
            job_id=job_id,
            status="accepted",
            original_file=str(tool_input.input_path),
            chunks=chunks,
            error=None,
        )

    def _build_chunk_response(
        self,
        job_id: str,
        segments: List[ChunkSegment],
        output_dir: Path,
    ) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []
        use_suffix = len(segments) > 1
        for index, _ in enumerate(segments, start=1):
            if use_suffix:
                chunk_id = f"{job_id}_{index:02d}"
            else:
                chunk_id = job_id
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "status": "queued",
                    "output_path": str(output_dir / f"{chunk_id}.txt"),
                }
            )
        return chunks

    def _write_job_metadata(
        self,
        job_id: str,
        tool_input: AsyncToolInput,
        chunks: List[Dict[str, Any]],
    ) -> None:
        metadata_path = self.queue.paths.input_dir / f"{job_id}.json"
        payload = {
            "job_id": job_id,
            "original_file": str(tool_input.input_path),
            "output_dir": str(tool_input.output_dir or self.config.async_transcription.output_dir),
            "total_chunks": len(chunks),
            "chunk_ids": [chunk["chunk_id"] for chunk in chunks],
            "created_at": int(time.time()),
        }
        temp_path = metadata_path.with_suffix(".json.tmp")
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True)
        os.replace(temp_path, metadata_path)

    def _cleanup_source(self, input_path: Path, chunk_paths: List[Path]) -> None:
        try:
            if input_path in chunk_paths:
                return
            input_path.unlink(missing_ok=True)
        except Exception:
            self._logger.warning("Failed to remove source file", path=str(input_path))

    def _generate_job_id(self) -> str:
        base_id = str(int(time.time() * 1000))
        job_id = base_id
        suffix = 1
        input_dir = self.queue.paths.input_dir
        output_dir = self.queue.paths.output_dir

        while (
            any(input_dir.glob(f"{job_id}*"))
            or any(output_dir.glob(f"{job_id}*"))
        ):
            job_id = f"{base_id}-{suffix}"
            suffix += 1
        return job_id


def validate_tool_input(arguments: Dict[str, Any]) -> AsyncToolInput:
    """Convenience function to validate async tool input."""
    tool = TranscribeAudioAsyncTool()
    return tool.validate_input(arguments)
