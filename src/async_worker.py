"""
Embedded worker manager for async transcription.

Polls the async input queue and processes chunk files in parallel.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime, timezone
from pathlib import Path
import threading
import time
from typing import Dict, Optional, Set, Tuple

from src.async_output_writer import AsyncOutputWriter
from src.async_queue import AsyncQueue
from src.audio_processor import AudioProcessor
from src.config import Config, get_config
from src.logger import MCPLogger, get_logger
from src.transcriber import (
    Transcriber,
    NoSpeechDetectedError,
    TranscriptionError,
)


class AsyncWorkerManager:
    """Embedded worker manager for async transcription."""

    def __init__(
        self,
        config: Optional[Config] = None,
        logger: Optional[MCPLogger] = None,
        queue: Optional[AsyncQueue] = None,
        output_writer: Optional[AsyncOutputWriter] = None,
        audio_processor: Optional[AudioProcessor] = None,
        transcriber: Optional[Transcriber] = None,
        poll_interval: float = 0.5,
    ):
        self._config = config
        self._logger = logger or get_logger("async_worker")
        self._queue = queue
        self._output_writer = output_writer
        self._audio_processor = audio_processor
        self._transcriber = transcriber
        self._poll_interval = poll_interval

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._executor: Optional[ThreadPoolExecutor] = None
        self._lock = threading.Lock()
        self._in_flight: Set[Path] = set()
        self._job_state: Dict[str, Dict[str, int]] = {}

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
    def output_writer(self) -> AsyncOutputWriter:
        if self._output_writer is None:
            self._output_writer = AsyncOutputWriter(config=self.config)
        return self._output_writer

    @property
    def audio_processor(self) -> AudioProcessor:
        if self._audio_processor is None:
            self._audio_processor = AudioProcessor(config=self.config)
        return self._audio_processor

    @property
    def transcriber(self) -> Transcriber:
        if self._transcriber is None:
            self._transcriber = Transcriber(config=self.config)
        return self._transcriber

    def start(self) -> None:
        """Start the worker manager."""
        if self._thread and self._thread.is_alive():
            return
        self.queue.ensure_directories()
        self._executor = ThreadPoolExecutor(
            max_workers=self.config.async_transcription.parallel_chunks
        )
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        self._logger.info("Async worker manager started")

    def stop(self) -> None:
        """Stop the worker manager."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._executor:
            self._executor.shutdown(wait=True)
        self._logger.info("Async worker manager stopped")

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            self._poll_once()
            self._stop_event.wait(self._poll_interval)

    def _poll_once(self) -> None:
        if self._executor is None:
            return
        for path in self.queue.list_pending_chunks():
            with self._lock:
                if path in self._in_flight:
                    continue
                self._in_flight.add(path)
            future = self._executor.submit(self._process_chunk, path)
            future.add_done_callback(lambda f, p=path: self._on_chunk_done(p, f))

    def _on_chunk_done(self, path: Path, future: Future) -> None:
        with self._lock:
            self._in_flight.discard(path)
        if future.exception():
            self._logger.warning(
                "Chunk processing failed",
                error_type=type(future.exception()).__name__,
                chunk_path=str(path),
            )

    def _process_chunk(self, path: Path) -> None:
        job_id, chunk_id, sequence = self._parse_chunk_filename(path)
        metadata = self.queue.read_job_metadata(job_id) or {}
        total_chunks = int(metadata.get("total_chunks", 1))
        output_dir = Path(metadata.get("output_dir", self.config.async_transcription.output_dir))

        max_attempts = 2
        attempt = 0
        last_error: Optional[Exception] = None

        while attempt < max_attempts:
            attempt += 1
            try:
                audio_bytes = path.read_bytes()
                processed = self.audio_processor.process_audio(
                    audio_data=audio_bytes,
                    expected_format="ogg",
                    is_base64=False,
                )
                result = self.transcriber.transcribe_with_retry(
                    audio_data=processed.flac_data,
                    language_code=self.config.audio.default_language,
                )
                payload = {
                    "job_id": job_id,
                    "chunk_id": chunk_id,
                    "sequence": sequence,
                    "total_chunks": total_chunks,
                    "transcription": result.text,
                    "confidence": result.confidence,
                    "language_code": result.language_code,
                    "duration_seconds": processed.metadata.duration_seconds,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                    "source_file": str(path),
                }
                self.output_writer.write_result(chunk_id, payload, output_dir=output_dir)
                self._cleanup_chunk(path)
                self._record_completion(job_id, total_chunks)
                return
            except NoSpeechDetectedError:
                payload = {
                    "job_id": job_id,
                    "chunk_id": chunk_id,
                    "sequence": sequence,
                    "total_chunks": total_chunks,
                    "transcription": "",
                    "confidence": 0.0,
                    "language_code": self.config.audio.default_language,
                    "duration_seconds": 0.0,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                    "source_file": str(path),
                }
                self.output_writer.write_result(chunk_id, payload, output_dir=output_dir)
                self._cleanup_chunk(path)
                self._record_completion(job_id, total_chunks)
                return
            except TranscriptionError as exc:
                last_error = exc
            except Exception as exc:
                last_error = exc

        payload = {
            "job_id": job_id,
            "chunk_id": chunk_id,
            "sequence": sequence,
            "total_chunks": total_chunks,
            "transcription": None,
            "error": str(last_error) if last_error else "Unknown error",
            "confidence": 0.0,
            "status": "failed",
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "source_file": str(path),
        }
        self.output_writer.write_result(chunk_id, payload, output_dir=output_dir)
        self._cleanup_chunk(path)
        self._record_completion(job_id, total_chunks)

    def _cleanup_chunk(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            self._logger.warning("Failed to remove chunk file", chunk_path=str(path))

    def _record_completion(self, job_id: str, total_chunks: int) -> None:
        with self._lock:
            state = self._job_state.setdefault(job_id, {"processed": 0, "total": total_chunks})
            state["processed"] += 1
            if state["processed"] >= state["total"]:
                self._job_state.pop(job_id, None)
                metadata_path = self.queue.job_metadata_path(job_id)
                try:
                    metadata_path.unlink(missing_ok=True)
                except Exception:
                    self._logger.warning(
                        "Failed to remove job metadata",
                        job_id=job_id,
                        metadata_path=str(metadata_path),
                    )

    def _parse_chunk_filename(self, path: Path) -> Tuple[str, str, int]:
        stem = path.stem
        if "_" in stem:
            base, suffix = stem.rsplit("_", 1)
            if suffix.isdigit():
                return base, stem, int(suffix)
        return stem, stem, 1
