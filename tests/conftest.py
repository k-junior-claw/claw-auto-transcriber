"""
Pytest configuration and shared fixtures for the test suite.

This module provides:
- Common fixtures for testing
- Test configuration
- Shared mocks and utilities
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def reset_global_state():
    """Reset global state between tests."""
    # Reset config singleton
    import src.config as config_module
    config_module._config = None
    
    # Reset audio processor singleton
    import src.audio_processor as audio_module
    audio_module._processor = None
    
    yield
    
    # Cleanup after test
    config_module._config = None
    audio_module._processor = None


@pytest.fixture
def temp_dir():
    """Provide a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_env_vars():
    """Provide a context manager for mocking environment variables."""
    original_env = os.environ.copy()
    
    def set_vars(vars_dict):
        os.environ.clear()
        os.environ.update(vars_dict)
    
    yield set_vars
    
    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def sample_ogg_header():
    """Provide sample OGG header bytes."""
    return b"OggS" + b"\x00" * 1000


@pytest.fixture
def sample_mp3_header():
    """Provide sample MP3 header bytes."""
    return b"ID3" + b"\x00" * 1000


@pytest.fixture
def sample_wav_header():
    """Provide sample WAV header bytes."""
    return b"RIFF" + b"\x00\x00\x00\x00WAVEfmt " + b"\x00" * 992


@pytest.fixture
def sample_flac_header():
    """Provide sample FLAC header bytes."""
    return b"fLaC" + b"\x00" * 1000


@pytest.fixture
def mock_audio_segment():
    """Provide a mock pydub AudioSegment."""
    mock = MagicMock()
    mock.__len__ = MagicMock(return_value=2000)  # 2 seconds
    mock.frame_rate = 16000
    mock.channels = 1
    mock.set_channels.return_value = mock
    mock.set_frame_rate.return_value = mock
    
    def mock_export(output, format):
        output.write(b"fLaC_mock_data")
    mock.export.side_effect = mock_export
    
    return mock


@pytest.fixture
def mock_google_credentials(temp_dir):
    """Provide mock Google Cloud credentials file."""
    import json
    
    creds_file = temp_dir / "service-account.json"
    creds_data = {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "key123",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMOCK\n-----END PRIVATE KEY-----\n",
        "client_email": "test@test-project.iam.gserviceaccount.com",
        "client_id": "123456789",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    creds_file.write_text(json.dumps(creds_data))
    
    return creds_file


# Markers for different test categories
def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
