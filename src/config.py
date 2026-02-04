"""
Configuration Manager for Claw Auto-Transcriber MCP Server.

Handles:
- Environment variable loading
- Google Cloud credential validation
- Configuration defaults
- Runtime configuration validation

Security Note: No sensitive values are logged. Paths and IDs are validated but not exposed.
"""

import os
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum

from dotenv import load_dotenv


class LogLevel(Enum):
    """Supported log levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogFormat(Enum):
    """Supported log formats."""
    JSON = "json"
    TEXT = "text"


class ConfigurationError(Exception):
    """Raised when configuration is invalid or missing."""
    pass


class CredentialError(Exception):
    """Raised when Google Cloud credentials are invalid or missing."""
    pass


@dataclass
class GoogleCloudConfig:
    """Google Cloud configuration settings."""
    project_id: str
    credentials_path: Path
    
    def validate(self) -> None:
        """Validate Google Cloud configuration.
        
        Raises:
            ConfigurationError: If project_id is empty
            CredentialError: If credentials file is missing or invalid
        """
        if not self.project_id:
            raise ConfigurationError("GOOGLE_CLOUD_PROJECT_ID is required")
        
        if not self.credentials_path.exists():
            raise CredentialError(
                f"Google Cloud credentials file not found at configured path. "
                f"Ensure GOOGLE_APPLICATION_CREDENTIALS points to a valid file."
            )
        
        # Validate JSON structure (without logging contents)
        try:
            with open(self.credentials_path, 'r') as f:
                creds = json.load(f)
                required_fields = ['type', 'project_id', 'private_key_id']
                missing = [f for f in required_fields if f not in creds]
                if missing:
                    raise CredentialError(
                        "Invalid credentials file: missing required fields"
                    )
        except json.JSONDecodeError:
            raise CredentialError("Invalid credentials file: not valid JSON")
        except PermissionError:
            raise CredentialError("Cannot read credentials file: permission denied")


@dataclass
class MCPServerConfig:
    """MCP Server configuration settings."""
    host: str = "localhost"
    port: int = 8765
    name: str = "claw-auto-transcriber"
    
    def validate(self) -> None:
        """Validate MCP server configuration.
        
        Raises:
            ConfigurationError: If port is invalid
        """
        if not (1 <= self.port <= 65535):
            raise ConfigurationError(f"Invalid port number: {self.port}")
        if not self.name:
            raise ConfigurationError("MCP_SERVER_NAME cannot be empty")


@dataclass
class AudioConfig:
    """Audio processing configuration settings."""
    max_duration: int = 60  # seconds
    max_size: int = 10 * 1024 * 1024  # 10MB
    temp_dir: Path = field(default_factory=lambda: Path("/tmp/claw_transcriber"))
    supported_formats: List[str] = field(default_factory=lambda: ["ogg", "mp3", "wav", "flac"])
    default_language: str = "en-US"
    
    def validate(self) -> None:
        """Validate audio configuration.
        
        Raises:
            ConfigurationError: If configuration values are invalid
        """
        if self.max_duration <= 0:
            raise ConfigurationError("MAX_AUDIO_DURATION must be positive")
        if self.max_duration > 300:
            raise ConfigurationError("MAX_AUDIO_DURATION cannot exceed 300 seconds")
        if self.max_size <= 0:
            raise ConfigurationError("MAX_AUDIO_SIZE must be positive")
        if not self.supported_formats:
            raise ConfigurationError("at least one audio format must be supported")


@dataclass
class SecurityConfig:
    """Security configuration settings."""
    require_authentication: bool = False
    rate_limit_per_minute: int = 60
    max_concurrent_invocations: int = 10
    
    def validate(self) -> None:
        """Validate security configuration.
        
        Raises:
            ConfigurationError: If configuration values are invalid
        """
        if self.rate_limit_per_minute <= 0:
            raise ConfigurationError("RATE_LIMIT_PER_MINUTE must be positive")
        if self.max_concurrent_invocations <= 0:
            raise ConfigurationError("MAX_CONCURRENT_INVOCATIONS must be positive")


@dataclass
class PerformanceConfig:
    """Performance configuration settings."""
    transcription_timeout: int = 30  # seconds
    max_retry_attempts: int = 3
    retry_delay: float = 1.0  # seconds
    
    def validate(self) -> None:
        """Validate performance configuration.
        
        Raises:
            ConfigurationError: If configuration values are invalid
        """
        if self.transcription_timeout <= 0:
            raise ConfigurationError("TRANSCRIPTION_TIMEOUT must be positive")
        if self.max_retry_attempts < 0:
            raise ConfigurationError("MAX_RETRY_ATTEMPTS cannot be negative")
        if self.retry_delay < 0:
            raise ConfigurationError("RETRY_DELAY cannot be negative")


@dataclass
class AsyncTranscriptionConfig:
    """Async transcription configuration settings."""
    input_dir: Path = field(default_factory=lambda: Path("/tmp/claw_transcriber/queue/in"))
    output_dir: Path = field(default_factory=lambda: Path("/tmp/claw_transcriber/queue/out"))
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    max_duration: int = 300  # seconds
    chunk_duration: int = 10  # seconds
    vad_aggressiveness: int = 2  # WebRTC VAD aggressiveness (0-3)
    parallel_chunks: int = 3

    def validate(self) -> None:
        """Validate async transcription configuration."""
        if self.max_file_size <= 0:
            raise ConfigurationError("ASYNC_MAX_FILE_SIZE must be positive")
        if self.max_duration <= 0:
            raise ConfigurationError("ASYNC_MAX_DURATION must be positive")
        if self.max_duration > 300:
            raise ConfigurationError("ASYNC_MAX_DURATION cannot exceed 300 seconds")
        if self.chunk_duration <= 0:
            raise ConfigurationError("ASYNC_CHUNK_DURATION must be positive")
        if self.chunk_duration > 30:
            raise ConfigurationError("ASYNC_CHUNK_DURATION cannot exceed 30 seconds")
        if not (0 <= self.vad_aggressiveness <= 3):
            raise ConfigurationError("ASYNC_VAD_AGGRESSIVENESS must be between 0 and 3")
        if self.parallel_chunks <= 0:
            raise ConfigurationError("ASYNC_PARALLEL_CHUNKS must be positive")


@dataclass
class LoggingConfig:
    """Logging configuration settings."""
    level: LogLevel = LogLevel.INFO
    format: LogFormat = LogFormat.JSON
    
    def validate(self) -> None:
        """Validate logging configuration."""
        # Enum validation is handled during construction
        pass


class Config:
    """
    Main configuration class for the MCP Server.
    
    Loads configuration from environment variables and provides
    validated access to all configuration settings.
    
    Usage:
        config = Config()
        config.load()  # Load from environment
        config.validate()  # Validate all settings
        
        # Access configuration
        print(config.mcp_server.port)
        print(config.audio.max_duration)
    """
    
    def __init__(self, env_file: Optional[Path] = None):
        """Initialize configuration manager.
        
        Args:
            env_file: Optional path to .env file. If not provided,
                     will look for .env in the current directory.
        """
        self._env_file = env_file
        self._loaded = False
        
        # Configuration sections
        self.google_cloud: Optional[GoogleCloudConfig] = None
        self.mcp_server: MCPServerConfig = MCPServerConfig()
        self.audio: AudioConfig = AudioConfig()
        self.security: SecurityConfig = SecurityConfig()
        self.performance: PerformanceConfig = PerformanceConfig()
        self.async_transcription: AsyncTranscriptionConfig = AsyncTranscriptionConfig()
        self.logging: LoggingConfig = LoggingConfig()
    
    def load(self, validate_credentials: bool = True) -> "Config":
        """Load configuration from environment variables.
        
        Args:
            validate_credentials: Whether to validate Google Cloud credentials exist.
                                Set to False for testing without credentials.
        
        Returns:
            Self for method chaining.
        
        Raises:
            ConfigurationError: If required configuration is missing.
        """
        # Load .env file if it exists
        if self._env_file:
            load_dotenv(self._env_file)
        else:
            load_dotenv()
        
        # Load Google Cloud configuration
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT_ID", "")
        creds_path = os.getenv(
            "GOOGLE_APPLICATION_CREDENTIALS",
            "./credentials/service-account.json"
        )
        
        if project_id or validate_credentials:
            self.google_cloud = GoogleCloudConfig(
                project_id=project_id,
                credentials_path=Path(creds_path)
            )
        
        # Load MCP Server configuration
        self.mcp_server = MCPServerConfig(
            host=os.getenv("MCP_SERVER_HOST", "localhost"),
            port=int(os.getenv("MCP_SERVER_PORT", "8765")),
            name=os.getenv("MCP_SERVER_NAME", "claw-auto-transcriber")
        )
        
        # Load Audio configuration
        formats_str = os.getenv("SUPPORTED_AUDIO_FORMATS", "ogg,mp3,wav,flac")
        self.audio = AudioConfig(
            max_duration=int(os.getenv("MAX_AUDIO_DURATION", "60")),
            max_size=int(os.getenv("MAX_AUDIO_SIZE", str(10 * 1024 * 1024))),
            temp_dir=Path(os.getenv("TEMP_AUDIO_DIR", "/tmp/claw_transcriber")),
            supported_formats=[f.strip().lower() for f in formats_str.split(",")],
            default_language=os.getenv("DEFAULT_LANGUAGE_CODE", "en-US")
        )
        
        # Load Security configuration
        self.security = SecurityConfig(
            require_authentication=os.getenv("REQUIRE_AUTHENTICATION", "false").lower() == "true",
            rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "60")),
            max_concurrent_invocations=int(os.getenv("MAX_CONCURRENT_INVOCATIONS", "10"))
        )
        
        # Load Performance configuration
        self.performance = PerformanceConfig(
            transcription_timeout=int(os.getenv("TRANSCRIPTION_TIMEOUT", "30")),
            max_retry_attempts=int(os.getenv("MAX_RETRY_ATTEMPTS", "3")),
            retry_delay=float(os.getenv("RETRY_DELAY", "1"))
        )

        # Load Async transcription configuration
        self.async_transcription = AsyncTranscriptionConfig(
            input_dir=Path(os.getenv("ASYNC_INPUT_DIR", "/tmp/claw_transcriber/queue/in")),
            output_dir=Path(os.getenv("ASYNC_OUTPUT_DIR", "/tmp/claw_transcriber/queue/out")),
            max_file_size=int(os.getenv("ASYNC_MAX_FILE_SIZE", str(10 * 1024 * 1024))),
            max_duration=int(os.getenv("ASYNC_MAX_DURATION", "300")),
            chunk_duration=int(os.getenv("ASYNC_CHUNK_DURATION", "10")),
            vad_aggressiveness=int(os.getenv("ASYNC_VAD_AGGRESSIVENESS", "2")),
            parallel_chunks=int(os.getenv("ASYNC_PARALLEL_CHUNKS", "3"))
        )
        
        # Load Logging configuration
        log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
        log_format_str = os.getenv("LOG_FORMAT", "json").lower()
        
        try:
            log_level = LogLevel[log_level_str]
        except KeyError:
            log_level = LogLevel.INFO
        
        try:
            log_format = LogFormat(log_format_str)
        except ValueError:
            log_format = LogFormat.JSON
        
        self.logging = LoggingConfig(
            level=log_level,
            format=log_format
        )
        
        self._loaded = True
        return self
    
    def validate(self, skip_google_cloud: bool = False) -> "Config":
        """Validate all configuration settings.
        
        Args:
            skip_google_cloud: Skip Google Cloud credential validation.
                             Useful for testing.
        
        Returns:
            Self for method chaining.
        
        Raises:
            ConfigurationError: If any configuration is invalid.
            CredentialError: If Google Cloud credentials are invalid.
        """
        if not self._loaded:
            raise ConfigurationError("Configuration not loaded. Call load() first.")
        
        # Validate each section
        if not skip_google_cloud and self.google_cloud:
            self.google_cloud.validate()
        
        self.mcp_server.validate()
        self.audio.validate()
        self.security.validate()
        self.performance.validate()
        self.async_transcription.validate()
        self.logging.validate()
        
        return self
    
    def ensure_temp_dir(self) -> Path:
        """Ensure the temporary audio directory exists.
        
        Returns:
            Path to the temporary directory.
        """
        self.audio.temp_dir.mkdir(parents=True, exist_ok=True)
        return self.audio.temp_dir

    def ensure_async_dirs(self) -> tuple[Path, Path]:
        """Ensure async queue directories exist.

        Returns:
            Tuple of (input_dir, output_dir).
        """
        self.async_transcription.input_dir.mkdir(parents=True, exist_ok=True)
        self.async_transcription.output_dir.mkdir(parents=True, exist_ok=True)
        return self.async_transcription.input_dir, self.async_transcription.output_dir
    
    def is_format_supported(self, format_str: str) -> bool:
        """Check if an audio format is supported.
        
        Args:
            format_str: Audio format string (e.g., "ogg", "mp3").
        
        Returns:
            True if the format is supported.
        """
        return format_str.lower().strip() in self.audio.supported_formats
    
    def get_credentials_env(self) -> dict:
        """Get environment variables needed for Google Cloud authentication.
        
        Returns:
            Dictionary with GOOGLE_APPLICATION_CREDENTIALS set.
        """
        if self.google_cloud:
            return {
                "GOOGLE_APPLICATION_CREDENTIALS": str(self.google_cloud.credentials_path.absolute())
            }
        return {}
    
    def __repr__(self) -> str:
        """Return string representation (without sensitive data)."""
        return (
            f"Config(loaded={self._loaded}, "
            f"server={self.mcp_server.host}:{self.mcp_server.port}, "
            f"max_audio_duration={self.audio.max_duration}s)"
        )


# Global configuration instance
_config: Optional[Config] = None


def get_config(reload: bool = False) -> Config:
    """Get the global configuration instance.
    
    Args:
        reload: If True, reload configuration from environment.
    
    Returns:
        Loaded and validated configuration.
    """
    global _config
    
    if _config is None or reload:
        _config = Config()
        _config.load(validate_credentials=False)
    
    return _config


def init_config(env_file: Optional[Path] = None, validate_credentials: bool = True) -> Config:
    """Initialize and validate configuration.
    
    Args:
        env_file: Optional path to .env file.
        validate_credentials: Whether to validate Google Cloud credentials.
    
    Returns:
        Loaded and validated configuration.
    
    Raises:
        ConfigurationError: If configuration is invalid.
        CredentialError: If credentials are invalid.
    """
    global _config
    
    _config = Config(env_file)
    _config.load(validate_credentials=validate_credentials)
    _config.validate(skip_google_cloud=not validate_credentials)
    
    return _config
