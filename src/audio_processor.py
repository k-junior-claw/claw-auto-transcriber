"""
Audio Processor Module for Claw Auto-Transcriber MCP Server.

Handles:
- Audio format validation (OGG, MP3, WAV, FLAC)
- Audio conversion to FLAC for Google STT
- Duration and size validation
- Ephemeral file handling with automatic cleanup
- Privacy-preserving processing (no content logging)

CRITICAL SECURITY NOTES:
1. Audio content is NEVER logged
2. Temporary files are cleaned up IMMEDIATELY after processing
3. All audio data is treated as sensitive and ephemeral
"""

import base64
import io
import os
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, BinaryIO, Generator
import struct

from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

from src.config import get_config, Config
from src.logger import get_logger, MCPLogger

# Optional soundfile fallback for when ffmpeg is not available
try:
    import soundfile as sf
    import numpy as np
    from scipy import signal
    SOUNDFILE_AVAILABLE = True
except ImportError:
    SOUNDFILE_AVAILABLE = False


# Audio format signatures (magic bytes)
AUDIO_SIGNATURES = {
    "ogg": [b"OggS"],
    "mp3": [b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"ID3"],
    "wav": [b"RIFF"],
    "flac": [b"fLaC"],
}

# MIME type mappings
MIME_TO_FORMAT = {
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
}


class AudioProcessingError(Exception):
    """Base exception for audio processing errors."""
    pass


class AudioValidationError(AudioProcessingError):
    """Raised when audio validation fails."""
    pass


class AudioConversionError(AudioProcessingError):
    """Raised when audio conversion fails."""
    pass


class AudioDurationError(AudioProcessingError):
    """Raised when audio duration exceeds limits."""
    pass


class AudioSizeError(AudioProcessingError):
    """Raised when audio size exceeds limits."""
    pass


class AudioFormatError(AudioProcessingError):
    """Raised when audio format is not supported."""
    pass


@dataclass
class AudioMetadata:
    """Metadata extracted from audio file."""
    format: str
    duration_seconds: float
    sample_rate: int
    channels: int
    size_bytes: int
    
    def to_dict(self) -> dict:
        """Convert to dictionary (safe for logging)."""
        return {
            "format": self.format,
            "duration_seconds": round(self.duration_seconds, 2),
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "size_bytes": self.size_bytes,
        }


@dataclass
class ProcessedAudio:
    """Result of audio processing."""
    flac_data: bytes
    metadata: AudioMetadata
    original_format: str
    
    def __del__(self):
        """Securely clear audio data on deletion."""
        # Overwrite the bytes data for security
        if hasattr(self, 'flac_data') and self.flac_data:
            # Note: This doesn't guarantee secure deletion due to Python's memory management
            # but is a best-effort approach
            self.flac_data = b''


class EphemeralFileManager:
    """
    Manages temporary files with guaranteed cleanup.
    
    Ensures all temporary audio files are deleted immediately after use,
    even in case of errors.
    """
    
    def __init__(self, temp_dir: Optional[Path] = None, logger: Optional[MCPLogger] = None):
        """
        Initialize the file manager.
        
        Args:
            temp_dir: Directory for temporary files
            logger: Optional logger instance
        """
        self._temp_dir = temp_dir
        self._logger = logger or get_logger("ephemeral_file_manager")
        self._active_files: set = set()
    
    @property
    def temp_dir(self) -> Path:
        """Get or create the temporary directory."""
        if self._temp_dir is None:
            try:
                config = get_config()
                self._temp_dir = config.audio.temp_dir
            except Exception:
                self._temp_dir = Path(tempfile.gettempdir()) / "claw_transcriber"
        
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        return self._temp_dir
    
    def _generate_filename(self, extension: str) -> Path:
        """Generate a unique temporary filename."""
        unique_id = uuid.uuid4().hex[:12]
        return self.temp_dir / f"audio_{unique_id}.{extension}"
    
    @contextmanager
    def temp_file(self, extension: str, data: Optional[bytes] = None) -> Generator[Path, None, None]:
        """
        Context manager for temporary file handling.
        
        Guarantees the file is deleted after the context exits,
        even if an exception occurs.
        
        Args:
            extension: File extension (e.g., "ogg", "flac")
            data: Optional initial data to write to the file
        
        Yields:
            Path to the temporary file
        """
        file_path = self._generate_filename(extension)
        self._active_files.add(file_path)
        
        try:
            # Write initial data if provided
            if data:
                file_path.write_bytes(data)
            
            yield file_path
        finally:
            self._cleanup_file(file_path)
    
    def _cleanup_file(self, file_path: Path) -> None:
        """
        Securely delete a temporary file.
        
        Attempts to overwrite the file with zeros before deletion
        for enhanced security.
        """
        try:
            if file_path.exists():
                # Overwrite with zeros before deletion (best-effort security)
                try:
                    size = file_path.stat().st_size
                    if size > 0:
                        with open(file_path, 'wb') as f:
                            # Write zeros in chunks to handle large files
                            chunk_size = min(size, 1024 * 1024)  # 1MB chunks
                            zeros = b'\x00' * chunk_size
                            remaining = size
                            while remaining > 0:
                                write_size = min(remaining, chunk_size)
                                f.write(zeros[:write_size])
                                remaining -= write_size
                except Exception:
                    pass  # Continue with deletion even if overwrite fails
                
                file_path.unlink()
                self._logger.debug(
                    "Temporary file cleaned up",
                    file_extension=file_path.suffix
                )
        except Exception as e:
            self._logger.warning(
                "Failed to cleanup temporary file",
                error_type=type(e).__name__
            )
        finally:
            self._active_files.discard(file_path)
    
    def cleanup_all(self) -> int:
        """
        Clean up all active temporary files.
        
        Returns:
            Number of files cleaned up
        """
        count = 0
        for file_path in list(self._active_files):
            self._cleanup_file(file_path)
            count += 1
        return count


class AudioProcessor:
    """
    Main audio processing class.
    
    Handles validation, conversion, and metadata extraction for audio files
    intended for Google Cloud Speech-to-Text transcription.
    
    Usage:
        processor = AudioProcessor()
        
        # Process base64 audio
        result = processor.process_audio(base64_audio_data, "ogg")
        
        # Access FLAC data for STT
        flac_bytes = result.flac_data
        duration = result.metadata.duration_seconds
    """
    
    def __init__(self, config: Optional[Config] = None, logger: Optional[MCPLogger] = None):
        """
        Initialize the audio processor.
        
        Args:
            config: Optional configuration instance
            logger: Optional logger instance
        """
        self._config = config
        self._logger = logger or get_logger("audio_processor")
        self._file_manager = EphemeralFileManager(logger=self._logger)
    
    @property
    def config(self) -> Config:
        """Get configuration."""
        if self._config is None:
            self._config = get_config()
        return self._config
    
    def detect_format(self, audio_bytes: bytes) -> Optional[str]:
        """
        Detect audio format from magic bytes.
        
        Args:
            audio_bytes: Raw audio data
        
        Returns:
            Format string (e.g., "ogg") or None if unknown
        """
        if len(audio_bytes) < 4:
            return None
        
        header = audio_bytes[:12]  # Read first 12 bytes for detection
        
        for format_name, signatures in AUDIO_SIGNATURES.items():
            for sig in signatures:
                if header.startswith(sig):
                    return format_name
        
        return None
    
    def validate_format(self, audio_bytes: bytes, expected_format: Optional[str] = None) -> str:
        """
        Validate audio format.
        
        Args:
            audio_bytes: Raw audio data
            expected_format: Optional expected format
        
        Returns:
            Detected format string
        
        Raises:
            AudioFormatError: If format is invalid or unsupported
        """
        detected = self.detect_format(audio_bytes)
        
        if detected is None:
            raise AudioFormatError("Unable to detect audio format from file header")
        
        if not self.config.is_format_supported(detected):
            raise AudioFormatError(
                f"Unsupported audio format: {detected}. "
                f"Supported formats: {', '.join(self.config.audio.supported_formats)}"
            )
        
        if expected_format and expected_format.lower() != detected:
            self._logger.warning(
                "Format mismatch",
                expected=expected_format,
                detected=detected
            )
        
        return detected
    
    def validate_size(self, audio_bytes: bytes) -> int:
        """
        Validate audio file size.
        
        Args:
            audio_bytes: Raw audio data
        
        Returns:
            Size in bytes
        
        Raises:
            AudioSizeError: If size exceeds limits
        """
        size = len(audio_bytes)
        max_size = self.config.audio.max_size
        
        if size == 0:
            raise AudioValidationError("Audio file is empty")
        
        if size > max_size:
            raise AudioSizeError(
                f"Audio file size ({size} bytes) exceeds maximum "
                f"({max_size} bytes / {max_size / 1024 / 1024:.1f}MB)"
            )
        
        return size
    
    def get_duration(self, audio_segment: AudioSegment) -> float:
        """
        Get audio duration in seconds.
        
        Args:
            audio_segment: pydub AudioSegment
        
        Returns:
            Duration in seconds
        
        Raises:
            AudioDurationError: If duration exceeds limits
        """
        duration_ms = len(audio_segment)
        duration_seconds = duration_ms / 1000.0
        max_duration = self.config.audio.max_duration
        
        if duration_seconds > max_duration:
            raise AudioDurationError(
                f"Audio duration ({duration_seconds:.1f}s) exceeds maximum "
                f"({max_duration}s)"
            )
        
        return duration_seconds
    
    def _load_audio_segment(self, audio_bytes: bytes, format: str) -> AudioSegment:
        """
        Load audio bytes into a pydub AudioSegment.
        
        Args:
            audio_bytes: Raw audio data
            format: Audio format
        
        Returns:
            AudioSegment instance
        
        Raises:
            AudioConversionError: If loading fails
        """
        try:
            # Create in-memory file for pydub
            audio_io = io.BytesIO(audio_bytes)
            
            # Load using pydub
            segment = AudioSegment.from_file(audio_io, format=format)
            return segment
            
        except CouldntDecodeError as e:
            # Try soundfile fallback for OGG files when ffmpeg is not available
            if format.lower() == "ogg" and SOUNDFILE_AVAILABLE:
                self._logger.debug("pydub failed, trying soundfile fallback")
                return self._load_audio_segment_with_soundfile(audio_bytes, format)
            raise AudioConversionError(f"Failed to decode {format} audio: corrupted or invalid file")
        except Exception as e:
            # Try soundfile fallback for OGG files when ffmpeg is not available
            if format.lower() == "ogg" and SOUNDFILE_AVAILABLE:
                self._logger.debug("pydub failed, trying soundfile fallback")
                return self._load_audio_segment_with_soundfile(audio_bytes, format)
            raise AudioConversionError(f"Failed to load audio: {type(e).__name__}")

    def _load_audio_segment_with_soundfile(self, audio_bytes: bytes, format: str) -> AudioSegment:
        """
        Load audio bytes using soundfile as fallback when pydub/ffmpeg fails.
        
        Args:
            audio_bytes: Raw audio data
            format: Audio format
        
        Returns:
            AudioSegment instance
        
        Raises:
            AudioConversionError: If loading fails
        """
        if not SOUNDFILE_AVAILABLE:
            raise AudioConversionError("soundfile not available for fallback conversion")
        
        try:
            import io
            
            # Read audio using soundfile
            audio_io = io.BytesIO(audio_bytes)
            data, samplerate = sf.read(audio_io)
            
            self._logger.debug(
                "Loaded audio with soundfile",
                sample_rate=samplerate,
                channels=len(data.shape) if len(data.shape) > 1 else 1
            )
            
            # Convert to mono if stereo
            if len(data.shape) > 1:
                data = data.mean(axis=1)
            
            # Resample to 16kHz for Google STT if needed
            if samplerate != 16000:
                num_samples = int(len(data) * 16000 / samplerate)
                data = signal.resample(data, num_samples)
                samplerate = 16000
            
            # Convert float to int16
            data = (data * 32767).astype(np.int16)
            
            # Create AudioSegment from raw data
            segment = AudioSegment(
                data.tobytes(),
                frame_rate=samplerate,
                sample_width=2,  # 16-bit = 2 bytes
                channels=1
            )
            
            return segment
            
        except Exception as e:
            raise AudioConversionError(f"soundfile fallback failed: {type(e).__name__}: {e}")
    
    def convert_to_flac(self, audio_segment: AudioSegment) -> bytes:
        """
        Convert AudioSegment to FLAC format.
        
        FLAC is the preferred format for Google Cloud Speech-to-Text
        as it provides lossless audio compression.
        
        Args:
            audio_segment: pydub AudioSegment
        
        Returns:
            FLAC audio data as bytes
        
        Raises:
            AudioConversionError: If conversion fails
        """
        try:
            # Google STT works best with mono audio at 16kHz
            # Convert to mono and resample if needed
            audio = audio_segment.set_channels(1)
            
            # Resample to 16kHz for optimal STT performance
            if audio.frame_rate != 16000:
                audio = audio.set_frame_rate(16000)
            
            # Export to FLAC
            output = io.BytesIO()
            audio.export(output, format="flac")
            return output.getvalue()
            
        except Exception as e:
            raise AudioConversionError(f"Failed to convert to FLAC: {type(e).__name__}")
    
    def extract_metadata(self, audio_segment: AudioSegment, original_format: str, size_bytes: int) -> AudioMetadata:
        """
        Extract metadata from an AudioSegment.
        
        Args:
            audio_segment: pydub AudioSegment
            original_format: Original audio format
            size_bytes: Original file size
        
        Returns:
            AudioMetadata instance
        """
        return AudioMetadata(
            format=original_format,
            duration_seconds=len(audio_segment) / 1000.0,
            sample_rate=audio_segment.frame_rate,
            channels=audio_segment.channels,
            size_bytes=size_bytes
        )
    
    def validate_audio(self, audio_bytes: bytes, expected_format: Optional[str] = None) -> Tuple[str, int]:
        """
        Validate audio bytes (format and size).
        
        Args:
            audio_bytes: Raw audio data
            expected_format: Optional expected format
        
        Returns:
            Tuple of (detected_format, size_bytes)
        
        Raises:
            AudioValidationError: If validation fails
        """
        size = self.validate_size(audio_bytes)
        format = self.validate_format(audio_bytes, expected_format)
        return format, size
    
    def process_audio(
        self,
        audio_data: str | bytes,
        expected_format: Optional[str] = None,
        is_base64: bool = True
    ) -> ProcessedAudio:
        """
        Process audio data for transcription.
        
        This is the main entry point for audio processing. It:
        1. Decodes base64 if needed
        2. Validates format and size
        3. Loads and validates duration
        4. Converts to FLAC format
        5. Extracts metadata
        
        Args:
            audio_data: Audio data (base64 string or raw bytes)
            expected_format: Optional expected format (e.g., "ogg")
            is_base64: Whether the input is base64 encoded
        
        Returns:
            ProcessedAudio with FLAC data and metadata
        
        Raises:
            AudioProcessingError: If processing fails
        """
        with self._logger.timed_operation("process_audio"):
            # Decode base64 if needed
            if is_base64:
                if isinstance(audio_data, str):
                    try:
                        audio_bytes = base64.b64decode(audio_data)
                    except Exception:
                        raise AudioValidationError("Invalid base64 encoding")
                else:
                    raise AudioValidationError("Expected base64 string but received bytes")
            else:
                audio_bytes = audio_data if isinstance(audio_data, bytes) else audio_data.encode()
            
            # Validate format and size
            detected_format, size = self.validate_audio(audio_bytes, expected_format)
            
            self._logger.debug(
                "Audio validated",
                detected_format=detected_format,
                size_bytes=size
            )
            
            # Load audio segment
            audio_segment = self._load_audio_segment(audio_bytes, detected_format)
            
            # Validate duration
            duration = self.get_duration(audio_segment)
            
            self._logger.debug(
                "Audio loaded",
                duration_seconds=round(duration, 2),
                sample_rate=audio_segment.frame_rate,
                channels=audio_segment.channels
            )
            
            # Convert to FLAC
            flac_data = self.convert_to_flac(audio_segment)
            
            # Extract metadata
            metadata = self.extract_metadata(audio_segment, detected_format, size)
            
            self._logger.info(
                "Audio processing complete",
                original_format=detected_format,
                duration_seconds=round(duration, 2),
                flac_size_bytes=len(flac_data)
            )
            
            return ProcessedAudio(
                flac_data=flac_data,
                metadata=metadata,
                original_format=detected_format
            )
    
    def process_audio_with_file(
        self,
        audio_data: str | bytes,
        expected_format: Optional[str] = None,
        is_base64: bool = True
    ) -> Tuple[ProcessedAudio, Path]:
        """
        Process audio and save to temporary file.
        
        Use this when you need a file path instead of bytes
        (e.g., for certain Google Cloud SDK methods).
        
        The temporary file is managed by the EphemeralFileManager
        and will be automatically cleaned up.
        
        Args:
            audio_data: Audio data (base64 string or raw bytes)
            expected_format: Optional expected format
            is_base64: Whether the input is base64 encoded
        
        Returns:
            Tuple of (ProcessedAudio, Path to temp FLAC file)
        """
        processed = self.process_audio(audio_data, expected_format, is_base64)
        
        # Use the context manager from file manager
        with self._file_manager.temp_file("flac", processed.flac_data) as temp_path:
            return processed, temp_path
    
    @contextmanager
    def ephemeral_audio(
        self,
        audio_data: str | bytes,
        expected_format: Optional[str] = None,
        is_base64: bool = True
    ) -> Generator[Tuple[ProcessedAudio, Path], None, None]:
        """
        Context manager for ephemeral audio processing.
        
        Processes audio and provides a temporary FLAC file that is
        automatically cleaned up when the context exits.
        
        Usage:
            with processor.ephemeral_audio(base64_data) as (processed, temp_path):
                # Use temp_path for STT
                transcription = stt_client.transcribe(temp_path)
            # File is automatically deleted here
        
        Args:
            audio_data: Audio data
            expected_format: Optional expected format
            is_base64: Whether input is base64 encoded
        
        Yields:
            Tuple of (ProcessedAudio, Path to temp file)
        """
        processed = self.process_audio(audio_data, expected_format, is_base64)
        
        with self._file_manager.temp_file("flac", processed.flac_data) as temp_path:
            yield processed, temp_path
    
    def cleanup(self) -> None:
        """Clean up all temporary files."""
        count = self._file_manager.cleanup_all()
        if count > 0:
            self._logger.info("Cleanup completed", files_removed=count)


# Module-level convenience functions

_processor: Optional[AudioProcessor] = None


def get_audio_processor() -> AudioProcessor:
    """Get the global AudioProcessor instance."""
    global _processor
    if _processor is None:
        _processor = AudioProcessor()
    return _processor


def process_audio(
    audio_data: str | bytes,
    expected_format: Optional[str] = None,
    is_base64: bool = True
) -> ProcessedAudio:
    """
    Process audio data for transcription.
    
    Convenience function that uses the global processor.
    
    Args:
        audio_data: Audio data (base64 string or raw bytes)
        expected_format: Optional expected format
        is_base64: Whether input is base64 encoded
    
    Returns:
        ProcessedAudio with FLAC data and metadata
    """
    return get_audio_processor().process_audio(audio_data, expected_format, is_base64)


def validate_audio(audio_bytes: bytes, expected_format: Optional[str] = None) -> Tuple[str, int]:
    """
    Validate audio bytes.
    
    Args:
        audio_bytes: Raw audio data
        expected_format: Optional expected format
    
    Returns:
        Tuple of (format, size_bytes)
    """
    return get_audio_processor().validate_audio(audio_bytes, expected_format)


def cleanup_temp_files() -> None:
    """Clean up all temporary audio files."""
    if _processor:
        _processor.cleanup()
