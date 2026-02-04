"""
VAD-based chunker for async transcription.

Uses WebRTC VAD to identify speech segments and produce chunk boundaries.
Falls back to time-based chunking if VAD is disabled or unavailable.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
import math

from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

from src.config import Config, get_config
from src.logger import MCPLogger, get_logger

try:
    import webrtcvad
    WEBRTCVAD_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised in tests via flags
    WEBRTCVAD_AVAILABLE = False
    webrtcvad = None  # type: ignore


class VADChunkerError(Exception):
    """Raised when VAD chunking fails."""


@dataclass
class ChunkSegment:
    """Represents a chunk segment in milliseconds."""
    start_ms: int
    end_ms: int

    @property
    def duration_seconds(self) -> float:
        return max(0.0, (self.end_ms - self.start_ms) / 1000.0)


class VADChunker:
    """Chunker that uses WebRTC VAD for speech segmentation."""

    def __init__(self, config: Optional[Config] = None, logger: Optional[MCPLogger] = None):
        self._config = config
        self._logger = logger or get_logger("vad_chunker")

    @property
    def config(self) -> Config:
        if self._config is None:
            self._config = get_config()
        return self._config

    def load_audio(self, input_path: Path) -> AudioSegment:
        """Load audio from disk using pydub."""
        if not input_path.exists():
            raise VADChunkerError("Input file not found")
        if not input_path.is_file():
            raise VADChunkerError("Input path is not a file")

        try:
            format_hint = input_path.suffix.lstrip(".") or None
            return AudioSegment.from_file(input_path, format=format_hint)
        except CouldntDecodeError as exc:
            raise VADChunkerError("Failed to decode input audio") from exc
        except Exception as exc:
            raise VADChunkerError(f"Failed to load audio: {type(exc).__name__}") from exc

    def chunk_audio(
        self,
        input_path: Path,
        chunk_duration: int,
        enable_vad: bool = True,
        vad_aggressiveness: Optional[int] = None,
    ) -> Tuple[AudioSegment, List[ChunkSegment]]:
        """Load and chunk audio, returning the segment and chunk list."""
        audio = self.load_audio(input_path)
        if chunk_duration <= 0:
            raise VADChunkerError("chunk_duration must be positive")

        if enable_vad and WEBRTCVAD_AVAILABLE:
            aggressiveness = (
                vad_aggressiveness
                if vad_aggressiveness is not None
                else self.config.async_transcription.vad_aggressiveness
            )
            segments = self._build_vad_segments(audio, aggressiveness, chunk_duration)
            if segments:
                return audio, segments

        # Fallback to time-based chunking
        return audio, self._build_time_segments(audio, chunk_duration)

    def _build_time_segments(self, audio: AudioSegment, chunk_duration: int) -> List[ChunkSegment]:
        total_ms = len(audio)
        chunk_ms = int(chunk_duration * 1000)
        segments: List[ChunkSegment] = []
        if chunk_ms <= 0 or total_ms <= 0:
            return segments
        for start in range(0, total_ms, chunk_ms):
            end = min(start + chunk_ms, total_ms)
            segments.append(ChunkSegment(start_ms=start, end_ms=end))
        return segments

    def _build_vad_segments(
        self,
        audio: AudioSegment,
        aggressiveness: int,
        chunk_duration: int,
    ) -> List[ChunkSegment]:
        if not WEBRTCVAD_AVAILABLE:
            return []

        if not (0 <= aggressiveness <= 3):
            raise VADChunkerError("VAD aggressiveness must be between 0 and 3")

        min_speech_ms = 500
        min_silence_ms = 300
        target_chunk_ms = int(chunk_duration * 1000)
        max_chunk_ms = int(max(15, chunk_duration) * 1000)

        pcm_audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)
        raw = pcm_audio.raw_data
        frame_ms = 30
        frame_size = int(16000 * 2 * frame_ms / 1000)
        if frame_size <= 0:
            return []

        vad = webrtcvad.Vad(aggressiveness)
        speech_segments: List[ChunkSegment] = []
        in_speech = False
        speech_start_ms = 0

        total_frames = len(raw) // frame_size
        for index in range(total_frames):
            start = index * frame_size
            frame = raw[start:start + frame_size]
            timestamp_ms = index * frame_ms
            is_speech = vad.is_speech(frame, 16000)

            if is_speech and not in_speech:
                in_speech = True
                speech_start_ms = timestamp_ms
            elif not is_speech and in_speech:
                in_speech = False
                speech_end_ms = timestamp_ms
                if speech_end_ms - speech_start_ms >= min_speech_ms:
                    speech_segments.append(
                        ChunkSegment(start_ms=speech_start_ms, end_ms=speech_end_ms)
                    )

        if in_speech:
            speech_end_ms = total_frames * frame_ms
            if speech_end_ms - speech_start_ms >= min_speech_ms:
                speech_segments.append(
                    ChunkSegment(start_ms=speech_start_ms, end_ms=speech_end_ms)
                )

        if not speech_segments:
            return []

        merged = self._merge_segments(speech_segments, min_silence_ms)
        expanded = self._split_long_segments(merged, max_chunk_ms, target_chunk_ms)
        return self._merge_to_target(expanded, target_chunk_ms, max_chunk_ms)

    def _merge_segments(
        self,
        segments: List[ChunkSegment],
        min_silence_ms: int,
    ) -> List[ChunkSegment]:
        merged: List[ChunkSegment] = []
        current = segments[0]
        for segment in segments[1:]:
            gap = segment.start_ms - current.end_ms
            if gap <= min_silence_ms:
                current = ChunkSegment(start_ms=current.start_ms, end_ms=segment.end_ms)
            else:
                merged.append(current)
                current = segment
        merged.append(current)
        return merged

    def _split_long_segments(
        self,
        segments: List[ChunkSegment],
        max_chunk_ms: int,
        target_chunk_ms: int,
    ) -> List[ChunkSegment]:
        split_segments: List[ChunkSegment] = []
        for segment in segments:
            duration_ms = segment.end_ms - segment.start_ms
            if duration_ms <= max_chunk_ms:
                split_segments.append(segment)
                continue

            chunk_count = max(1, math.ceil(duration_ms / target_chunk_ms))
            for index in range(chunk_count):
                start = segment.start_ms + index * target_chunk_ms
                end = min(start + target_chunk_ms, segment.end_ms)
                split_segments.append(ChunkSegment(start_ms=start, end_ms=end))
        return split_segments

    def _merge_to_target(
        self,
        segments: List[ChunkSegment],
        target_chunk_ms: int,
        max_chunk_ms: int,
    ) -> List[ChunkSegment]:
        merged: List[ChunkSegment] = []
        current: Optional[ChunkSegment] = None
        for segment in segments:
            if current is None:
                current = segment
                continue

            proposed_end = segment.end_ms
            proposed_duration = proposed_end - current.start_ms

            if proposed_duration <= max_chunk_ms:
                current = ChunkSegment(start_ms=current.start_ms, end_ms=proposed_end)
                if proposed_duration >= target_chunk_ms:
                    merged.append(current)
                    current = None
            else:
                merged.append(current)
                current = segment

        if current is not None:
            merged.append(current)
        return merged

    def export_chunks(
        self,
        audio: AudioSegment,
        segments: List[ChunkSegment],
        output_dir: Path,
        job_id: str,
    ) -> List[Path]:
        """Export chunks to the output directory."""
        output_dir.mkdir(parents=True, exist_ok=True)
        use_suffix = len(segments) > 1
        paths: List[Path] = []
        for index, segment in enumerate(segments, start=1):
            chunk_audio = audio[segment.start_ms:segment.end_ms]
            if use_suffix:
                name = f"{job_id}_{index:02d}.ogg"
            else:
                name = f"{job_id}.ogg"
            path = output_dir / name
            chunk_audio.export(path, format="ogg")
            paths.append(path)
        return paths
