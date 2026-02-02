"""
Tests for the transcriber module.

Tests:
- Exception hierarchy
- Data classes (WordInfo, TranscriptionResult)
- Transcriber class with mocked Google Cloud client
- Retry logic
- Error handling
- Module-level convenience functions

Note: All tests mock the Google Cloud Speech client to avoid
actual API calls and costs.
"""

import time
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass

import pytest
from google.api_core import exceptions as google_exceptions

from src.transcriber import (
    Transcriber,
    TranscriptionResult,
    WordInfo,
    TranscriptionError,
    TranscriptionAPIError,
    TranscriptionTimeoutError,
    TranscriptionQuotaError,
    NoSpeechDetectedError,
    get_transcriber,
    transcribe,
    transcribe_with_retry,
)
from src.config import Config


class TestExceptionClasses:
    """Tests for custom exception classes."""
    
    def test_transcription_error_base(self):
        """Test base TranscriptionError."""
        error = TranscriptionError("Test error")
        assert str(error) == "Test error"
        assert isinstance(error, Exception)
    
    def test_transcription_api_error(self):
        """Test TranscriptionAPIError."""
        error = TranscriptionAPIError("API failed", error_code="INVALID_ARGUMENT")
        assert isinstance(error, TranscriptionError)
        assert error.error_code == "INVALID_ARGUMENT"
        assert "API failed" in str(error)
    
    def test_transcription_api_error_no_code(self):
        """Test TranscriptionAPIError without error code."""
        error = TranscriptionAPIError("API failed")
        assert error.error_code is None
    
    def test_transcription_timeout_error(self):
        """Test TranscriptionTimeoutError."""
        error = TranscriptionTimeoutError("Request timed out")
        assert isinstance(error, TranscriptionError)
    
    def test_transcription_quota_error(self):
        """Test TranscriptionQuotaError."""
        error = TranscriptionQuotaError("Quota exceeded")
        assert isinstance(error, TranscriptionError)
    
    def test_no_speech_detected_error(self):
        """Test NoSpeechDetectedError."""
        error = NoSpeechDetectedError("No speech found")
        assert isinstance(error, TranscriptionError)


class TestWordInfo:
    """Tests for WordInfo dataclass."""
    
    def test_word_info_creation(self):
        """Test creating WordInfo."""
        word = WordInfo(
            word="hello",
            start_time=0.5,
            end_time=1.0,
            confidence=0.95
        )
        
        assert word.word == "hello"
        assert word.start_time == 0.5
        assert word.end_time == 1.0
        assert word.confidence == 0.95
    
    def test_word_info_to_dict_redacts_word(self):
        """Test that to_dict redacts the actual word."""
        word = WordInfo(
            word="secret",
            start_time=0.123,
            end_time=0.456,
            confidence=0.987
        )
        
        result = word.to_dict()
        
        assert result["word"] == "<redacted>"
        assert result["start_time"] == 0.123
        assert result["end_time"] == 0.456
        assert result["confidence"] == 0.987


class TestTranscriptionResult:
    """Tests for TranscriptionResult dataclass."""
    
    def test_result_creation(self):
        """Test creating TranscriptionResult."""
        result = TranscriptionResult(
            text="Hello world",
            confidence=0.95,
            language_code="en-US",
            duration_seconds=2.5
        )
        
        assert result.text == "Hello world"
        assert result.confidence == 0.95
        assert result.language_code == "en-US"
        assert result.duration_seconds == 2.5
        assert result.word_info is None
        assert result.alternatives == []
    
    def test_result_with_word_info(self):
        """Test TranscriptionResult with word info."""
        words = [
            WordInfo(word="Hello", start_time=0.0, end_time=0.5, confidence=0.9),
            WordInfo(word="world", start_time=0.5, end_time=1.0, confidence=0.95),
        ]
        
        result = TranscriptionResult(
            text="Hello world",
            confidence=0.95,
            language_code="en-US",
            duration_seconds=1.0,
            word_info=words
        )
        
        assert len(result.word_info) == 2
    
    def test_result_to_dict_redacts_text(self):
        """Test that to_dict redacts transcription text."""
        result = TranscriptionResult(
            text="This is sensitive text",
            confidence=0.95,
            language_code="en-US",
            duration_seconds=2.5,
            alternatives=[{"confidence": 0.8}]
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["text"] == "<redacted>"
        assert result_dict["confidence"] == 0.95
        assert result_dict["language_code"] == "en-US"
        assert result_dict["duration_seconds"] == 2.5
        assert result_dict["word_count"] == 4
        assert result_dict["has_word_info"] is False
        assert result_dict["alternatives_count"] == 1
    
    def test_result_to_dict_empty_text(self):
        """Test to_dict with empty text."""
        result = TranscriptionResult(
            text="",
            confidence=0.0,
            language_code="en-US",
            duration_seconds=0.0
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["word_count"] == 0


class TestTranscriber:
    """Tests for Transcriber class."""
    
    @pytest.fixture
    def mock_speech_client(self):
        """Create a mock Google Cloud Speech client."""
        with patch('src.transcriber.speech.SpeechClient') as mock_class:
            mock_client = MagicMock()
            mock_class.return_value = mock_client
            yield mock_client
    
    @pytest.fixture
    def mock_config(self, tmp_path):
        """Create a test configuration."""
        config = Config()
        config.load(validate_credentials=False)
        config.audio.default_language = "en-US"
        config.performance.transcription_timeout = 30
        config.performance.max_retry_attempts = 3
        config.performance.retry_delay = 0.1  # Fast for testing
        return config
    
    @pytest.fixture
    def transcriber(self, mock_config, mock_speech_client):
        """Create a transcriber with mocked dependencies."""
        return Transcriber(config=mock_config)
    
    def _create_mock_response(self, transcript: str, confidence: float = 0.95):
        """Helper to create a mock recognition response."""
        mock_alternative = MagicMock()
        mock_alternative.transcript = transcript
        mock_alternative.confidence = confidence
        mock_alternative.words = []
        
        mock_result = MagicMock()
        mock_result.alternatives = [mock_alternative]
        
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        
        return mock_response
    
    def _create_mock_response_with_words(
        self, 
        transcript: str, 
        confidence: float = 0.95,
        words: list = None
    ):
        """Helper to create a mock response with word timing."""
        mock_alternative = MagicMock()
        mock_alternative.transcript = transcript
        mock_alternative.confidence = confidence
        
        if words:
            mock_words = []
            for w in words:
                mock_word = MagicMock()
                mock_word.word = w["word"]
                mock_word.start_time.total_seconds.return_value = w["start"]
                mock_word.end_time.total_seconds.return_value = w["end"]
                mock_word.confidence = w.get("confidence", 0.9)
                mock_words.append(mock_word)
            mock_alternative.words = mock_words
        else:
            mock_alternative.words = []
        
        mock_result = MagicMock()
        mock_result.alternatives = [mock_alternative]
        
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        
        return mock_response
    
    # Initialization Tests
    
    def test_transcriber_creation(self, mock_config):
        """Test creating a transcriber."""
        transcriber = Transcriber(config=mock_config)
        
        assert transcriber._config is mock_config
        assert transcriber._client is None  # Lazy initialization
    
    def test_client_lazy_initialization(self, transcriber, mock_speech_client):
        """Test that client is lazily initialized."""
        # Client should not be created yet
        assert transcriber._client is None
        
        # Access client property
        client = transcriber.client
        
        # Now it should be created
        assert client is not None
    
    # Transcription Tests
    
    def test_transcribe_success(self, transcriber, mock_speech_client):
        """Test successful transcription."""
        mock_response = self._create_mock_response("Hello world", 0.95)
        mock_speech_client.recognize.return_value = mock_response
        
        result = transcriber.transcribe(b"fake_flac_audio")
        
        assert result.text == "Hello world"
        assert result.confidence == 0.95
        assert result.language_code == "en-US"
        mock_speech_client.recognize.assert_called_once()
    
    def test_transcribe_with_language_code(self, transcriber, mock_speech_client):
        """Test transcription with custom language code."""
        mock_response = self._create_mock_response("Bonjour", 0.9)
        mock_speech_client.recognize.return_value = mock_response
        
        result = transcriber.transcribe(b"audio", language_code="fr-FR")
        
        assert result.language_code == "fr-FR"
    
    def test_transcribe_with_word_timing(self, transcriber, mock_speech_client):
        """Test transcription with word-level timing."""
        words = [
            {"word": "Hello", "start": 0.0, "end": 0.5, "confidence": 0.9},
            {"word": "world", "start": 0.5, "end": 1.0, "confidence": 0.95},
        ]
        mock_response = self._create_mock_response_with_words(
            "Hello world", 0.95, words
        )
        mock_speech_client.recognize.return_value = mock_response
        
        result = transcriber.transcribe(
            b"audio",
            enable_word_time_offsets=True
        )
        
        assert result.word_info is not None
        assert len(result.word_info) == 2
        assert result.word_info[0].word == "Hello"
        assert result.word_info[0].start_time == 0.0
    
    def test_transcribe_no_speech_empty_results(self, transcriber, mock_speech_client):
        """Test handling of empty results (no speech)."""
        mock_response = MagicMock()
        mock_response.results = []
        mock_speech_client.recognize.return_value = mock_response
        
        with pytest.raises(NoSpeechDetectedError, match="No speech detected"):
            transcriber.transcribe(b"silent_audio")
    
    def test_transcribe_no_alternatives(self, transcriber, mock_speech_client):
        """Test handling of result with no alternatives."""
        mock_result = MagicMock()
        mock_result.alternatives = []
        
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_speech_client.recognize.return_value = mock_response
        
        with pytest.raises(NoSpeechDetectedError, match="No transcription alternatives"):
            transcriber.transcribe(b"audio")
    
    # Error Handling Tests
    
    def test_transcribe_timeout_error(self, transcriber, mock_speech_client):
        """Test handling of timeout errors."""
        mock_speech_client.recognize.side_effect = google_exceptions.DeadlineExceeded(
            "Request timed out"
        )
        
        with pytest.raises(TranscriptionTimeoutError, match="timed out"):
            transcriber.transcribe(b"audio")
    
    def test_transcribe_quota_error(self, transcriber, mock_speech_client):
        """Test handling of quota errors."""
        mock_speech_client.recognize.side_effect = google_exceptions.ResourceExhausted(
            "Quota exceeded"
        )
        
        with pytest.raises(TranscriptionQuotaError, match="quota exceeded"):
            transcriber.transcribe(b"audio")
    
    def test_transcribe_api_error(self, transcriber, mock_speech_client):
        """Test handling of general API errors."""
        mock_speech_client.recognize.side_effect = google_exceptions.InvalidArgument(
            "Invalid audio format"
        )
        
        with pytest.raises(TranscriptionAPIError):
            transcriber.transcribe(b"audio")
    
    def test_transcribe_unexpected_error(self, transcriber, mock_speech_client):
        """Test handling of unexpected errors."""
        mock_speech_client.recognize.side_effect = RuntimeError("Something went wrong")
        
        with pytest.raises(TranscriptionAPIError, match="Unexpected error"):
            transcriber.transcribe(b"audio")
    
    # Retry Logic Tests
    
    def test_transcribe_with_retry_success_first_attempt(
        self, transcriber, mock_speech_client
    ):
        """Test retry wrapper with success on first attempt."""
        mock_response = self._create_mock_response("Hello", 0.95)
        mock_speech_client.recognize.return_value = mock_response
        
        result = transcriber.transcribe_with_retry(b"audio")
        
        assert result.text == "Hello"
        assert mock_speech_client.recognize.call_count == 1
    
    def test_transcribe_with_retry_success_after_retry(
        self, transcriber, mock_speech_client
    ):
        """Test retry wrapper with success after transient error."""
        mock_response = self._create_mock_response("Hello", 0.95)
        
        # First call fails, second succeeds
        mock_speech_client.recognize.side_effect = [
            google_exceptions.ServiceUnavailable("Temporarily unavailable"),
            mock_response
        ]
        
        result = transcriber.transcribe_with_retry(b"audio")
        
        assert result.text == "Hello"
        assert mock_speech_client.recognize.call_count == 2
    
    def test_transcribe_with_retry_max_attempts_exceeded(
        self, transcriber, mock_speech_client
    ):
        """Test retry wrapper when max attempts exceeded."""
        # All calls fail with retryable error
        mock_speech_client.recognize.side_effect = google_exceptions.ServiceUnavailable(
            "Temporarily unavailable"
        )
        
        with pytest.raises(TranscriptionAPIError):
            transcriber.transcribe_with_retry(b"audio", max_attempts=3)
        
        assert mock_speech_client.recognize.call_count == 3
    
    def test_transcribe_with_retry_non_retryable_error(
        self, transcriber, mock_speech_client
    ):
        """Test that non-retryable errors are not retried."""
        mock_speech_client.recognize.side_effect = google_exceptions.InvalidArgument(
            "Invalid request"
        )
        
        with pytest.raises(TranscriptionAPIError):
            transcriber.transcribe_with_retry(b"audio")
        
        # Should only try once for non-retryable errors
        assert mock_speech_client.recognize.call_count == 1
    
    def test_transcribe_with_retry_no_speech_not_retried(
        self, transcriber, mock_speech_client
    ):
        """Test that NoSpeechDetectedError is not retried."""
        mock_response = MagicMock()
        mock_response.results = []
        mock_speech_client.recognize.return_value = mock_response
        
        with pytest.raises(NoSpeechDetectedError):
            transcriber.transcribe_with_retry(b"audio")
        
        assert mock_speech_client.recognize.call_count == 1
    
    def test_transcribe_with_retry_exponential_backoff(
        self, transcriber, mock_speech_client
    ):
        """Test that retry uses exponential backoff."""
        mock_response = self._create_mock_response("Hello", 0.95)
        
        # Fail twice, then succeed
        mock_speech_client.recognize.side_effect = [
            google_exceptions.ServiceUnavailable("Unavailable"),
            google_exceptions.ServiceUnavailable("Unavailable"),
            mock_response
        ]
        
        start = time.time()
        result = transcriber.transcribe_with_retry(
            b"audio",
            max_attempts=3,
            retry_delay=0.1
        )
        elapsed = time.time() - start
        
        assert result.text == "Hello"
        # Should have waited: 0.1 (first retry) + 0.2 (second retry) = 0.3s minimum
        assert elapsed >= 0.25  # Allow some tolerance
    
    # Client Initialization Error Tests
    
    def test_client_initialization_error(self, mock_config):
        """Test handling of client initialization errors."""
        with patch('src.transcriber.speech.SpeechClient') as mock_class:
            mock_class.side_effect = google_exceptions.Unauthenticated(
                "Invalid credentials"
            )
            
            transcriber = Transcriber(config=mock_config)
            
            with pytest.raises(TranscriptionAPIError, match="Failed to initialize"):
                _ = transcriber.client
    
    # Retryable Error Detection Tests
    
    def test_is_retryable_service_unavailable(self, transcriber):
        """Test that ServiceUnavailable is retryable."""
        error = google_exceptions.ServiceUnavailable("Unavailable")
        assert transcriber._is_retryable_error(error) is True
    
    def test_is_retryable_deadline_exceeded(self, transcriber):
        """Test that DeadlineExceeded is retryable."""
        error = google_exceptions.DeadlineExceeded("Timeout")
        assert transcriber._is_retryable_error(error) is True
    
    def test_is_retryable_resource_exhausted(self, transcriber):
        """Test that ResourceExhausted is retryable."""
        error = google_exceptions.ResourceExhausted("Quota")
        assert transcriber._is_retryable_error(error) is True
    
    def test_is_not_retryable_invalid_argument(self, transcriber):
        """Test that InvalidArgument is not retryable."""
        error = google_exceptions.InvalidArgument("Invalid")
        assert transcriber._is_retryable_error(error) is False
    
    def test_is_not_retryable_permission_denied(self, transcriber):
        """Test that PermissionDenied is not retryable."""
        error = google_exceptions.PermissionDenied("Denied")
        assert transcriber._is_retryable_error(error) is False


class TestTranscriberMultipleAlternatives:
    """Tests for handling multiple transcription alternatives."""
    
    @pytest.fixture
    def mock_speech_client(self):
        """Create a mock Google Cloud Speech client."""
        with patch('src.transcriber.speech.SpeechClient') as mock_class:
            mock_client = MagicMock()
            mock_class.return_value = mock_client
            yield mock_client
    
    @pytest.fixture
    def mock_config(self):
        """Create a test configuration."""
        config = Config()
        config.load(validate_credentials=False)
        return config
    
    @pytest.fixture
    def transcriber(self, mock_config, mock_speech_client):
        """Create a transcriber."""
        return Transcriber(config=mock_config)
    
    def test_multiple_alternatives(self, transcriber, mock_speech_client):
        """Test parsing response with multiple alternatives."""
        # Create primary alternative
        alt1 = MagicMock()
        alt1.transcript = "Hello world"
        alt1.confidence = 0.95
        alt1.words = []
        
        # Create secondary alternatives
        alt2 = MagicMock()
        alt2.transcript = "Hello word"
        alt2.confidence = 0.8
        alt2.words = []
        
        alt3 = MagicMock()
        alt3.transcript = "Hello world!"
        alt3.confidence = 0.7
        alt3.words = []
        
        mock_result = MagicMock()
        mock_result.alternatives = [alt1, alt2, alt3]
        
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        
        mock_speech_client.recognize.return_value = mock_response
        
        result = transcriber.transcribe(b"audio")
        
        assert result.text == "Hello world"
        assert result.confidence == 0.95
        assert len(result.alternatives) == 2  # Excludes first


class TestModuleFunctions:
    """Tests for module-level convenience functions."""
    
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset the module singleton before each test."""
        import src.transcriber as module
        module._transcriber = None
        yield
        module._transcriber = None
    
    def test_get_transcriber_singleton(self):
        """Test that get_transcriber returns same instance."""
        with patch('src.transcriber.speech.SpeechClient'):
            t1 = get_transcriber()
            t2 = get_transcriber()
            
            assert t1 is t2
    
    def test_transcribe_convenience_function(self):
        """Test module-level transcribe function."""
        with patch('src.transcriber.speech.SpeechClient') as mock_class:
            mock_client = MagicMock()
            mock_class.return_value = mock_client
            
            # Create mock response
            mock_alt = MagicMock()
            mock_alt.transcript = "Hello"
            mock_alt.confidence = 0.95
            mock_alt.words = []
            
            mock_result = MagicMock()
            mock_result.alternatives = [mock_alt]
            
            mock_response = MagicMock()
            mock_response.results = [mock_result]
            
            mock_client.recognize.return_value = mock_response
            
            result = transcribe(b"audio")
            
            assert result.text == "Hello"
    
    def test_transcribe_with_retry_convenience_function(self):
        """Test module-level transcribe_with_retry function."""
        with patch('src.transcriber.speech.SpeechClient') as mock_class:
            mock_client = MagicMock()
            mock_class.return_value = mock_client
            
            # Create mock response
            mock_alt = MagicMock()
            mock_alt.transcript = "Hello"
            mock_alt.confidence = 0.95
            mock_alt.words = []
            
            mock_result = MagicMock()
            mock_result.alternatives = [mock_alt]
            
            mock_response = MagicMock()
            mock_response.results = [mock_result]
            
            mock_client.recognize.return_value = mock_response
            
            result = transcribe_with_retry(b"audio")
            
            assert result.text == "Hello"


class TestRecognitionConfig:
    """Tests for recognition configuration building."""
    
    @pytest.fixture
    def mock_config(self):
        """Create a test configuration."""
        config = Config()
        config.load(validate_credentials=False)
        return config
    
    @pytest.fixture
    def transcriber(self, mock_config):
        """Create a transcriber."""
        with patch('src.transcriber.speech.SpeechClient'):
            return Transcriber(config=mock_config)
    
    def test_build_recognition_config_defaults(self, transcriber):
        """Test building recognition config with defaults."""
        with patch('src.transcriber.speech.RecognitionConfig') as mock_config_class:
            transcriber._build_recognition_config("en-US")
            
            mock_config_class.assert_called_once()
            call_kwargs = mock_config_class.call_args.kwargs
            
            assert call_kwargs["language_code"] == "en-US"
            assert call_kwargs["enable_automatic_punctuation"] is True
            assert call_kwargs["enable_word_time_offsets"] is False
    
    def test_build_recognition_config_with_word_offsets(self, transcriber):
        """Test building config with word time offsets enabled."""
        with patch('src.transcriber.speech.RecognitionConfig') as mock_config_class:
            transcriber._build_recognition_config(
                "en-US",
                enable_word_time_offsets=True
            )
            
            call_kwargs = mock_config_class.call_args.kwargs
            assert call_kwargs["enable_word_time_offsets"] is True
    
    def test_build_recognition_audio(self, transcriber):
        """Test building recognition audio object."""
        with patch('src.transcriber.speech.RecognitionAudio') as mock_audio_class:
            audio_data = b"fake_audio_bytes"
            transcriber._build_recognition_audio(audio_data)
            
            mock_audio_class.assert_called_once_with(content=audio_data)


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""
    
    @pytest.fixture
    def mock_speech_client(self):
        """Create a mock Google Cloud Speech client."""
        with patch('src.transcriber.speech.SpeechClient') as mock_class:
            mock_client = MagicMock()
            mock_class.return_value = mock_client
            yield mock_client
    
    @pytest.fixture
    def mock_config(self):
        """Create a test configuration."""
        config = Config()
        config.load(validate_credentials=False)
        config.performance.retry_delay = 0.01  # Very short for testing
        return config
    
    @pytest.fixture
    def transcriber(self, mock_config, mock_speech_client):
        """Create a transcriber."""
        return Transcriber(config=mock_config)
    
    def test_zero_confidence(self, transcriber, mock_speech_client):
        """Test handling of zero confidence result."""
        mock_alt = MagicMock()
        mock_alt.transcript = "Uncertain text"
        mock_alt.confidence = 0.0
        mock_alt.words = []
        
        mock_result = MagicMock()
        mock_result.alternatives = [mock_alt]
        
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        
        mock_speech_client.recognize.return_value = mock_response
        
        result = transcriber.transcribe(b"audio")
        
        assert result.confidence == 0.0
        assert result.text == "Uncertain text"
    
    def test_empty_transcript(self, transcriber, mock_speech_client):
        """Test handling of empty transcript string."""
        mock_alt = MagicMock()
        mock_alt.transcript = ""
        mock_alt.confidence = 0.5
        mock_alt.words = []
        
        mock_result = MagicMock()
        mock_result.alternatives = [mock_alt]
        
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        
        mock_speech_client.recognize.return_value = mock_response
        
        result = transcriber.transcribe(b"audio")
        
        assert result.text == ""
    
    def test_missing_confidence_attribute(self, transcriber, mock_speech_client):
        """Test handling when confidence attribute is missing."""
        mock_alt = MagicMock(spec=['transcript', 'words'])
        mock_alt.transcript = "Hello"
        mock_alt.words = []
        # No confidence attribute
        
        mock_result = MagicMock()
        mock_result.alternatives = [mock_alt]
        
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        
        mock_speech_client.recognize.return_value = mock_response
        
        result = transcriber.transcribe(b"audio")
        
        # Should default to 0.0
        assert result.confidence == 0.0
    
    def test_very_long_audio_duration_estimate(self, transcriber, mock_speech_client):
        """Test duration estimation with large audio data."""
        mock_alt = MagicMock()
        mock_alt.transcript = "Long audio"
        mock_alt.confidence = 0.95
        mock_alt.words = []
        
        mock_result = MagicMock()
        mock_result.alternatives = [mock_alt]
        
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        
        mock_speech_client.recognize.return_value = mock_response
        
        # 1MB of audio at 16kHz mono ~ 32 seconds
        large_audio = b"x" * (1024 * 1024)
        result = transcriber.transcribe(large_audio)
        
        # Duration should be reasonably estimated
        assert result.duration_seconds > 0
