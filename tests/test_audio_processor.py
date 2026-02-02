"""
Tests for the audio processor module.

Tests:
- Audio format detection
- Format validation
- Size validation
- Duration validation
- FLAC conversion
- Ephemeral file handling
- Cleanup mechanisms

Note: These tests use synthetic audio data and mocks to avoid
requiring actual audio files.
"""

import base64
import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

from src.audio_processor import (
    AudioProcessor,
    AudioMetadata,
    ProcessedAudio,
    EphemeralFileManager,
    AudioProcessingError,
    AudioValidationError,
    AudioConversionError,
    AudioDurationError,
    AudioSizeError,
    AudioFormatError,
    AUDIO_SIGNATURES,
    MIME_TO_FORMAT,
    get_audio_processor,
    process_audio,
    validate_audio,
    cleanup_temp_files,
)
from src.config import Config


class TestAudioSignatures:
    """Tests for audio format signatures."""
    
    def test_ogg_signature(self):
        """Test OGG magic bytes."""
        assert b"OggS" in AUDIO_SIGNATURES["ogg"]
    
    def test_mp3_signatures(self):
        """Test MP3 magic bytes."""
        sigs = AUDIO_SIGNATURES["mp3"]
        assert b"\xff\xfb" in sigs or b"ID3" in sigs
    
    def test_wav_signature(self):
        """Test WAV magic bytes."""
        assert b"RIFF" in AUDIO_SIGNATURES["wav"]
    
    def test_flac_signature(self):
        """Test FLAC magic bytes."""
        assert b"fLaC" in AUDIO_SIGNATURES["flac"]


class TestMimeToFormat:
    """Tests for MIME type mappings."""
    
    def test_ogg_mime(self):
        """Test OGG MIME type."""
        assert MIME_TO_FORMAT["audio/ogg"] == "ogg"
    
    def test_mp3_mimes(self):
        """Test MP3 MIME types."""
        assert MIME_TO_FORMAT["audio/mpeg"] == "mp3"
        assert MIME_TO_FORMAT["audio/mp3"] == "mp3"
    
    def test_wav_mimes(self):
        """Test WAV MIME types."""
        assert MIME_TO_FORMAT["audio/wav"] == "wav"
        assert MIME_TO_FORMAT["audio/x-wav"] == "wav"
    
    def test_flac_mimes(self):
        """Test FLAC MIME types."""
        assert MIME_TO_FORMAT["audio/flac"] == "flac"


class TestAudioMetadata:
    """Tests for AudioMetadata dataclass."""
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        metadata = AudioMetadata(
            format="ogg",
            duration_seconds=3.456,
            sample_rate=48000,
            channels=1,
            size_bytes=45000
        )
        
        result = metadata.to_dict()
        
        assert result["format"] == "ogg"
        assert result["duration_seconds"] == 3.46  # Rounded
        assert result["sample_rate"] == 48000
        assert result["channels"] == 1
        assert result["size_bytes"] == 45000


class TestProcessedAudio:
    """Tests for ProcessedAudio dataclass."""
    
    def test_creation(self):
        """Test creating ProcessedAudio."""
        metadata = AudioMetadata(
            format="ogg",
            duration_seconds=2.0,
            sample_rate=16000,
            channels=1,
            size_bytes=1000
        )
        
        processed = ProcessedAudio(
            flac_data=b"fake_flac_data",
            metadata=metadata,
            original_format="ogg"
        )
        
        assert processed.flac_data == b"fake_flac_data"
        assert processed.original_format == "ogg"


class TestEphemeralFileManager:
    """Tests for EphemeralFileManager."""
    
    def test_temp_dir_creation(self, tmp_path):
        """Test temporary directory creation."""
        manager = EphemeralFileManager(temp_dir=tmp_path / "audio_temp")
        
        result = manager.temp_dir
        
        assert result.exists()
        assert result.is_dir()
    
    def test_temp_file_creation_and_cleanup(self, tmp_path):
        """Test temporary file is created and cleaned up."""
        manager = EphemeralFileManager(temp_dir=tmp_path)
        
        with manager.temp_file("flac", b"test data") as file_path:
            assert file_path.exists()
            assert file_path.read_bytes() == b"test data"
            stored_path = file_path
        
        # File should be deleted after context exits
        assert not stored_path.exists()
    
    def test_temp_file_cleanup_on_exception(self, tmp_path):
        """Test cleanup happens even on exception."""
        manager = EphemeralFileManager(temp_dir=tmp_path)
        
        with pytest.raises(ValueError):
            with manager.temp_file("flac", b"test data") as file_path:
                stored_path = file_path
                raise ValueError("Test error")
        
        # File should still be deleted
        assert not stored_path.exists()
    
    def test_cleanup_all(self, tmp_path):
        """Test cleaning up all active files."""
        manager = EphemeralFileManager(temp_dir=tmp_path)
        
        # Create some files directly (simulating incomplete cleanup)
        file1 = tmp_path / "test1.flac"
        file2 = tmp_path / "test2.flac"
        file1.write_bytes(b"data1")
        file2.write_bytes(b"data2")
        manager._active_files.add(file1)
        manager._active_files.add(file2)
        
        count = manager.cleanup_all()
        
        assert count == 2
        assert not file1.exists()
        assert not file2.exists()


class TestAudioProcessor:
    """Tests for AudioProcessor."""
    
    @pytest.fixture
    def processor(self, tmp_path):
        """Create a processor with test config."""
        config = Config()
        config.load(validate_credentials=False)
        config.audio.temp_dir = tmp_path / "audio_temp"
        config.audio.max_duration = 60
        config.audio.max_size = 10 * 1024 * 1024
        return AudioProcessor(config=config)
    
    def test_detect_format_ogg(self, processor):
        """Test OGG format detection."""
        ogg_header = b"OggS" + b"\x00" * 100
        
        result = processor.detect_format(ogg_header)
        
        assert result == "ogg"
    
    def test_detect_format_mp3_id3(self, processor):
        """Test MP3 format detection with ID3 header."""
        mp3_header = b"ID3" + b"\x00" * 100
        
        result = processor.detect_format(mp3_header)
        
        assert result == "mp3"
    
    def test_detect_format_wav(self, processor):
        """Test WAV format detection."""
        wav_header = b"RIFF" + b"\x00" * 100
        
        result = processor.detect_format(wav_header)
        
        assert result == "wav"
    
    def test_detect_format_flac(self, processor):
        """Test FLAC format detection."""
        flac_header = b"fLaC" + b"\x00" * 100
        
        result = processor.detect_format(flac_header)
        
        assert result == "flac"
    
    def test_detect_format_unknown(self, processor):
        """Test unknown format detection."""
        unknown_data = b"\x00\x01\x02\x03" * 100
        
        result = processor.detect_format(unknown_data)
        
        assert result is None
    
    def test_detect_format_too_short(self, processor):
        """Test format detection with too little data."""
        short_data = b"ab"
        
        result = processor.detect_format(short_data)
        
        assert result is None
    
    def test_validate_format_supported(self, processor):
        """Test validation of supported format."""
        ogg_data = b"OggS" + b"\x00" * 100
        
        result = processor.validate_format(ogg_data)
        
        assert result == "ogg"
    
    def test_validate_format_unsupported(self, processor):
        """Test validation of unsupported format."""
        # Create data with unknown header
        unknown_data = b"UNKN" + b"\x00" * 100
        
        with pytest.raises(AudioFormatError, match="Unable to detect"):
            processor.validate_format(unknown_data)
    
    def test_validate_size_valid(self, processor):
        """Test size validation with valid size."""
        data = b"x" * 1000
        
        result = processor.validate_size(data)
        
        assert result == 1000
    
    def test_validate_size_empty(self, processor):
        """Test size validation with empty data."""
        with pytest.raises(AudioValidationError, match="empty"):
            processor.validate_size(b"")
    
    def test_validate_size_too_large(self, processor):
        """Test size validation with oversized data."""
        # Create data larger than max_size
        large_data = b"x" * (processor.config.audio.max_size + 1)
        
        with pytest.raises(AudioSizeError, match="exceeds maximum"):
            processor.validate_size(large_data)
    
    def test_get_duration_valid(self, processor):
        """Test duration extraction with valid audio."""
        # Create a mock AudioSegment
        mock_segment = MagicMock()
        mock_segment.__len__ = MagicMock(return_value=5000)  # 5 seconds in ms
        
        result = processor.get_duration(mock_segment)
        
        assert result == 5.0
    
    def test_get_duration_exceeds_max(self, processor):
        """Test duration validation with too long audio."""
        mock_segment = MagicMock()
        mock_segment.__len__ = MagicMock(return_value=120000)  # 120 seconds
        
        with pytest.raises(AudioDurationError, match="exceeds maximum"):
            processor.get_duration(mock_segment)
    
    def test_validate_audio_combined(self, processor):
        """Test combined validation of format and size."""
        ogg_data = b"OggS" + b"\x00" * 500
        
        format_result, size_result = processor.validate_audio(ogg_data)
        
        assert format_result == "ogg"
        assert size_result == 504
    
    def test_extract_metadata(self, processor):
        """Test metadata extraction from AudioSegment."""
        mock_segment = MagicMock()
        mock_segment.__len__ = MagicMock(return_value=3500)  # 3.5 seconds
        mock_segment.frame_rate = 48000
        mock_segment.channels = 2
        
        result = processor.extract_metadata(mock_segment, "ogg", 45000)
        
        assert result.format == "ogg"
        assert result.duration_seconds == 3.5
        assert result.sample_rate == 48000
        assert result.channels == 2
        assert result.size_bytes == 45000
    
    @patch('src.audio_processor.AudioSegment')
    def test_process_audio_invalid_base64(self, mock_audio_segment, processor):
        """Test processing with invalid base64."""
        with pytest.raises(AudioValidationError, match="Invalid base64"):
            processor.process_audio("not_valid_base64!!!", is_base64=True)
    
    @patch('src.audio_processor.AudioSegment')
    def test_process_audio_base64_bytes_error(self, mock_audio_segment, processor):
        """Test that passing bytes when base64 expected raises error."""
        with pytest.raises(AudioValidationError, match="Expected base64 string"):
            processor.process_audio(b"some bytes", is_base64=True)
    
    def test_cleanup(self, processor, tmp_path):
        """Test cleanup method."""
        # Create a temp file
        temp_file = tmp_path / "audio_temp" / "test.flac"
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_bytes(b"test")
        processor._file_manager._active_files.add(temp_file)
        
        processor.cleanup()
        
        assert not temp_file.exists()


class TestAudioProcessorIntegration:
    """Integration tests for AudioProcessor with mocked pydub."""
    
    @pytest.fixture
    def mock_audio_segment(self):
        """Create a mock AudioSegment class."""
        with patch('src.audio_processor.AudioSegment') as mock_class:
            mock_segment = MagicMock()
            mock_segment.__len__ = MagicMock(return_value=2000)  # 2 seconds
            mock_segment.frame_rate = 48000
            mock_segment.channels = 1
            mock_segment.set_channels.return_value = mock_segment
            mock_segment.set_frame_rate.return_value = mock_segment
            
            # Mock export to return FLAC bytes
            def mock_export(output, format):
                output.write(b"fLaC_mock_data")
            mock_segment.export.side_effect = mock_export
            
            mock_class.from_file.return_value = mock_segment
            yield mock_class
    
    def test_full_processing_flow(self, mock_audio_segment, tmp_path):
        """Test full audio processing flow."""
        config = Config()
        config.load(validate_credentials=False)
        config.audio.temp_dir = tmp_path
        processor = AudioProcessor(config=config)
        
        # Create valid OGG-like base64 data
        ogg_data = b"OggS" + b"\x00" * 1000
        base64_audio = base64.b64encode(ogg_data).decode('utf-8')
        
        result = processor.process_audio(base64_audio, expected_format="ogg")
        
        assert result.flac_data == b"fLaC_mock_data"
        assert result.original_format == "ogg"
        assert result.metadata.duration_seconds == 2.0


class TestModuleFunctions:
    """Tests for module-level convenience functions."""
    
    def test_get_audio_processor_singleton(self):
        """Test that get_audio_processor returns same instance."""
        import src.audio_processor as module
        module._processor = None  # Reset
        
        p1 = get_audio_processor()
        p2 = get_audio_processor()
        
        assert p1 is p2
    
    def test_validate_audio_function(self, tmp_path):
        """Test module-level validate_audio function."""
        import src.audio_processor as module
        
        config = Config()
        config.load(validate_credentials=False)
        config.audio.temp_dir = tmp_path
        module._processor = AudioProcessor(config=config)
        
        ogg_data = b"OggS" + b"\x00" * 500
        
        format_result, size_result = validate_audio(ogg_data)
        
        assert format_result == "ogg"
    
    def test_cleanup_temp_files_function(self):
        """Test module-level cleanup function."""
        import src.audio_processor as module
        
        mock_processor = MagicMock()
        module._processor = mock_processor
        
        cleanup_temp_files()
        
        mock_processor.cleanup.assert_called_once()
    
    def test_cleanup_temp_files_no_processor(self):
        """Test cleanup when no processor exists."""
        import src.audio_processor as module
        module._processor = None
        
        # Should not raise
        cleanup_temp_files()


class TestErrorClasses:
    """Tests for custom exception classes."""
    
    def test_audio_processing_error_base(self):
        """Test base AudioProcessingError."""
        error = AudioProcessingError("Test error")
        assert str(error) == "Test error"
        assert isinstance(error, Exception)
    
    def test_audio_validation_error(self):
        """Test AudioValidationError."""
        error = AudioValidationError("Invalid audio")
        assert isinstance(error, AudioProcessingError)
    
    def test_audio_conversion_error(self):
        """Test AudioConversionError."""
        error = AudioConversionError("Conversion failed")
        assert isinstance(error, AudioProcessingError)
    
    def test_audio_duration_error(self):
        """Test AudioDurationError."""
        error = AudioDurationError("Too long")
        assert isinstance(error, AudioProcessingError)
    
    def test_audio_size_error(self):
        """Test AudioSizeError."""
        error = AudioSizeError("Too large")
        assert isinstance(error, AudioProcessingError)
    
    def test_audio_format_error(self):
        """Test AudioFormatError."""
        error = AudioFormatError("Unsupported")
        assert isinstance(error, AudioProcessingError)
