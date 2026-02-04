"""
Async output writer for transcribe-audio-async.

Writes JSON result files to the output queue with atomic rename.
"""

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from src.config import Config, get_config
from src.logger import MCPLogger, get_logger


class AsyncOutputWriterError(Exception):
    """Raised when async output writing fails."""


def _chmod_if_posix(path: Path, mode: int) -> None:
    """Best-effort chmod for POSIX environments."""
    if os.name != "posix":
        return
    try:
        path.chmod(mode)
    except Exception:
        pass


class AsyncOutputWriter:
    """Write async transcription results to output queue."""

    def __init__(self, config: Optional[Config] = None, logger: Optional[MCPLogger] = None):
        self._config = config
        self._logger = logger or get_logger("async_output_writer")

    @property
    def config(self) -> Config:
        if self._config is None:
            self._config = get_config()
        return self._config

    @property
    def output_dir(self) -> Path:
        return self.config.async_transcription.output_dir

    def ensure_output_dir(self) -> Path:
        """Ensure output directory exists."""
        output_dir = self.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        _chmod_if_posix(output_dir, 0o700)
        return output_dir

    def write_result(self, chunk_id: str, payload: Dict[str, Any]) -> Path:
        """Write a result file atomically for the given chunk ID."""
        output_dir = self.ensure_output_dir()
        final_path = output_dir / f"{chunk_id}.txt"
        temp_name = f".{chunk_id}.{uuid.uuid4().hex}.tmp"
        temp_path = output_dir / temp_name

        try:
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=True)
            os.replace(temp_path, final_path)
            _chmod_if_posix(final_path, 0o600)
            return final_path
        except Exception as exc:
            self._logger.error("Failed to write async output", error_type=type(exc).__name__)
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
            raise AsyncOutputWriterError("Failed to write output file") from exc
