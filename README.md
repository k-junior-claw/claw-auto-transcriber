# Claw Auto-Transcriber

An MCP (Model Context Protocol) server that provides audio transcription capabilities using Google Cloud Speech-to-Text.

## Overview

Claw Auto-Transcriber is a lightweight MCP server that exposes a `transcribe_audio` tool for converting voice messages and audio files to text. It's designed to be used by AI agents (like Claude) to process audio input as part of conversational workflows.

### Key Features

- **MCP Protocol Compliant**: Standard MCP server implementation using stdio transport
- **Multiple Audio Formats**: Supports OGG, MP3, WAV, and FLAC audio files
- **Google Cloud STT**: High-quality transcription using Google Cloud Speech-to-Text
- **Privacy-First**: Audio content is never logged; ephemeral processing with immediate cleanup
- **Configurable**: Extensive configuration via environment variables
- **Production Ready**: Includes Docker, systemd, and monitoring support

### Architecture

```
┌─────────────────┐     ┌──────────────────────────────────────────────────┐
│   MCP Client    │     │           Claw Auto-Transcriber                  │
│  (Claude, etc)  │────▶│  ┌─────────────┐  ┌──────────┐  ┌────────────┐  │
│                 │◀────│  │ MCP Server  │─▶│ Audio    │─▶│ Google     │  │
│                 │     │  │             │  │ Processor│  │ Cloud STT  │  │
└─────────────────┘     │  └─────────────┘  └──────────┘  └────────────┘  │
                        └──────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.10 or higher
- Google Cloud account with Speech-to-Text API enabled
- FFmpeg (optional, for fallback audio conversion)

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/k-junior-claw/claw-auto-transcriber.git
   cd claw-auto-transcriber
   ```

2. **Create virtual environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # Linux/macOS
   # or: venv\Scripts\activate  # Windows
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**:
   ```bash
   cp .env.template .env
   # Edit .env with your Google Cloud credentials
   ```

5. **Run the server**:
   ```bash
   python -m src.mcp_server
   ```

See [docs/setup.md](docs/setup.md) for detailed setup instructions including Google Cloud configuration.

## Configuration

All configuration is done via environment variables. Copy `.env.template` to `.env` and customize:

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `GOOGLE_CLOUD_PROJECT_ID` | Your Google Cloud project ID | `my-project-123` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON | `./credentials/sa.json` |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_SERVER_NAME` | `claw-auto-transcriber` | Server identifier |
| `MAX_AUDIO_DURATION` | `60` | Maximum audio duration in seconds |
| `MAX_AUDIO_SIZE` | `10485760` | Maximum file size in bytes (10MB) |
| `DEFAULT_LANGUAGE_CODE` | `en-US` | Default language for transcription |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `LOG_FORMAT` | `json` | Log format (json or text) |

See [.env.template](.env.template) for all available options.

## API Reference

### transcribe_audio Tool

The server exposes a single tool: `transcribe_audio`

#### Input Schema

```json
{
  "audio_data": {
    "type": "string",
    "description": "Base64-encoded audio file (OGG, MP3, WAV, or FLAC)",
    "required": true
  },
  "metadata": {
    "type": "object",
    "properties": {
      "original_format": {
        "type": "string",
        "enum": ["ogg", "mp3", "wav", "flac"],
        "description": "Format hint for the audio"
      },
      "language_code": {
        "type": "string",
        "description": "BCP-47 language code (e.g., 'en-US', 'es-ES')"
      },
      "user_id": {
        "type": "string",
        "description": "User identifier for tracking"
      },
      "message_id": {
        "type": "string",
        "description": "Message identifier for tracking"
      }
    }
  }
}
```

#### Response Format

**Success Response:**
```json
{
  "success": true,
  "transcription": "Hello, how are you today?",
  "confidence": 0.95,
  "language_code": "en-US",
  "duration_seconds": 2.5,
  "word_count": 5,
  "processing_time_ms": 1250.5,
  "metadata": {
    "invocation_id": "inv_abc123",
    "original_format": "ogg"
  }
}
```

**Error Response:**
```json
{
  "success": false,
  "transcription": null,
  "confidence": null,
  "language_code": "en-US",
  "duration_seconds": 0,
  "word_count": 0,
  "processing_time_ms": 150.2,
  "error": "Audio exceeds maximum duration (60 seconds)",
  "error_type": "duration_error"
}
```

#### Error Types

| Error Type | Description |
|------------|-------------|
| `validation_error` | Invalid audio format or corrupted file |
| `duration_error` | Audio exceeds maximum duration |
| `size_error` | File exceeds maximum size |
| `format_error` | Unsupported audio format |
| `conversion_error` | Failed to convert audio |
| `timeout_error` | Transcription request timed out |
| `quota_error` | Google Cloud quota exceeded |
| `api_error` | Google Cloud API error |
| `transcription_error` | General transcription failure |

## MCP Client Configuration

### Claude Desktop

Add to your Claude Desktop configuration (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "claw-transcriber": {
      "command": "python",
      "args": ["-m", "src.mcp_server"],
      "cwd": "/path/to/claw-auto-transcriber",
      "env": {
        "GOOGLE_CLOUD_PROJECT_ID": "your-project-id",
        "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/credentials.json"
      }
    }
  }
}
```

See [docs/mcp-client-config.md](docs/mcp-client-config.md) for more client configurations.

## Development

### Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=src --cov-report=term-missing

# Run specific test file
python -m pytest tests/test_transcriber.py -v
```

### Project Structure

```
claw-auto-transcriber/
├── src/                    # Source code
│   ├── mcp_server.py      # MCP server implementation
│   ├── audio_processor.py # Audio validation and conversion
│   ├── transcriber.py     # Google Cloud STT integration
│   ├── config.py          # Configuration management
│   └── logger.py          # Logging utilities
├── tools/
│   └── transcribe_audio.py # Tool definition
├── tests/                  # Test suite (262 tests)
├── docs/                   # Documentation
├── deployment/             # Deployment configs
├── .env.template          # Environment template
├── requirements.txt       # Python dependencies
└── pyproject.toml         # Project configuration
```

## Deployment

### Docker

```bash
# Build image
docker build -t claw-transcriber .

# Run container
docker run -d \
  -e GOOGLE_CLOUD_PROJECT_ID=your-project \
  -v /path/to/credentials.json:/app/credentials/sa.json:ro \
  claw-transcriber
```

### systemd (Linux)

```bash
# Copy service file
sudo cp deployment/claw-transcriber.service /etc/systemd/system/

# Enable and start
sudo systemctl enable claw-transcriber
sudo systemctl start claw-transcriber
```

See [docs/setup.md](docs/setup.md) for detailed deployment instructions.

## Security Considerations

- **Credentials**: Never commit Google Cloud credentials to version control
- **Logging**: Audio content and transcription text are never logged
- **Ephemeral**: Audio files are processed in memory and immediately discarded
- **Validation**: All inputs are validated before processing

## Troubleshooting

### Common Issues

**"Invalid credentials" error**
- Verify `GOOGLE_APPLICATION_CREDENTIALS` points to a valid service account JSON file
- Ensure the service account has the `Cloud Speech-to-Text API User` role

**"Audio format not supported" error**
- Verify the audio is one of: OGG, MP3, WAV, FLAC
- If using OGG files and soundfile fails, install FFmpeg as fallback: `sudo apt install ffmpeg`

**"Audio duration exceeded" error**
- Default max duration is 60 seconds
- Increase with `MAX_AUDIO_DURATION` environment variable

See [docs/usage-examples.md](docs/usage-examples.md) for more troubleshooting tips.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Submit a pull request

All changes must pass the existing test suite.
