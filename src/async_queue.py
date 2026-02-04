"""
Async queue utilities for transcribe-audio-async.

Handles:
- Queue directory creation
- Listing pending chunk files
- Path safety checks for async input
"""

from dataclasses import dataclass
from pathlib import Path
import os
import json
from typing import Any, Dict, List, Optional

from src.config import Config, get_config
from src.logger import MCPLogger, get_logger


class AsyncQueueError(Exception):
    """Raised when async queue operations fail."""


@dataclass
class AsyncQueuePaths:
    """Paths for async input/output queues."""
    input_dir: Path
    output_dir: Path


def _chmod_if_posix(path: Path, mode: int) -> None:
    """Best-effort chmod for POSIX environments."""
    if os.name != "posix":
        return
    try:
        path.chmod(mode)
    except Exception:
        pass


class AsyncQueue:
    """Filesystem queue helper for async transcription."""

    def __init__(self, config: Optional[Config] = None, logger: Optional[MCPLogger] = None):
        self._config = config
        self._logger = logger or get_logger("async_queue")

    @property
    def config(self) -> Config:
        if self._config is None:
            self._config = get_config()
        return self._config

    @property
    def paths(self) -> AsyncQueuePaths:
        return AsyncQueuePaths(
            input_dir=self.config.async_transcription.input_dir,
            output_dir=self.config.async_transcription.output_dir,
        )

    def ensure_directories(self) -> AsyncQueuePaths:
        """Ensure input/output queue directories exist."""
        paths = self.paths
        paths.input_dir.mkdir(parents=True, exist_ok=True)
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        _chmod_if_posix(paths.input_dir, 0o700)
        _chmod_if_posix(paths.output_dir, 0o700)
        return paths

    def list_pending_chunks(self) -> List[Path]:
        """List pending chunk files in the input queue."""
        paths = self.paths
        if not paths.input_dir.exists():
            return []
        return sorted(paths.input_dir.glob("*.ogg"))

    def job_metadata_path(self, job_id: str) -> Path:
        """Return the metadata file path for a job."""
        return self.paths.input_dir / f"{job_id}.json"

    def write_job_metadata(self, job_id: str, payload: Dict[str, Any]) -> Path:
        """Write job metadata to the input queue."""
        self.ensure_directories()
        metadata_path = self.job_metadata_path(job_id)
        temp_path = metadata_path.with_suffix(".json.tmp")
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True)
        os.replace(temp_path, metadata_path)
        return metadata_path

    def read_job_metadata(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Read job metadata if present."""
        metadata_path = self.job_metadata_path(job_id)
        if not metadata_path.exists():
            return None
        try:
            with open(metadata_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            return None

    def is_within_input_dir(self, path: Path) -> bool:
        """Return True if path is within the configured input directory."""
        try:
            input_root = self.paths.input_dir.resolve()
            return input_root in path.resolve().parents
        except Exception:
            return False
