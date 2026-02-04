"""
Tests for async output writer.
"""

import json

import pytest

from src.async_output_writer import AsyncOutputWriter
from src.config import Config


class TestAsyncOutputWriter:
    """Tests for AsyncOutputWriter."""

    @pytest.fixture
    def config(self, tmp_path):
        config = Config()
        config.load(validate_credentials=False)
        config.async_transcription.output_dir = tmp_path / "out"
        return config

    def test_write_result_creates_file(self, config):
        writer = AsyncOutputWriter(config=config)
        payload = {
            "job_id": "123",
            "chunk_id": "123_01",
            "sequence": 1,
            "total_chunks": 1,
            "transcription": "hello",
            "confidence": 0.9,
        }

        output_path = writer.write_result("123_01", payload)

        assert output_path.exists()
        assert output_path.name == "123_01.txt"

        data = json.loads(output_path.read_text())
        assert data["job_id"] == "123"
        assert data["chunk_id"] == "123_01"
