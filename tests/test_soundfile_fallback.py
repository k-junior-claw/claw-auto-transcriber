"""
Test soundfile fallback for audio processing without ffmpeg.
"""
import pytest
import io
from unittest.mock import patch, MagicMock

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

from src.audio_processor import (
    AudioProcessor,
    AudioConversionError,
    SOUNDFILE_AVAILABLE
)


class TestSoundfileFallback:
    """Test soundfile fallback functionality."""
    
    @pytest.fixture
    def processor(self):
        """Create an AudioProcessor instance."""
        return AudioProcessor()
    
    @pytest.mark.skipif(not SOUNDFILE_AVAILABLE, reason="soundfile not installed")
    def test_soundfile_fallback_available(self):
        """Test that soundfile fallback is available."""
        assert SOUNDFILE_AVAILABLE is True
    
    @pytest.mark.skipif(SOUNDFILE_AVAILABLE, reason="soundfile is installed")
    def test_soundfile_fallback_not_available(self):
        """Test behavior when soundfile is not available."""
        assert SOUNDFILE_AVAILABLE is False
    
    @pytest.mark.skipif(not SOUNDFILE_AVAILABLE, reason="soundfile not installed")
    @pytest.mark.skipif(not NUMPY_AVAILABLE, reason="numpy not installed")
    def test_load_audio_segment_with_soundfile_success(self, processor, mocker):
        """Test successful audio loading with soundfile."""
        # Mock soundfile.read to return test data
        import numpy as np
        mock_data = np.array([0.1, -0.1, 0.2, -0.2], dtype=np.float32)
        mock_samplerate = 48000
        
        with patch('src.audio_processor.sf.read') as mock_read:
            mock_read.return_value = (mock_data, mock_samplerate)
            
            # Create dummy audio bytes
            audio_bytes = b'dummy_ogg_data'
            
            # Call the fallback method
            segment = processor._load_audio_segment_with_soundfile(audio_bytes, 'ogg')
            
            # Verify the result is an AudioSegment
            assert segment is not None
            assert hasattr(segment, 'frame_rate')
            assert segment.frame_rate == 16000  # Should be resampled
            assert segment.channels == 1  # Should be mono
    
    @pytest.mark.skipif(not SOUNDFILE_AVAILABLE, reason="soundfile not installed")
    def test_load_audio_segment_with_soundfile_failure(self, processor, mocker):
        """Test soundfile fallback failure handling."""
        with patch('src.audio_processor.sf.read') as mock_read:
            mock_read.side_effect = Exception("Read error")
            
            audio_bytes = b'dummy_ogg_data'
            
            with pytest.raises(AudioConversionError) as exc_info:
                processor._load_audio_segment_with_soundfile(audio_bytes, 'ogg')
            
            assert "soundfile fallback failed" in str(exc_info.value)
        AudioConversionError


class TestFallbackIntegration:
    """Integration tests for fallback behavior."""
    
    @pytest.fixture
    def processor(self):
        """Create an AudioProcessor instance."""
        return AudioProcessor()
    
    @pytest.mark.skipif(not SOUNDFILE_AVAILABLE, reason="soundfile not installed")
    def test_pydub_failure_triggers_fallback(self, processor, mocker):
        """Test that pydub failure triggers soundfile fallback for OGG."""
        # Mock pydub to fail
        with patch('src.audio_processor.AudioSegment.from_file') as mock_from_file:
            mock_from_file.side_effect = Exception("ffmpeg not found")
            
            # Mock soundfile fallback
            mock_segment = MagicMock()
            mock_segment.frame_rate = 16000
            with patch.object(processor, '_load_audio_segment_with_soundfile') as mock_fallback:
                mock_fallback.return_value = mock_segment
                
                # Create dummy OGG bytes (with OggS header)
                audio_bytes = b'OggS' + b'\x00' * 100
                
                # Call load method
                segment = processor._load_audio_segment(audio_bytes, 'ogg')
                
                # Verify fallback was called
                mock_fallback.assert_called_once()
    
    def test_pydub_failure_without_fallback_raises_error(self, processor):
        """Test that pydub failure without soundfile raises error."""
        # Temporarily disable soundfile
        with patch('src.audio_processor.SOUNDFILE_AVAILABLE', False):
            with patch('src.audio_processor.AudioSegment.from_file') as mock_from_file:
                mock_from_file.side_effect = Exception("ffmpeg not found")
                
                audio_bytes = b'OggS' + b'\x00' * 100
                
                with pytest.raises(AudioConversionError):
                    processor._load_audio_segment(audio_bytes, 'ogg')
