"""
Tests for async worker manager processing.
"""

import json

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.async_worker import AsyncWorkerManager
from src.async_queue import AsyncQueue
from src.async_output_writer import AsyncOutputWriter
from src.audio_processor import ProcessedAudio, AudioMetadata
from src.config import Config
from src.transcriber import TranscriptionResult, TranscriptionError, NoSpeechDetectedError


@pytest.fixture
def config(tmp_path):
    config = Config()
    config.load(validate_credentials=False)
    config.async_transcription.input_dir = tmp_path / "in"
    config.async_transcription.output_dir = tmp_path / "out"
    config.async_transcription.input_dir.mkdir(parents=True)
    return config


def _write_chunk(path: Path) -> None:
    path.write_bytes(b"OggS" + b"\x00" * 10)


def test_process_chunk_success(config):
    queue = AsyncQueue(config=config)
    output_writer = AsyncOutputWriter(config=config)

    chunk_path = config.async_transcription.input_dir / "job123_01.ogg"
    _write_chunk(chunk_path)
    queue.write_job_metadata(
        "job123",
        {
            "job_id": "job123",
            "total_chunks": 1,
            "output_dir": str(config.async_transcription.output_dir),
        },
    )

    audio_processor = MagicMock()
    audio_processor.process_audio.return_value = ProcessedAudio(
        flac_data=b"fLaC",
        metadata=AudioMetadata(
            format="ogg",
            duration_seconds=1.0,
            sample_rate=16000,
            channels=1,
            size_bytes=100,
        ),
        original_format="ogg",
    )
    transcriber = MagicMock()
    transcriber.transcribe_with_retry.return_value = TranscriptionResult(
        text="hello",
        confidence=0.9,
        language_code="en-US",
        duration_seconds=1.0,
    )

    manager = AsyncWorkerManager(
        config=config,
        queue=queue,
        output_writer=output_writer,
        audio_processor=audio_processor,
        transcriber=transcriber,
    )

    manager._process_chunk(chunk_path)

    output_path = config.async_transcription.output_dir / "job123_01.txt"
    assert output_path.exists()
    payload = json.loads(output_path.read_text())
    assert payload["transcription"] == "hello"
    assert payload["chunk_id"] == "job123_01"
    assert not chunk_path.exists()


def test_process_chunk_no_speech(config):
    queue = AsyncQueue(config=config)
    output_writer = AsyncOutputWriter(config=config)

    chunk_path = config.async_transcription.input_dir / "job999.ogg"
    _write_chunk(chunk_path)
    queue.write_job_metadata(
        "job999",
        {
            "job_id": "job999",
            "total_chunks": 1,
            "output_dir": str(config.async_transcription.output_dir),
        },
    )

    audio_processor = MagicMock()
    audio_processor.process_audio.return_value = ProcessedAudio(
        flac_data=b"fLaC",
        metadata=AudioMetadata(
            format="ogg",
            duration_seconds=1.0,
            sample_rate=16000,
            channels=1,
            size_bytes=100,
        ),
        original_format="ogg",
    )
    transcriber = MagicMock()
    transcriber.transcribe_with_retry.side_effect = NoSpeechDetectedError("no speech")

    manager = AsyncWorkerManager(
        config=config,
        queue=queue,
        output_writer=output_writer,
        audio_processor=audio_processor,
        transcriber=transcriber,
    )

    manager._process_chunk(chunk_path)

    output_path = config.async_transcription.output_dir / "job999.txt"
    assert output_path.exists()
    payload = json.loads(output_path.read_text())
    assert payload["transcription"] == ""


def test_process_chunk_failure(config):
    queue = AsyncQueue(config=config)
    output_writer = AsyncOutputWriter(config=config)

    chunk_path = config.async_transcription.input_dir / "jobfail_01.ogg"
    _write_chunk(chunk_path)
    queue.write_job_metadata(
        "jobfail",
        {
            "job_id": "jobfail",
            "total_chunks": 1,
            "output_dir": str(config.async_transcription.output_dir),
        },
    )

    audio_processor = MagicMock()
    audio_processor.process_audio.return_value = ProcessedAudio(
        flac_data=b"fLaC",
        metadata=AudioMetadata(
            format="ogg",
            duration_seconds=1.0,
            sample_rate=16000,
            channels=1,
            size_bytes=100,
        ),
        original_format="ogg",
    )
    transcriber = MagicMock()
    transcriber.transcribe_with_retry.side_effect = TranscriptionError("failure")

    manager = AsyncWorkerManager(
        config=config,
        queue=queue,
        output_writer=output_writer,
        audio_processor=audio_processor,
        transcriber=transcriber,
    )

    manager._process_chunk(chunk_path)

    output_path = config.async_transcription.output_dir / "jobfail_01.txt"
    assert output_path.exists()
    payload = json.loads(output_path.read_text())
    assert payload["status"] == "failed"
    assert payload["transcription"] is None
