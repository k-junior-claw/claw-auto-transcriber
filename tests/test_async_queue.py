"""
Tests for async queue utilities.
"""

from pathlib import Path

import pytest

from src.async_queue import AsyncQueue
from src.config import Config


class TestAsyncQueue:
    """Tests for AsyncQueue."""

    @pytest.fixture
    def config(self, tmp_path):
        config = Config()
        config.load(validate_credentials=False)
        config.async_transcription.input_dir = tmp_path / "in"
        config.async_transcription.output_dir = tmp_path / "out"
        return config

    def test_ensure_directories(self, config):
        queue = AsyncQueue(config=config)

        paths = queue.ensure_directories()

        assert paths.input_dir.exists()
        assert paths.output_dir.exists()
        assert paths.input_dir.is_dir()
        assert paths.output_dir.is_dir()

    def test_list_pending_chunks(self, config):
        queue = AsyncQueue(config=config)
        paths = queue.ensure_directories()

        (paths.input_dir / "job_02.ogg").write_bytes(b"OggS" + b"\x00" * 4)
        (paths.input_dir / "job_01.ogg").write_bytes(b"OggS" + b"\x00" * 4)

        files = queue.list_pending_chunks()

        assert [path.name for path in files] == ["job_01.ogg", "job_02.ogg"]

    def test_is_within_input_dir(self, config):
        queue = AsyncQueue(config=config)
        paths = queue.ensure_directories()

        inside = paths.input_dir / "sample.ogg"
        inside.write_bytes(b"OggS" + b"\x00" * 4)
        outside = paths.output_dir / "outside.ogg"

        assert queue.is_within_input_dir(inside) is True
        assert queue.is_within_input_dir(outside) is False
