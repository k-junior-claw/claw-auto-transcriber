"""
Tests for transcribe-audio-async tool.
"""

import json
from pathlib import Path

from pydub import AudioSegment
import pytest

from tools.transcribe_audio_async import (
    TranscribeAudioAsyncTool,
    ToolInputError,
    get_tool_schema,
)
from src.config import Config
from src.vad_chunker import ChunkSegment


class TestAsyncToolSchema:
    """Schema tests for async tool."""

    def test_schema_has_required_fields(self):
        schema = get_tool_schema()
        assert schema["name"] == "transcribe-audio-async"
        assert "inputSchema" in schema
        assert "input_path" in schema["inputSchema"]["properties"]


class TestAsyncToolValidation:
    """Validation tests for async tool input."""

    @pytest.fixture
    def config(self, tmp_path):
        config = Config()
        config.load(validate_credentials=False)
        config.async_transcription.input_dir = tmp_path / "in"
        config.async_transcription.output_dir = tmp_path / "out"
        config.async_transcription.input_dir.mkdir(parents=True)
        return config

    def test_missing_input_path(self, config):
        tool = TranscribeAudioAsyncTool(config=config)
        with pytest.raises(ToolInputError):
            tool.validate_input({})

    def test_relative_path_rejected(self, config):
        tool = TranscribeAudioAsyncTool(config=config)
        with pytest.raises(ToolInputError):
            tool.validate_input({"input_path": "relative.ogg"})

    def test_outside_input_dir_rejected(self, config, tmp_path):
        tool = TranscribeAudioAsyncTool(config=config)
        outside = tmp_path / "outside.ogg"
        outside.write_bytes(b"OggS" + b"\x00" * 4)
        with pytest.raises(ToolInputError):
            tool.validate_input({"input_path": str(outside)})


class TestAsyncToolExecution:
    """Execution tests for async tool."""

    @pytest.fixture
    def config(self, tmp_path):
        config = Config()
        config.load(validate_credentials=False)
        config.async_transcription.input_dir = tmp_path / "in"
        config.async_transcription.output_dir = tmp_path / "out"
        config.async_transcription.input_dir.mkdir(parents=True)
        return config

    def test_execute_returns_chunk_list_and_metadata(self, config, monkeypatch, tmp_path):
        tool = TranscribeAudioAsyncTool(config=config)
        input_path = config.async_transcription.input_dir / "sample.ogg"
        input_path.write_bytes(b"OggS" + b"\x00" * 100)

        audio = AudioSegment.silent(duration=3000)
        segments = [
            ChunkSegment(start_ms=0, end_ms=1000),
            ChunkSegment(start_ms=1000, end_ms=2000),
            ChunkSegment(start_ms=2000, end_ms=3000),
        ]

        monkeypatch.setattr(tool.chunker, "chunk_audio", lambda *args, **kwargs: (audio, segments))

        def fake_export(audio_seg, segs, output_dir, job_id):
            return [output_dir / f"{job_id}_{i:02d}.ogg" for i in range(1, len(segs) + 1)]

        monkeypatch.setattr(tool.chunker, "export_chunks", fake_export)
        monkeypatch.setattr("tools.transcribe_audio_async.time.time", lambda: 1700000000.0)

        tool_input = tool.validate_input({"input_path": str(input_path)})
        response = tool.execute(tool_input)

        assert response.status == "accepted"
        assert response.job_id == "1700000000000"
        assert len(response.chunks) == 3

        metadata_path = config.async_transcription.input_dir / f"{response.job_id}.json"
        assert metadata_path.exists()
        metadata = json.loads(metadata_path.read_text())
        assert metadata["total_chunks"] == 3
        assert response.chunks[0]["output_path"].endswith(".txt")
