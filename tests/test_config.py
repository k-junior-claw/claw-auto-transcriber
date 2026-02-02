"""
Tests for the configuration module.

Tests:
- Environment variable loading
- Configuration validation
- Google Cloud credential validation
- Default values
- Error handling
"""

import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.config import (
    Config,
    ConfigurationError,
    CredentialError,
    GoogleCloudConfig,
    MCPServerConfig,
    AudioConfig,
    SecurityConfig,
    PerformanceConfig,
    LoggingConfig,
    LogLevel,
    LogFormat,
    get_config,
    init_config,
)


class TestGoogleCloudConfig:
    """Tests for GoogleCloudConfig."""
    
    def test_validate_missing_project_id(self, tmp_path):
        """Test validation fails without project ID."""
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps({
            "type": "service_account",
            "project_id": "test",
            "private_key_id": "key123"
        }))
        
        config = GoogleCloudConfig(
            project_id="",
            credentials_path=creds_file
        )
        
        with pytest.raises(ConfigurationError, match="GOOGLE_CLOUD_PROJECT_ID"):
            config.validate()
    
    def test_validate_missing_credentials_file(self, tmp_path):
        """Test validation fails with missing credentials file."""
        config = GoogleCloudConfig(
            project_id="test-project",
            credentials_path=tmp_path / "nonexistent.json"
        )
        
        with pytest.raises(CredentialError, match="not found"):
            config.validate()
    
    def test_validate_invalid_json(self, tmp_path):
        """Test validation fails with invalid JSON."""
        creds_file = tmp_path / "creds.json"
        creds_file.write_text("not valid json")
        
        config = GoogleCloudConfig(
            project_id="test-project",
            credentials_path=creds_file
        )
        
        with pytest.raises(CredentialError, match="not valid JSON"):
            config.validate()
    
    def test_validate_missing_required_fields(self, tmp_path):
        """Test validation fails with missing required fields."""
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps({"type": "service_account"}))
        
        config = GoogleCloudConfig(
            project_id="test-project",
            credentials_path=creds_file
        )
        
        with pytest.raises(CredentialError, match="missing required fields"):
            config.validate()
    
    def test_validate_valid_credentials(self, tmp_path):
        """Test validation passes with valid credentials."""
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps({
            "type": "service_account",
            "project_id": "test",
            "private_key_id": "key123"
        }))
        
        config = GoogleCloudConfig(
            project_id="test-project",
            credentials_path=creds_file
        )
        
        # Should not raise
        config.validate()


class TestMCPServerConfig:
    """Tests for MCPServerConfig."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = MCPServerConfig()
        
        assert config.host == "localhost"
        assert config.port == 8765
        assert config.name == "claw-auto-transcriber"
    
    def test_validate_invalid_port_low(self):
        """Test validation fails with port below 1."""
        config = MCPServerConfig(port=0)
        
        with pytest.raises(ConfigurationError, match="Invalid port"):
            config.validate()
    
    def test_validate_invalid_port_high(self):
        """Test validation fails with port above 65535."""
        config = MCPServerConfig(port=70000)
        
        with pytest.raises(ConfigurationError, match="Invalid port"):
            config.validate()
    
    def test_validate_empty_name(self):
        """Test validation fails with empty name."""
        config = MCPServerConfig(name="")
        
        with pytest.raises(ConfigurationError, match="cannot be empty"):
            config.validate()
    
    def test_validate_valid_config(self):
        """Test validation passes with valid config."""
        config = MCPServerConfig(
            host="0.0.0.0",
            port=8080,
            name="test-server"
        )
        
        # Should not raise
        config.validate()


class TestAudioConfig:
    """Tests for AudioConfig."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = AudioConfig()
        
        assert config.max_duration == 60
        assert config.max_size == 10 * 1024 * 1024
        assert "ogg" in config.supported_formats
        assert config.default_language == "en-US"
    
    def test_validate_invalid_duration_zero(self):
        """Test validation fails with zero duration."""
        config = AudioConfig(max_duration=0)
        
        with pytest.raises(ConfigurationError, match="must be positive"):
            config.validate()
    
    def test_validate_invalid_duration_too_long(self):
        """Test validation fails with duration over 300s."""
        config = AudioConfig(max_duration=400)
        
        with pytest.raises(ConfigurationError, match="cannot exceed 300"):
            config.validate()
    
    def test_validate_invalid_size(self):
        """Test validation fails with zero size."""
        config = AudioConfig(max_size=0)
        
        with pytest.raises(ConfigurationError, match="must be positive"):
            config.validate()
    
    def test_validate_empty_formats(self):
        """Test validation fails with no supported formats."""
        config = AudioConfig(supported_formats=[])
        
        with pytest.raises(ConfigurationError, match="at least one"):
            config.validate()


class TestSecurityConfig:
    """Tests for SecurityConfig."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = SecurityConfig()
        
        assert config.require_authentication is False
        assert config.rate_limit_per_minute == 60
        assert config.max_concurrent_invocations == 10
    
    def test_validate_invalid_rate_limit(self):
        """Test validation fails with zero rate limit."""
        config = SecurityConfig(rate_limit_per_minute=0)
        
        with pytest.raises(ConfigurationError, match="must be positive"):
            config.validate()
    
    def test_validate_invalid_concurrent(self):
        """Test validation fails with zero concurrent invocations."""
        config = SecurityConfig(max_concurrent_invocations=0)
        
        with pytest.raises(ConfigurationError, match="must be positive"):
            config.validate()


class TestPerformanceConfig:
    """Tests for PerformanceConfig."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = PerformanceConfig()
        
        assert config.transcription_timeout == 30
        assert config.max_retry_attempts == 3
        assert config.retry_delay == 1.0
    
    def test_validate_invalid_timeout(self):
        """Test validation fails with zero timeout."""
        config = PerformanceConfig(transcription_timeout=0)
        
        with pytest.raises(ConfigurationError, match="must be positive"):
            config.validate()
    
    def test_validate_negative_retry_attempts(self):
        """Test validation fails with negative retry attempts."""
        config = PerformanceConfig(max_retry_attempts=-1)
        
        with pytest.raises(ConfigurationError, match="cannot be negative"):
            config.validate()
    
    def test_validate_negative_retry_delay(self):
        """Test validation fails with negative retry delay."""
        config = PerformanceConfig(retry_delay=-0.5)
        
        with pytest.raises(ConfigurationError, match="cannot be negative"):
            config.validate()


class TestConfig:
    """Tests for the main Config class."""
    
    def test_load_default_values(self):
        """Test loading configuration with default values."""
        with patch.dict(os.environ, {}, clear=True):
            config = Config()
            config.load(validate_credentials=False)
            
            assert config.mcp_server.host == "localhost"
            assert config.mcp_server.port == 8765
            assert config.audio.max_duration == 60
    
    def test_load_from_environment(self):
        """Test loading configuration from environment variables."""
        env_vars = {
            "MCP_SERVER_HOST": "0.0.0.0",
            "MCP_SERVER_PORT": "9000",
            "MAX_AUDIO_DURATION": "120",
            "LOG_LEVEL": "DEBUG",
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            config = Config()
            config.load(validate_credentials=False)
            
            assert config.mcp_server.host == "0.0.0.0"
            assert config.mcp_server.port == 9000
            assert config.audio.max_duration == 120
            assert config.logging.level == LogLevel.DEBUG
    
    def test_load_from_env_file(self, tmp_path):
        """Test loading configuration from .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("""
MCP_SERVER_PORT=7777
MAX_AUDIO_DURATION=90
""")
        
        config = Config(env_file=env_file)
        config.load(validate_credentials=False)
        
        assert config.mcp_server.port == 7777
        assert config.audio.max_duration == 90
    
    def test_validate_not_loaded(self):
        """Test validation fails if not loaded."""
        config = Config()
        
        with pytest.raises(ConfigurationError, match="not loaded"):
            config.validate()
    
    def test_validate_skip_google_cloud(self):
        """Test validation can skip Google Cloud validation."""
        config = Config()
        config.load(validate_credentials=False)
        
        # Should not raise even without Google Cloud credentials
        config.validate(skip_google_cloud=True)
    
    def test_ensure_temp_dir(self, tmp_path):
        """Test ensuring temp directory exists."""
        config = Config()
        config.load(validate_credentials=False)
        config.audio.temp_dir = tmp_path / "test_temp"
        
        result = config.ensure_temp_dir()
        
        assert result.exists()
        assert result.is_dir()
    
    def test_is_format_supported(self):
        """Test checking if format is supported."""
        config = Config()
        config.load(validate_credentials=False)
        
        assert config.is_format_supported("ogg") is True
        assert config.is_format_supported("OGG") is True
        assert config.is_format_supported(" ogg ") is True
        assert config.is_format_supported("xyz") is False
    
    def test_get_credentials_env(self, tmp_path):
        """Test getting credentials environment variables."""
        creds_file = tmp_path / "creds.json"
        creds_file.write_text("{}")
        
        config = Config()
        config.load(validate_credentials=False)
        config.google_cloud = GoogleCloudConfig(
            project_id="test",
            credentials_path=creds_file
        )
        
        env = config.get_credentials_env()
        
        assert "GOOGLE_APPLICATION_CREDENTIALS" in env
        assert str(creds_file) in env["GOOGLE_APPLICATION_CREDENTIALS"]
    
    def test_repr(self):
        """Test string representation."""
        config = Config()
        config.load(validate_credentials=False)
        
        repr_str = repr(config)
        
        assert "Config(" in repr_str
        assert "loaded=True" in repr_str


class TestGlobalConfig:
    """Tests for global configuration functions."""
    
    def test_get_config_creates_instance(self):
        """Test get_config creates an instance."""
        with patch.dict(os.environ, {}, clear=True):
            # Clear any cached config
            import src.config as config_module
            config_module._config = None
            
            result = get_config()
            
            assert result is not None
            assert isinstance(result, Config)
    
    def test_get_config_returns_cached(self):
        """Test get_config returns cached instance."""
        import src.config as config_module
        config_module._config = None
        
        config1 = get_config()
        config2 = get_config()
        
        assert config1 is config2
    
    def test_get_config_reload(self):
        """Test get_config with reload."""
        import src.config as config_module
        config_module._config = None
        
        config1 = get_config()
        config2 = get_config(reload=True)
        
        assert config1 is not config2
    
    def test_init_config(self, tmp_path):
        """Test init_config function."""
        import src.config as config_module
        config_module._config = None
        
        result = init_config(validate_credentials=False)
        
        assert result is not None
        assert result._loaded is True
