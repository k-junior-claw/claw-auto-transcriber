"""
Transcriber Module for Claw Auto-Transcriber MCP Server.

Handles:
- Google Cloud Speech-to-Text API integration
- Transcription of audio data to text
- Response parsing with confidence scores
- Error handling with retry logic for transient failures
- Privacy-preserving logging (NO transcription content logged)

CRITICAL SECURITY NOTES:
1. Transcription text is NEVER logged
2. Audio content is NEVER logged
3. Only metadata (duration, confidence, language) is logged
"""

import time
from dataclasses import dataclass, field
from typing import Optional, List, Any
from enum import Enum

from google.cloud import speech
from google.api_core import exceptions as google_exceptions

from src.config import Config, get_config
from src.logger import MCPLogger, get_logger


class TranscriptionError(Exception):
    """Base exception for transcription errors."""
    pass


class TranscriptionAPIError(TranscriptionError):
    """Raised when Google Cloud Speech API returns an error."""
    
    def __init__(self, message: str, error_code: Optional[str] = None):
        """
        Initialize API error.
        
        Args:
            message: Error message
            error_code: Optional Google Cloud error code
        """
        super().__init__(message)
        self.error_code = error_code


class TranscriptionTimeoutError(TranscriptionError):
    """Raised when transcription request times out."""
    pass


class TranscriptionQuotaError(TranscriptionError):
    """Raised when API quota is exceeded."""
    pass


class NoSpeechDetectedError(TranscriptionError):
    """Raised when no speech is detected in audio."""
    pass


@dataclass
class WordInfo:
    """Word-level information from transcription."""
    word: str
    start_time: float  # seconds
    end_time: float    # seconds
    confidence: float  # 0.0 to 1.0
    
    def to_dict(self) -> dict:
        """Convert to dictionary (safe for logging - redacts word)."""
        return {
            "word": "<redacted>",  # Never log actual words
            "start_time": round(self.start_time, 3),
            "end_time": round(self.end_time, 3),
            "confidence": round(self.confidence, 3),
        }


@dataclass
class TranscriptionResult:
    """Result of a transcription operation."""
    text: str
    confidence: float
    language_code: str
    duration_seconds: float
    word_info: Optional[List[WordInfo]] = None
    alternatives: List[dict] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary (safe for logging - redacts text)."""
        return {
            "text": "<redacted>",  # Never log transcription text
            "confidence": round(self.confidence, 3),
            "language_code": self.language_code,
            "duration_seconds": round(self.duration_seconds, 2),
            "word_count": len(self.text.split()) if self.text else 0,
            "has_word_info": self.word_info is not None,
            "alternatives_count": len(self.alternatives),
        }


class Transcriber:
    """
    Google Cloud Speech-to-Text client wrapper.
    
    Handles transcription of audio data using Google Cloud Speech-to-Text API
    with proper error handling, retry logic, and privacy-preserving logging.
    
    Usage:
        transcriber = Transcriber()
        
        # Transcribe FLAC audio data
        result = transcriber.transcribe(flac_audio_bytes)
        print(f"Transcription confidence: {result.confidence}")
        
        # With retry logic
        result = transcriber.transcribe_with_retry(flac_audio_bytes)
    """
    
    def __init__(
        self,
        config: Optional[Config] = None,
        logger: Optional[MCPLogger] = None
    ):
        """
        Initialize the transcriber.
        
        Args:
            config: Optional configuration instance
            logger: Optional logger instance
        """
        self._config = config
        self._logger = logger or get_logger("transcriber")
        self._client: Optional[speech.SpeechClient] = None
    
    @property
    def config(self) -> Config:
        """Get configuration (lazy loading)."""
        if self._config is None:
            self._config = get_config()
        return self._config
    
    @property
    def client(self) -> speech.SpeechClient:
        """Get Google Cloud Speech client (lazy initialization)."""
        if self._client is None:
            self._client = self._initialize_client()
        return self._client
    
    def _initialize_client(self) -> speech.SpeechClient:
        """
        Initialize the Google Cloud Speech client.
        
        Returns:
            Configured SpeechClient instance
        
        Raises:
            TranscriptionAPIError: If client initialization fails
        """
        try:
            self._logger.debug("Initializing Google Cloud Speech client")
            
            # Client will use GOOGLE_APPLICATION_CREDENTIALS from environment
            # or the credentials_path from config
            client = speech.SpeechClient()
            
            self._logger.info("Google Cloud Speech client initialized")
            return client
            
        except google_exceptions.GoogleAPIError as e:
            self._logger.error(
                "Failed to initialize Speech client",
                error_type=type(e).__name__
            )
            raise TranscriptionAPIError(
                "Failed to initialize Google Cloud Speech client",
                error_code=getattr(e, 'code', None)
            ) from e
        except Exception as e:
            self._logger.error(
                "Unexpected error initializing Speech client",
                error_type=type(e).__name__
            )
            raise TranscriptionAPIError(
                f"Failed to initialize client: {type(e).__name__}"
            ) from e
    
    def _build_recognition_config(
        self,
        language_code: str,
        enable_word_time_offsets: bool = False
    ) -> speech.RecognitionConfig:
        """
        Build recognition configuration for API request.
        
        Args:
            language_code: Language code (e.g., "en-US")
            enable_word_time_offsets: Whether to include word timing
        
        Returns:
            RecognitionConfig for the API request
        """
        return speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.FLAC,
            sample_rate_hertz=16000,
            language_code=language_code,
            enable_automatic_punctuation=True,
            enable_word_time_offsets=enable_word_time_offsets,
            model="default",
        )
    
    def _build_recognition_audio(self, audio_data: bytes) -> speech.RecognitionAudio:
        """
        Build recognition audio object.
        
        Args:
            audio_data: FLAC audio bytes
        
        Returns:
            RecognitionAudio for the API request
        """
        return speech.RecognitionAudio(content=audio_data)
    
    def _parse_response(
        self,
        response: speech.RecognizeResponse,
        language_code: str,
        duration_seconds: float
    ) -> TranscriptionResult:
        """
        Parse the API response into a TranscriptionResult.
        
        Args:
            response: Google Cloud Speech API response
            language_code: Language code used for transcription
            duration_seconds: Estimated audio duration
        
        Returns:
            TranscriptionResult with parsed data
        
        Raises:
            NoSpeechDetectedError: If no speech was detected
        """
        if not response.results:
            raise NoSpeechDetectedError("No speech detected in audio")
        
        # Get the first (best) result
        result = response.results[0]
        
        if not result.alternatives:
            raise NoSpeechDetectedError("No transcription alternatives found")
        
        best_alternative = result.alternatives[0]
        
        # Extract word info if available
        word_info = None
        if best_alternative.words:
            word_info = [
                WordInfo(
                    word=word.word,
                    start_time=word.start_time.total_seconds(),
                    end_time=word.end_time.total_seconds(),
                    confidence=getattr(word, 'confidence', 0.0),
                )
                for word in best_alternative.words
            ]
        
        # Collect alternatives (without transcript text for privacy)
        alternatives = []
        for alt in result.alternatives[1:]:  # Skip first (already used)
            alternatives.append({
                "confidence": getattr(alt, 'confidence', 0.0),
            })
        
        return TranscriptionResult(
            text=best_alternative.transcript,
            confidence=getattr(best_alternative, 'confidence', 0.0),
            language_code=language_code,
            duration_seconds=duration_seconds,
            word_info=word_info,
            alternatives=alternatives,
        )
    
    def _is_retryable_error(self, error: Exception) -> bool:
        """
        Check if an error is retryable.
        
        Args:
            error: Exception to check
        
        Returns:
            True if the error is retryable
        """
        retryable_types = (
            google_exceptions.ServiceUnavailable,
            google_exceptions.DeadlineExceeded,
            google_exceptions.ResourceExhausted,
            google_exceptions.Aborted,
            google_exceptions.InternalServerError,
        )
        return isinstance(error, retryable_types)
    
    def _handle_api_error(self, error: Exception) -> None:
        """
        Handle and re-raise API errors as custom exceptions.
        
        Args:
            error: Original exception
        
        Raises:
            TranscriptionTimeoutError: For timeout errors
            TranscriptionQuotaError: For quota errors
            TranscriptionAPIError: For other API errors
        """
        if isinstance(error, google_exceptions.DeadlineExceeded):
            raise TranscriptionTimeoutError(
                "Transcription request timed out"
            ) from error
        
        if isinstance(error, google_exceptions.ResourceExhausted):
            raise TranscriptionQuotaError(
                "Google Cloud Speech API quota exceeded"
            ) from error
        
        if isinstance(error, google_exceptions.GoogleAPIError):
            raise TranscriptionAPIError(
                f"Google Cloud Speech API error: {type(error).__name__}",
                error_code=str(getattr(error, 'code', 'unknown'))
            ) from error
        
        raise TranscriptionAPIError(
            f"Unexpected transcription error: {type(error).__name__}"
        ) from error
    
    def transcribe(
        self,
        audio_data: bytes,
        language_code: Optional[str] = None,
        enable_word_time_offsets: bool = False,
        timeout: Optional[float] = None
    ) -> TranscriptionResult:
        """
        Transcribe audio data to text.
        
        Args:
            audio_data: FLAC audio data at 16kHz
            language_code: Language code (default from config)
            enable_word_time_offsets: Include word-level timing
            timeout: Request timeout in seconds (default from config)
        
        Returns:
            TranscriptionResult with transcription and metadata
        
        Raises:
            TranscriptionError: If transcription fails
            NoSpeechDetectedError: If no speech is detected
        """
        # Use defaults from config
        if language_code is None:
            language_code = self.config.audio.default_language
        if timeout is None:
            timeout = self.config.performance.transcription_timeout
        
        # Estimate duration (rough estimate: 16kHz mono FLAC ~ 2 bytes/sample)
        estimated_duration = len(audio_data) / (16000 * 2)
        
        self._logger.debug(
            "Starting transcription",
            audio_size_bytes=len(audio_data),
            language_code=language_code,
            estimated_duration=round(estimated_duration, 2)
        )
        
        start_time = time.perf_counter()
        
        try:
            # Build request
            config = self._build_recognition_config(
                language_code=language_code,
                enable_word_time_offsets=enable_word_time_offsets
            )
            audio = self._build_recognition_audio(audio_data)
            
            # Make API call
            response = self.client.recognize(
                config=config,
                audio=audio,
                timeout=timeout
            )
            
            # Parse response
            result = self._parse_response(response, language_code, estimated_duration)
            
            processing_time = (time.perf_counter() - start_time) * 1000
            
            self._logger.info(
                "Transcription completed",
                confidence=round(result.confidence, 3),
                language_code=result.language_code,
                processing_time_ms=round(processing_time, 2),
                word_count=len(result.text.split()) if result.text else 0
            )
            
            return result
            
        except NoSpeechDetectedError:
            # Re-raise without wrapping
            self._logger.warning(
                "No speech detected in audio",
                audio_size_bytes=len(audio_data)
            )
            raise
            
        except google_exceptions.GoogleAPIError as e:
            self._logger.error(
                "Transcription API error",
                error_type=type(e).__name__,
                audio_size_bytes=len(audio_data)
            )
            self._handle_api_error(e)
            
        except Exception as e:
            self._logger.error(
                "Unexpected transcription error",
                error_type=type(e).__name__
            )
            raise TranscriptionAPIError(
                f"Unexpected error during transcription: {type(e).__name__}"
            ) from e
    
    def transcribe_with_retry(
        self,
        audio_data: bytes,
        language_code: Optional[str] = None,
        enable_word_time_offsets: bool = False,
        max_attempts: Optional[int] = None,
        retry_delay: Optional[float] = None
    ) -> TranscriptionResult:
        """
        Transcribe audio with automatic retry for transient errors.
        
        Args:
            audio_data: FLAC audio data at 16kHz
            language_code: Language code (default from config)
            enable_word_time_offsets: Include word-level timing
            max_attempts: Maximum retry attempts (default from config)
            retry_delay: Base delay between retries (default from config)
        
        Returns:
            TranscriptionResult with transcription and metadata
        
        Raises:
            TranscriptionError: If all retry attempts fail
        """
        # Use defaults from config
        if max_attempts is None:
            max_attempts = self.config.performance.max_retry_attempts
        if retry_delay is None:
            retry_delay = self.config.performance.retry_delay
        
        last_error: Optional[Exception] = None
        
        for attempt in range(max_attempts):
            try:
                return self.transcribe(
                    audio_data=audio_data,
                    language_code=language_code,
                    enable_word_time_offsets=enable_word_time_offsets
                )
                
            except NoSpeechDetectedError:
                # Don't retry if no speech detected
                raise
                
            except TranscriptionError as e:
                last_error = e
                
                # Check if error is retryable
                original_error = e.__cause__ if e.__cause__ else e
                
                if not self._is_retryable_error(original_error):
                    self._logger.warning(
                        "Non-retryable transcription error",
                        error_type=type(e).__name__,
                        attempt=attempt + 1
                    )
                    raise
                
                if attempt < max_attempts - 1:
                    # Calculate exponential backoff delay
                    delay = retry_delay * (2 ** attempt)
                    
                    self._logger.warning(
                        "Retrying transcription after error",
                        error_type=type(e).__name__,
                        attempt=attempt + 1,
                        max_attempts=max_attempts,
                        delay_seconds=delay
                    )
                    
                    time.sleep(delay)
                else:
                    self._logger.error(
                        "Max retry attempts reached",
                        error_type=type(e).__name__,
                        attempts=max_attempts
                    )
        
        # Raise the last error if all retries failed
        if last_error:
            raise last_error
        
        # This shouldn't happen, but just in case
        raise TranscriptionAPIError("Transcription failed after all retry attempts")


# Module-level singleton and convenience functions

_transcriber: Optional[Transcriber] = None


def get_transcriber() -> Transcriber:
    """
    Get the global Transcriber instance.
    
    Returns:
        Singleton Transcriber instance
    """
    global _transcriber
    if _transcriber is None:
        _transcriber = Transcriber()
    return _transcriber


def transcribe(
    audio_data: bytes,
    language_code: Optional[str] = None,
    enable_word_time_offsets: bool = False
) -> TranscriptionResult:
    """
    Transcribe audio data to text.
    
    Convenience function using the global transcriber.
    
    Args:
        audio_data: FLAC audio data at 16kHz
        language_code: Language code (default: "en-US")
        enable_word_time_offsets: Include word-level timing
    
    Returns:
        TranscriptionResult with transcription and metadata
    """
    return get_transcriber().transcribe(
        audio_data=audio_data,
        language_code=language_code,
        enable_word_time_offsets=enable_word_time_offsets
    )


def transcribe_with_retry(
    audio_data: bytes,
    language_code: Optional[str] = None,
    enable_word_time_offsets: bool = False
) -> TranscriptionResult:
    """
    Transcribe audio with automatic retry for transient errors.
    
    Convenience function using the global transcriber.
    
    Args:
        audio_data: FLAC audio data at 16kHz
        language_code: Language code (default: "en-US")
        enable_word_time_offsets: Include word-level timing
    
    Returns:
        TranscriptionResult with transcription and metadata
    """
    return get_transcriber().transcribe_with_retry(
        audio_data=audio_data,
        language_code=language_code,
        enable_word_time_offsets=enable_word_time_offsets
    )
