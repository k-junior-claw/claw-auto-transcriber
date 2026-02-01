# Claw Auto-Transcriber - Project Specification

## Overview

**Project:** Auto-transcriber for voice recordings on Telegram channel  
**Repository:** https://github.com/k-junior-claw/claw-auto-transcriber  
**Platform:** Python  
**Transcription Service:** Google Cloud Speech-to-Text (STT)  
**Primary Channel:** Telegram

## 1. Components & Module Design

### Core Components

#### 1.1 Telegram Bot Handler (`telegram_bot.py`)
**Responsibilities:**
- Initialize and manage Telegram bot connection
- Receive voice messages from Telegram channel
- Process audio file downloads from Telegram
- Send transcription results back to Telegram
- Handle user commands and interactions

**Key Functions:**
- `start_bot()` - Initialize bot listener
- `download_voice_message(msg)` - Download audio from Telegram
- `send_transcription(chat_id, transcription)` - Return results
- `handle_error(error_msg, chat_id)` - Error reporting

#### 1.2 Google Cloud STT Integration (`transcriber.py`)
**Responsibilities:**
- Authenticate with Google Cloud using service account credentials
- Convert audio files to formats compatible with STT API
- Send audio to Google Cloud Speech-to-Text
- Parse transcription responses
- Handle API errors and retries

**Key Functions:**
- `initialize_stt_client()` - Setup Google Cloud connection
- `transcribe_audio(audio_file_path)` - Main transcription function
- `convert_audio_format(input_path, output_path)` - Format conversion
- `parse_transcription_response(response)` - Extract text from API response

#### 1.3 Audio Processing Module (`audio_processor.py`)
**Responsibilities:**
- Verify audio file format and compatibility
- Convert Telegram audio (OGG) to Google Cloud STT compatible format (FLAC)
- Validate audio quality and duration limits
- Extract audio metadata
- Manage temporary audio files

**Key Functions:**
- `validate_audio(file_path)` - Check format/size constraints
- `convert_ogg_to_flac(ogg_path, flac_path)` - Convert format
- `get_audio_duration(file_path)` - Check length
- `cleanup_temp_files()` - Remove processed files

#### 1.4 Configuration Manager (`config.py`)
**Responsibilities:**
- Load and validate environment variables
- Manage Google Cloud credentials
- Store Telegram bot token
- Provide configuration defaults

**Key Variables:**
- `TELEGRAM_BOT_TOKEN`
- `GOOGLE_CLOUD_PROJECT_ID`
- `GOOGLE_CLOUD_CREDENTIALS_PATH`
- `SUPPORTED_AUDIO_FORMATS`
- `MAX_AUDIO_DURATION` (default: 60 seconds)

#### 1.5 Logger Module (`logger.py`)
**Responsibilities:**
- Application-wide logging configuration
- Structured logging for debugging
- Error tracking and reporting
- Performance metrics logging

### Secondary Components

#### 1.6 Testing Suite (`tests/`)
**Purpose:** Comprehensive testing of all modules

**Test Categories:**
- Unit tests for each component
- Integration tests for API interactions
- Mock tests for external services

#### 1.7 Documentation (`docs/`)
**Purpose:** User and developer documentation

**Contents:**
- Installation guide
- Configuration instructions
- Usage examples
- API documentation

## 2. Interaction Flow

### 2.1 Voice Message Processing Flow

```
Telegram User → Voice Message → Bot Receives Update
    ↓
Bot Downloads Audio (OGG format)
    ↓
Audio Processor Validates & Converts (OGG → FLAC)
    ↓
Transcriber Sends to Google Cloud STT
    ↓
Google Cloud Returns Transcription
    ↓
Bot Formats Response
    ↓
Bot Sends Transcription to Telegram
```

### 2.2 Authentication Flow

```
Application Start → Config Loader Reads .env
    ↓
Validate Telegram Bot Token
    ↓
Validate Google Cloud Credentials
    ↓
Initialize Google STT Client
    ↓
Start Telegram Bot Polling
    ↓
Ready to Receive Messages
```

### 2.3 Error Handling Flow

```
Error Occurs → Logger Captures Details
    ↓
Determine Error Type (Network, API, Audio, etc.)
    ↓
Retry Logic (if applicable, max 3 attempts)
    ↓
Send User-Friendly Error Message to Telegram
    ↓
Log Final Error State
```

## 3. Data Design

### 3.1 Configuration Data (.env file)

```bash
# Telegram
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# Google Cloud
GOOGLE_CLOUD_PROJECT_ID=your_project_id
GOOGLE_APPLICATION_CREDENTIALS=path/to/service_account.json

# Application Settings
MAX_AUDIO_DURATION=60  # seconds
LOG_LEVEL=INFO
```

### 3.2 Temporary Audio Files

**Storage Location:** `/tmp/claw_transcriber/`

**File Naming:** `audio_{timestamp}_{user_id}_{message_id}.{ext}`

**Auto-cleanup:** Files older than 1 hour are automatically removed

### 3.3 Logging Data Structure

```json
{
  "timestamp": "2026-02-01T10:30:00Z",
  "level": "INFO",
  "module": "transcriber",
  "function": "transcribe_audio",
  "message": "Transcription completed successfully",
  "metadata": {
    "audio_duration": 45.2,
    "transcription_length": 156,
    "user_id": 123456789
  }
}
```

### 3.4 Telegram Message Schema

```json
{
  "message_id": 12345,
  "chat_id": 123456789,
  "user_id": 987654321,
  "timestamp": "2026-02-01T10:29:30Z",
  "audio_file_id": "AwACAgQAAxkB...",
  "audio_duration": 45,
  "mime_type": "audio/ogg"
}
```

### 3.5 Transcription Response Schema

```json
{
  "original_message_id": 12345,
  "transcription": "Hello, this is a test message for transcription.",
  "confidence": 0.95,
  "processing_time_ms": 3200,
  "language": "en-US"
}
```

## 4. Implementation Plan

### Phase 1: Project Setup & Configuration (High Priority)

**Duration:** 1-2 days

**Tasks:**
1. ✅ Repository already cloned
2. Create Python virtual environment with uv
3. Install required packages:
   - `python-telegram-bot`
   - `google-cloud-speech`
   - `pydub` (for audio conversion)
   - `python-dotenv`
   - `structlog` (for logging)
4. Create `.env.template` file with all required variables
5. Set up `.gitignore` to exclude `.env` and credentials
6. Initialize logger module

### Phase 2: Core Module Development (High Priority)

**Duration:** 3-4 days

**Tasks:**
1. **Config Module** (`config.py`)
   - Load environment variables
   - Validate required settings
   - Provide configuration defaults
   
2. **Logger Module** (`logger.py`)
   - Set up structured logging
   - Configure file and console handlers
   - Add performance timing functions
   
3. **Audio Processor** (`audio_processor.py`)
   - Implement audio validation
   - Create conversion functions (OGG → FLAC)
   - Add duration checking
   - Implement cleanup utilities
   
4. **Google STT Client** (`transcriber.py`)
   - Initialize Google Cloud client
   - Create audio upload and transcription functions
   - Implement error handling and retries
   - Parse and format responses

### Phase 3: Telegram Bot Integration (High Priority)

**Duration:** 2-3 days

**Tasks:**
1. **Bot Handler** (`telegram_bot.py`)
   - Initialize Telegram bot
   - Set up command handlers (/start, /help, etc.)
   - Implement voice message detection
   - Add audio download functionality
   - Send responses back to users
2. Connect bot to main application loop
3. Add user-friendly error messages

### Phase 4: Integration & Testing (Medium Priority)

**Duration:** 2-3 days

**Tasks:**
1. **Main Application** (`main.py`)
   - Wire all components together
   - Create application entry point
   - Add graceful shutdown handling
2. **Integration Testing**
   - Test full flow: Telegram → Audio → STT → Response
   - Mock external APIs for testing
   - Performance testing with various audio lengths
3. **Error Handling**
   - Add comprehensive error handling
   - Test error messages in Telegram
   - Verify retry logic

### Phase 5: Documentation & Deployment (Low Priority)

**Duration:** 1-2 days

**Tasks:**
1. **Documentation** (`README.md`)
   - Installation instructions
   - Configuration guide
   - Usage examples
   - Troubleshooting section
2. **Setup Guide** (`docs/setup.md`)
   - Detailed setup instructions
   - Google Cloud project configuration
   - Telegram bot creation guide
3. **Deploy** (future)
   - Deployment configuration
   - Docker setup (optional)
   - Monitoring setup

## 5. File Structure

```
claw-auto-transcriber/
├── .env.template                          # Environment variables template
├── .gitignore                            # Git ignore patterns
├── requirements.txt                      # Python dependencies
├── README.md                             # Project overview
├── main.py                               # Application entry point
├── config.py                             # Configuration management
├── logger.py                             # Logging utilities
├── telegram_bot.py                       # Telegram integration
├── audio_processor.py                    # Audio handling
├── transcriber.py                        # Google STT integration
├── tests/
│   ├── __init__.py
│   ├── test_telegram_bot.py
│   ├── test_audio_processor.py
│   ├── test_transcriber.py
│   └── fixtures/                         # Test audio files
└── docs/
    ├── setup.md                          # Setup instructions
    └── architecture.md                   # Architecture details
```

## 6. Security & Best Practices

### 6.1 Credential Management
- **NEVER commit** `.env` file or service account keys
- Use `.env` or environment variables for all secrets
- Store sensitive files outside version control
- Rotate credentials regularly

### 6.2 Telegram Bot Security
- Use webhook URLs with random tokens
- Validate incoming requests
- Rate limit requests to prevent abuse

### 6.3 Google Cloud Security
- Use service accounts with minimal permissions
- Follow principle of least privilege
- Monitor API usage and costs

### 6.4 Code Quality
- Use type hints throughout
- Write docstrings for all functions
- Keep functions small and focused
- Follow PEP 8 style guide

## 7. Testing Strategy

### 7.1 Unit Tests (70% coverage goal)
- Test each module independently
- Mock external dependencies
- Test edge cases and error conditions

### 7.2 Integration Tests
- Test component interactions
- Verify full data flow
- Test with real (but safe) data

### 7.3 Performance Tests
- Test with various audio lengths (1s, 10s, 30s, 60s)
- Measure processing time
- Monitor memory usage

## 8. Future Enhancements (Out of Scope for Initial Implementation)

- Support for longer audio (>60 seconds)
- Speaker diarization
- Multi-language support
- Batch processing of multiple audio files
- Web dashboard for monitoring
- Cloud deployment automation

---

**Last Updated:** 2026-02-01  
**Version:** 1.0  
**Status:** Ready for Review