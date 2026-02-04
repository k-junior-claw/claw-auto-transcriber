"""
Tests for VAD chunker behavior.
"""

from pathlib import Path

from pydub import AudioSegment

from src.vad_chunker import VADChunker, ChunkSegment
import src.vad_chunker as vad_chunker_module


def test_time_based_chunking(monkeypatch, tmp_path):
    chunker = VADChunker()
    audio = AudioSegment.silent(duration=25000)  # 25s

    monkeypatch.setattr(chunker, "load_audio", lambda _: audio)

    _, segments = chunker.chunk_audio(tmp_path / "sample.ogg", chunk_duration=10, enable_vad=False)

    assert len(segments) == 3
    assert segments[0].duration_seconds == 10.0
    assert segments[1].duration_seconds == 10.0
    assert segments[2].duration_seconds == 5.0


def test_vad_fallback_to_time_based(monkeypatch, tmp_path):
    chunker = VADChunker()
    audio = AudioSegment.silent(duration=3000)

    monkeypatch.setattr(chunker, "load_audio", lambda _: audio)
    monkeypatch.setattr(vad_chunker_module, "WEBRTCVAD_AVAILABLE", False)

    _, segments = chunker.chunk_audio(tmp_path / "sample.ogg", chunk_duration=2, enable_vad=True)

    assert len(segments) == 2
    assert segments[0].duration_seconds == 2.0
    assert segments[1].duration_seconds == 1.0


def test_merge_to_target():
    chunker = VADChunker()
    segments = [
        ChunkSegment(start_ms=0, end_ms=4000),
        ChunkSegment(start_ms=4000, end_ms=8000),
        ChunkSegment(start_ms=8000, end_ms=12000),
    ]

    merged = chunker._merge_to_target(segments, target_chunk_ms=10000, max_chunk_ms=15000)

    assert len(merged) == 1
    assert merged[0].duration_seconds == 12.0
