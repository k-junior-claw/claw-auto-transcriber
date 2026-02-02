# Claw Auto-Transcriber - Project Specification (MCP SERVER v3.0)

## 🔑 KEY ARCHITECTURE CLARIFICATION

**This is an MCP Server, not a Telegram Bot.**

The server provides a `transcribe_audio` tool that I (Kelvin Junior agent) invoke when I need to transcribe voice/audio messages. The transcription becomes a tool response that I then process as input.

**Architecture Flow:**
1. **I receive/process** Telegram messages (as the agent)
2. **When I detect audio**, I invoke the `transcribe_audio` tool from this MCP server
3. **MCP Server** processes: Audio download → Validation → Google STT → Get transcription
4. **I receive transcription** as tool response
5. **I process transcribed text** as if it were regular user input
6. **I generate and send response** back to Telegram

**MCP Server Role:** Only provides the transcription capability as a tool. The agent handles all Telegram interaction and response generation.

---

## Overview

**Project:** MCP Server - Audio Transcription Service  
**Repository:** https://github.com/k-junior-claw/claw-auto-transcriber  
**Platform:** Python  
**Service Type:** MCP (Model Context Protocol) Server  
**Primary Tool:** `transcribe_audio`  
**Transcription Engine:** Google Cloud Speech-to-Text (STT)  
**Key Innovation:** Voice/audio transcription as a reusable MCP tool

**Architecture:**
- **Server:** Implements MCP protocol, provides transcription tool
- **Client:** I (Kelvin Junior agent) invoke the tool when needed
- **Separation of Concerns:** Server handles audio→text, agent handles user interaction

## 1. Components & Module Design

### Core Components

#### 1.1 MCP Server (`mcp_server.py`) - **NEW PRIMARY COMPONENT**
**Responsibilities:**
- Implement MCP (Model Context Protocol)
- Expose `transcribe_audio` tool
- Handle tool invocations from agents
- Manage tool lifecycle
- Provide tool metadata and schema

**Key Functions:**
- `initialize_server()` - Setup MCP server
- `register_tools()` - Register transcribe_audio tool
- `handle_tool_call()` - Process incoming tool invocations
- `get_tool_schema()` - Return tool definition JSON

#### 1.2 Tool Definition (`tools/transcribe_audio.py`) - **NEW COMPONENT**
**Responsibilities:**
- Define transcribe_audio tool interface
- Specify input parameters (audio file, format, etc.)
- Define output schema (transcription, confidence, etc.)
- Validate tool invocation parameters

**Key Functions:**
- `get_tool_schema()` - Return JSON schema for tool
- `validate_inputs(audio_data, metadata)` - Validate invocation
- `format_response(transcription, confidence)` - Format tool response

#### 1.3 Audio Processor (`audio_processor.py`)
**Responsibilities:**
- Receive audio data from tool invocations
- Validate audio format and compatibility
- Convert audio to Google STT format (FLAC)
- Validate audio quality and duration limits
- Manage temporary audio files (ephemeral)

**Key Functions:**
- `validate_audio(audio_bytes)` - Check format/size
- `convert_ogg_to_flac(ogg_bytes)` - Convert format
- `get_audio_duration(audio_data)` - Check length
- `cleanup_temp_files()` - Remove processed files immediately

#### 1.4 Google STT Integration (`transcriber.py`)
**Responsibilities:**
- Authenticate with Google Cloud using service account credentials
- Send audio to Google Cloud Speech-to-Text API
- Parse transcription responses
- Handle API errors and retries
- Extract transcription text and confidence

**Key Functions:**
- `initialize_stt_client()` - Setup Google Cloud connection
- `transcribe_audio(audio_data, metadata)` - Main transcription function
- `parse_transcription_response(response)` - Extract text & confidence

#### 1.5 Configuration Manager (`config.py`)
**Responsibilities:**
- Load environment variables
- Manage Google Cloud credentials
- Provide configuration defaults
- Validate required settings

**Key Variables:**
- `GOOGLE_CLOUD_PROJECT_ID`
- `GOOGLE_APPLICATION_CREDENTIALS_PATH`
- `SUPPORTED_AUDIO_FORMATS`
- `MAX_AUDIO_DURATION` (default: 60 seconds)
- `TEMP_AUDIO_DIR`

#### 1.6 Logger Module (`logger.py`)
**Responsibilities:**
- Application-wide logging configuration
- Structured logging for debugging
- Error tracking and reporting
- Performance metrics logging
- Ensure NO audio content is logged (privacy)

### Secondary Components

#### 1.7 Testing Suite (`tests/`)
**Purpose:** Comprehensive testing of all modules

**Test Categories:**
- Unit tests for each component (80% coverage goal with pytest)
- Integration tests for MCP tool flow
- Mock tests for Google Cloud STT
- Tool invocation and response tests
- Error handling tests

#### 1.8 Documentation (`docs/`)
**Purpose:** User and developer documentation

**Contents:**
- Installation guide
- Configuration instructions
- MCP usage examples
- Tool invocation examples
- API documentation

## 2. Interaction Flow - MCP Tool Invocation

### 2.1 MCP Tool Invocation Sequence (PRIMARY FLOW)

```mermaid
sequenceDiagram
    participant Agent as Kelvin Junior (Agent)
    participant MCP as MCP Server
    participant AudioProc as Audio Processor
    participant Transcriber as Google STT
    participant GCloud as Google Cloud

    Note over Agent,GCloud: Agent detects audio message
    Agent->>MCP: invoke_tool("transcribe_audio", audio_data)
    MCP->>AudioProc: validate_audio(audio_data)
    AudioProc-->>MCP: validation passed
    MCP->>AudioProc: convert_ogg_to_flac(audio_data)
    AudioProc-->>MCP: flac_data
    MCP->>Transcriber: transcribe_audio(flac_data, metadata)
    Transcriber->>GCloud: API request
    GCloud->>Transcriber: transcription result
    Transcriber-->>MCP: {"text": "What's the weather?", "confidence": 0.95}
    MCP-->>Agent: Tool response with transcription
    Note over Agent: Agent processes transcription as input
    Agent->>Agent: generate_response("What's the weather?")
    Agent->>User: Send final response
```

**Flow Description:**
1. **I (agent)** detect a voice message from user on Telegram
2. **I invoke** `transcribe_audio` tool on MCP Server with audio data
3. **MCP Server** validates and converts the audio
4. **MCP Server** sends audio to Google Cloud STT
5. **Google Cloud** returns transcription (e.g., "What's the weather?")
6. **MCP Server** formats and returns tool response to me
7. **I (agent)** receive transcription and treat as user input
8. **I process** the transcribed text like a regular message
9. **I generate and send** appropriate response back to user

**Key Difference:** Unlike a bot, the MCP server **never interacts directly with Telegram**. It only provides the transcription capability that I invoke as a tool.

### 2.2 MCP Protocol Implementation Flow

```mermaid
sequenceDiagram
    participant Client as Agent Client
    participant Server as MCP Server
    participant Tool as Transcribe Tool
    participant Config as Config Manager

    Client->>Server: Initialize connection
    Server->>Config: Load configuration
    Config-->>Server: Config loaded
    Server-->>Client: Server ready
    Client->>Server: List available tools
    Server->>Tool: Get tool schema
    Tool-->>Server: Tool definition JSON
    Server-->>Client: ["transcribe_audio"] + schemas
    Client->>Server: Invoke transcribe_audio(audio_data)
    Server->>Tool: Execute tool(audio_data)
    Tool-->>Server: Process audio → transcription
    Tool-->>Server: {"text": "...", "confidence": 0.95}
    Server-->>Client: Tool response
```

### 2.3 Error Handling in MCP Tool Flow

```mermaid
sequenceDiagram
    participant Agent as Agent
    participant MCP as MCP Server
    participant Logger as Logger

    Agent->>MCP: Invoke transcribe_audio(audio_data)
    alt Audio validation fails
        MCP->>Logger: log_error(invalid_audio)
        Logger-->>MCP: Error logged
        MCP-->>Agent: Tool error: Invalid audio format/file type
    else STT API fails
        MCP->>Logger: log_error(stt_api_failed)
        MCP->>MCP: Retry transcription (max 3 attempts)
        alt Retry succeeds
            MCP-->>Agent: Success with transcription
        else Retry fails
            MCP->>Logger: log_error(final_failure)
            MCP-->>Agent: Tool error: Transcription failed after retries
        end
    else Audio too long
        MCP->>Logger: log_error(duration_exceeded)
        MCP-->>Agent: Tool error: Audio exceeds maximum duration (60s)
    end
```

## 3. Data Design

### 3.1 MCP Tool Schema (JSON)

```json
{
  "tool_name": "transcribe_audio",
  "description": "Transcribe audio/voice messages to text using Google Cloud Speech-to-Text",
  "parameters": {
    "audio_data": {
      "type": "string",
      "format": "base64",
      "description": "Base64-encoded audio file (OGG format from Telegram)"
    },
    "metadata": {
      "type": "object",
      "properties": {
        "original_format": {"type": "string", "enum": ["ogg", "mp3", "wav"]},
        "duration_seconds": {"type": "number"},
        "user_id": {"type": "string"},
        "message_id": {"type": "string"}
      }
    }
  },
  "response_schema": {
    "transcription": {
      "type": "string",
      "description": "The transcribed text from the audio"
    },
    "confidence": {
      "type": "number",
      "minimum": 0,
      "maximum": 1,
      "description": "Confidence score for the transcription (0.0 to 1.0)"
    },
    "language": {
      "type": "string",
      "description": "Detected language code (e.g., 'en-US')"
    },
    "duration": {
      "type": "number",
      "description": "Audio duration in seconds"
    }
  },
  "requirements": {
    "max_duration": 60,
    "supported_formats": ["audio/ogg", "audio/mp3", "audio/wav", "audio/flac"],
    "api_key_required": true
  }
}
```

### 3.2 Configuration Data (.env file)

```bash
# Google Cloud
GOOGLE_CLOUD_PROJECT_ID=your-project-id
GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json

# MCP Server
MCP_SERVER_HOST=localhost
MCP_SERVER_PORT=8765
MCP_SERVER_NAME=claw-auto-transcriber

# Application Settings
MAX_AUDIO_DURATION=60  # seconds
TEMP_AUDIO_DIR=/tmp/claw_transcriber
LOG_LEVEL=INFO

# Security
REQUIRE_AUTHENTICATION=true
RATE_LIMIT_PER_MINUTE=60
```

### 3.3 MCP Server State (Runtime, Ephemeral)

**Storage:** In-memory only (no persistence between server restarts)  
**Lifecycle:** Server start → Tools registered → Connections handled → Server stop

```json
{
  "server_id": "claw-transcriber-001",
  "start_time": "2026-02-01T12:00:00Z",
  "active_connections": 3,
  "tools_registered": ["transcribe_audio"],
  "total_invocations": 157,
  "errors_in_session": 2
}
```

### 3.4 Logging Data Structure (for debugging/monitoring)

```json
{
  "timestamp": "2026-02-01T12:15:30Z",
  "level": "INFO",
  "component": "mcp_server",
  "event": "tool_invoked",
  "metadata": {
    "tool_name": "transcribe_audio",
    "connection_id": "conn_abc123",
    "audio_duration": 3.2,
    "processing_time_ms": 2150
  }
}
```

**Privacy:** No audio content or transcription text is logged. Only metadata for debugging.

### 3.5 Tool Invocation Metadata (Temporary, per-call)

**Storage:** In-memory during tool execution only  
**Lifecycle:** Tool call starts → Created → Processing → Response sent → Discarded

```json
{
  "invocation_id": "invoke_789abc",
  "connection_id": "conn_abc123",
  "tool_name": "transcribe_audio",
  "received_at": "2026-02-01T12:15:30Z",
  "audio_size_bytes": 45000,
  "audio_format": "audio/ogg",
  "processing_time_ms": 2150,
  "status": "completed",
  "error": null
}
```

## 4. Implementation Plan (Revised for MCP Architecture)

### Phase 1: Core Module Development (High Priority)

**Duration:** 3-4 days

**Tasks:**
1. **Setup MCP Server Framework** (`mcp_server.py`)
   - Install MCP Python SDK
   - Create server initialization
   - Implement basic tool registration
   - Setup connection handling

2. **Config Module** (`config.py`)
   - Load environment variables
   - Validate Google Cloud credentials
   - Provide configuration defaults

3. **Logger Module** (`logger.py`)
   - Set up structured logging
   - Configure handlers
   - Add performance timing

4. **Audio Processor** (`audio_processor.py`)
   - Audio validation (format, size, duration)
   - OGG → FLAC conversion for Google STT
   - Implement ephemeral file handling
   - Add privacy-preserving cleanup

### Phase 2: Google STT Integration (High Priority)

**Status:** COMPLETED  
**Duration:** 2-3 days

#### 2.1 Transcriber Module (`src/transcriber.py`)

**Responsibilities:**
- Authenticate with Google Cloud using service account credentials
- Send audio to Google Cloud Speech-to-Text API
- Parse transcription responses with text and confidence
- Handle API errors with retry logic for transient failures
- Integrate with existing logger and config modules

**Key Classes:**

```python
@dataclass
class TranscriptionResult:
    """Result of a transcription operation."""
    text: str                    # Transcribed text
    confidence: float            # Confidence score (0.0 to 1.0)
    language_code: str           # Detected/used language code
    duration_seconds: float      # Audio duration processed
    word_info: Optional[List[WordInfo]]  # Optional word-level timing

class Transcriber:
    """Google Cloud Speech-to-Text client wrapper."""
    def __init__(self, config: Optional[Config] = None, logger: Optional[MCPLogger] = None)
    def transcribe(self, audio_data: bytes, language_code: str = "en-US") -> TranscriptionResult
    def transcribe_with_retry(self, audio_data: bytes, language_code: str = "en-US") -> TranscriptionResult
```

**Key Functions:**
- `initialize_client()` - Setup Google Cloud Speech client with credentials
- `transcribe(audio_data, language_code)` - Main transcription function
- `transcribe_with_retry(audio_data, language_code)` - Transcription with automatic retry
- `_parse_response(response)` - Extract text and confidence from API response
- `_handle_api_error(error)` - Convert Google Cloud errors to custom exceptions

**Exception Classes:**
- `TranscriptionError` - Base exception for transcription errors
- `TranscriptionAPIError` - Google Cloud API errors
- `TranscriptionTimeoutError` - Request timeout errors
- `TranscriptionQuotaError` - API quota exceeded errors
- `NoSpeechDetectedError` - No speech found in audio

**Configuration Integration:**
- Uses `config.google_cloud.project_id` for project identification
- Uses `config.google_cloud.credentials_path` for authentication
- Uses `config.performance.transcription_timeout` for request timeout
- Uses `config.performance.max_retry_attempts` for retry count
- Uses `config.performance.retry_delay` for backoff delay
- Uses `config.audio.default_language` for default language code

**Logging Integration:**
- Uses MCPLogger for all logging (never logs audio content or transcription text)
- Logs metadata: duration, confidence, language_code, processing_time_ms
- Logs errors with error_type (never sensitive details)

#### 2.2 API Request Configuration

**Recognition Config:**
```python
{
    "encoding": RecognitionConfig.AudioEncoding.FLAC,
    "sample_rate_hertz": 16000,
    "language_code": "en-US",
    "enable_automatic_punctuation": True,
    "model": "default",
    "use_enhanced": False,  # Configurable for higher accuracy
}
```

**Retry Strategy:**
- Max attempts: 3 (configurable via `MAX_RETRY_ATTEMPTS`)
- Retry delay: 1.0 seconds (configurable via `RETRY_DELAY`)
- Exponential backoff: delay * (2 ^ attempt_number)
- Retryable errors: ServiceUnavailable, DeadlineExceeded, ResourceExhausted

#### 2.3 Tasks Completed

1. **Google STT Client** (`transcriber.py`)
   - [x] Initialize Google Cloud Speech client with service account
   - [x] Create synchronous transcription function
   - [x] Implement error handling with custom exception hierarchy
   - [x] Implement retry logic with exponential backoff
   - [x] Parse transcription responses (text + confidence)
   - [x] Extract word-level timing (optional)
   - [x] Integration with existing logger (privacy-preserving)
   - [x] Integration with existing config module

2. **Test STT Integration** (`tests/test_transcriber.py`)
   - [x] Unit tests with mocked Google Cloud client
   - [x] Test successful transcription flow
   - [x] Test error handling (API errors, timeouts, quota)
   - [x] Test retry logic (success after retry, max retries exceeded)
   - [x] Test response parsing (single result, multiple alternatives)
   - [x] Test configuration integration
   - [x] Test no speech detected scenario

### Phase 3: Tool Definition & Integration (High Priority)

**Status:** COMPLETED  
**Duration:** 2-3 days

#### 3.1 Tool Definition Module (`tools/transcribe_audio.py`)

**Responsibilities:**
- Define transcribe_audio tool JSON schema
- Validate tool invocation inputs
- Execute transcription pipeline (audio_processor → transcriber)
- Format responses with metadata (transcription, confidence, duration)
- Handle errors with graceful degradation

**Key Classes:**

```python
@dataclass
class ToolInput:
    """Validated input for transcribe_audio tool."""
    audio_data: bytes          # Decoded audio bytes
    language_code: str         # BCP-47 language code (e.g., "en-US")
    original_format: Optional[str]  # Format hint ("ogg", "mp3", etc.)
    user_id: Optional[str]     # Tracking identifier
    message_id: Optional[str]  # Message tracking

@dataclass
class ToolResponse:
    """Response from transcribe_audio tool."""
    success: bool
    transcription: Optional[str]  # Transcribed text
    confidence: Optional[float]   # 0.0 to 1.0
    language_code: str
    duration_seconds: float
    word_count: int
    processing_time_ms: float
    error: Optional[str]         # Error message if failed

class TranscribeAudioTool:
    """Main tool class for transcribe_audio."""
    def __init__(self, config, logger)
    def get_schema() -> dict  # Static method returns JSON schema
    def validate_input(arguments: dict) -> ToolInput
    def execute(input: ToolInput) -> ToolResponse
    def format_response(response: ToolResponse) -> dict
```

**Key Functions:**
- `get_tool_schema()` - Return JSON schema for MCP tool registration
- `validate_input(arguments)` - Validate and parse tool invocation arguments
- `execute(input)` - Execute transcription pipeline
- `format_response(response)` - Format response for MCP protocol
- `format_error_response(error)` - Format error for MCP protocol

**Exception Classes:**
- `ToolInputError` - Invalid tool input parameters
- `ToolExecutionError` - Error during tool execution

**Tool Schema Definition:**
```json
{
    "name": "transcribe_audio",
    "description": "Transcribe audio/voice messages to text using Google Cloud Speech-to-Text",
    "inputSchema": {
        "type": "object",
        "properties": {
            "audio_data": {
                "type": "string",
                "description": "Base64-encoded audio file (OGG, MP3, WAV, or FLAC)"
            },
            "metadata": {
                "type": "object",
                "properties": {
                    "original_format": {"type": "string", "enum": ["ogg", "mp3", "wav", "flac"]},
                    "language_code": {"type": "string"},
                    "user_id": {"type": "string"},
                    "message_id": {"type": "string"}
                }
            }
        },
        "required": ["audio_data"]
    }
}
```

**Response Schema:**
```json
{
    "success": true,
    "transcription": "What's the weather today?",
    "confidence": 0.95,
    "language_code": "en-US",
    "duration_seconds": 2.5,
    "word_count": 4,
    "processing_time_ms": 1250.5,
    "metadata": {
        "invocation_id": "inv_abc123",
        "original_format": "ogg"
    }
}
```

#### 3.2 MCP Server Integration Updates (`src/mcp_server.py`)

**New Responsibilities:**
- Wire transcribe_audio tool to TranscribeAudioTool class
- Integrate Transcriber module for actual transcription
- Return real transcription results (replacing Phase 2 placeholder)

**Updated Handler Flow:**
```python
async def _handle_transcribe_audio(arguments, invocation_id):
    # 1. Validate input using tool module
    tool_input = TranscribeAudioTool.validate_input(arguments)
    
    # 2. Process audio (audio_processor)
    processed = audio_processor.process_audio(tool_input.audio_data)
    
    # 3. Transcribe (transcriber)
    result = transcriber.transcribe_with_retry(
        processed.flac_data, 
        language_code=tool_input.language_code
    )
    
    # 4. Format response
    return TranscribeAudioTool.format_response(result, processed.metadata)
```

**Error Handling Strategy:**
- `AudioValidationError` → Tool returns user-friendly error
- `AudioDurationError` → Tool returns duration exceeded error
- `TranscriptionError` → Tool returns transcription failed error
- `NoSpeechDetectedError` → Tool returns "no speech detected" result (not error)

#### 3.3 Configuration Integration

**Uses existing config values:**
- `config.audio.default_language` - Default language for transcription
- `config.audio.max_duration` - Maximum audio duration
- `config.audio.max_size` - Maximum file size
- `config.performance.transcription_timeout` - API timeout
- `config.performance.max_retry_attempts` - Retry count

**Logging Integration:**
- Uses MCPLogger for all logging
- Logs metadata: invocation_id, duration, confidence, processing_time
- NEVER logs audio content or transcription text (privacy)

#### 3.4 Tasks Completed

1. **Tool Definition** (`tools/transcribe_audio.py`)
   - [x] Define ToolInput and ToolResponse dataclasses
   - [x] Implement TranscribeAudioTool class
   - [x] Create JSON schema for MCP registration
   - [x] Implement input validation with proper error handling
   - [x] Implement execute() with audio_processor → transcriber flow
   - [x] Implement response formatting (success and error cases)
   - [x] Handle NoSpeechDetectedError as valid result (not error)

2. **MCP Server Integration** (`src/mcp_server.py`)
   - [x] Import and integrate TranscribeAudioTool
   - [x] Update _handle_transcribe_audio to call transcriber
   - [x] Return actual transcription results
   - [x] Handle transcription errors gracefully

3. **Test Suite** (`tests/test_tools.py`)
   - [x] Unit tests for ToolInput validation
   - [x] Unit tests for ToolResponse formatting
   - [x] Unit tests for TranscribeAudioTool class
   - [x] Integration tests with mocked transcriber
   - [x] Error scenario tests
   - [x] Test no speech detected handling

### Phase 4: MCP Server Implementation & Testing

**Status:** IN PROGRESS  
**Duration:** 3-4 days

#### 4.1 MCP Protocol Implementation

**Tasks:**
1. **Implement MCP Protocol**
   - [x] Tool discovery endpoint (`@server.list_tools()` decorator)
   - [x] Tool invocation handling (`@server.call_tool()` decorator)
   - [x] Error response formatting (comprehensive exception → TextContent mapping)
   - [x] Connection management (stdio transport via `stdio_server()`)
   - [ ] TCP transport support (optional, spec mentions both STDIO and TCP)

2. **Server Lifecycle Management**
   - [x] Server start/stop (`start()` and `stop()` methods)
   - [x] Graceful shutdown (cleanup in finally block)
   - [x] Signal handling (SIGINT and SIGTERM handlers)
   - [x] State tracking (`ServerState` dataclass with metrics)
   - [x] Resource cleanup (audio processor temp files)

#### 4.2 Testing Requirements

**Tasks:**
1. **Unit Tests** (80% coverage with pytest)
   - [x] MCP Server tests (`test_mcp_server.py` - 45+ tests)
   - [x] Tool tests (`test_tools.py` - 50+ tests)
   - [x] Audio processor tests (`test_audio_processor.py`)
   - [x] Transcriber tests (`test_transcriber.py`)
   - [x] Config tests (`test_config.py`)
   - [x] Logger tests (`test_logger.py`)

2. **Integration Tests**
   - [ ] End-to-end MCP tool invocation flow (`test_integration.py`)
   - [ ] Full pipeline tests (audio → process → transcribe → response)
   - [ ] Error propagation through full pipeline
   - [ ] Concurrent tool invocations simulation

3. **Format & Edge Case Tests**
   - [x] Mock Google Cloud STT
   - [x] Basic audio format tests (OGG, MP3, WAV, FLAC headers)
   - [ ] Additional format edge cases (corrupted headers, minimal valid files)
   - [x] Duration/size boundary tests

#### 4.3 Security Testing

**Tasks:**
1. **Input Validation Security**
   - [x] Basic input validation (missing params, invalid types)
   - [x] Invalid base64 handling
   - [ ] Malicious input tests (SQL injection patterns, XSS patterns)
   - [ ] Oversized input handling
   - [ ] Special character handling in metadata

2. **Privacy Compliance**
   - [x] No audio content in logs (privacy tests exist)
   - [x] No transcription in logs (verified in tests)
   - [x] Ephemeral processing (cleanup tests)

3. **Rate Limiting** (Optional)
   - [ ] Not implemented - considered optional for v1.0

### Phase 5: Documentation & Deployment

**Duration:** 2-3 days

**Tasks:**
1. **Documentation** (`README.md`, `docs/`)
   - MCP server setup instructions
   - Configuration guide
   - Tool usage examples
   - Agent integration examples
   - API reference

2. **Setup Documentation** (`docs/setup.md`)
   - Google Cloud project creation
   - Service account setup
   - Environment configuration
   - MCP client configuration

3. **Deployment Configuration**
   - Docker setup (optional)
   - Process manager configuration
   - Monitoring setup
   - Log aggregation

## 5. MCP-Specific Considerations (NEW SECTION)

### 5.1 MCP Protocol Compliance

**Standards:**
- Follow Model Context Protocol specification
- Use official MCP SDK for Python
- Support both STDIO and TCP transports
- Implement tool discovery mechanism
- Follow JSON-RPC 2.0 for messages

**Tool Registration:**
```json
{
  "tools": [
    {
      "name": "transcribe_audio",
      "description": "Transcribe audio/voice to text using Google Cloud STT",
      "input_schema": {
        "type": "object",
        "properties": {
          "audio_data": {"type": "string", "format": "base64"},
          "metadata": {"type": "object"}
        },
        "required": ["audio_data"]
      }
    }
  ]
}
```

### 5.2 Tool Invocation Flow

**From Agent Perspective:**
```python
# Agent invokes the tool
tool_response = await mcp_client.call_tool(
    "transcribe_audio",
    {
        "audio_data": base64_audio,
        "metadata": {"format": "ogg", "duration": 3.2}
    }
)

# Agent receives and processes response
transcription = tool_response["transcription"]
confidence = tool_response["confidence"]
# ... process transcription as input ...
```

### 5.3 Security & Access Control

**Authentication:**
- MCP server may require authentication token
- Agent must provide valid credentials
- Rate limiting per connection
- Audit logging for tracking usage

**Input Validation:**
- Validate all audio data before processing
- Sanitize metadata to prevent injection
- Check file size limits
- Reject unsupported formats

### 5.4 Performance & Resource Management

**Optimization:**
- Reuse Google Cloud STT client connections
- Keep audio files in memory (no disk I/O when possible)
- Parallel processing for multiple concurrent tool calls
- Connection pooling

**Resource Limits:**
- Maximum concurrent tool invocations: 10
- Audio size limit: 10MB per invocation
- Timeout per invocation: 30 seconds
- Memory limit: 512MB per audio file

## 6. File Structure (Updated for MCP Server)

```
claw-auto-transcriber/
├── .env.template                          # Environment variables template
├── .gitignore                            # Git ignore patterns
├── requirements.txt                      # Python dependencies (including mcp SDK)
├── pyproject.toml                        # Project configuration and build settings
├── README.md                             # Project overview (MCP server)
├── PROJECT_SPEC.md                       # This specification (v3.1)
├── TASK_TRACKER.md                       # Implementation task tracker
├── src/                                  # **Source code directory**
│   ├── __init__.py                       # Package initialization
│   ├── mcp_server.py                     # MCP server implementation
│   ├── audio_processor.py                # Audio handling
│   ├── transcriber.py                    # Google STT integration (Phase 2)
│   ├── config.py                         # Configuration management
│   └── logger.py                         # Logging utilities
├── tools/
│   ├── __init__.py
│   └── transcribe_audio.py               # Tool definition (Phase 3)
├── tests/
│   ├── __init__.py
│   ├── conftest.py                       # Pytest configuration and fixtures
│   ├── test_mcp_server.py                # MCP server tests
│   ├── test_audio_processor.py           # Audio processor tests
│   ├── test_config.py                    # Configuration tests
│   ├── test_logger.py                    # Logger tests
│   └── fixtures/                         # Test audio files (sample OGGs)
│       └── .gitkeep
└── docs/
    ├── setup.md                          # Setup instructions
    ├── mcp_usage.md                      # MCP usage guide
    └── tool_reference.md                 # Tool API reference
```

**Note:** All Python source modules are located in the `src/` directory. Imports should use the `src.` prefix (e.g., `from src.config import Config`).

## 7. Testing Strategy (80% Coverage with pytest)

### 7.1 Unit Tests (Individual Components)
- **MCP Server:** Tool registration, request handling, response formatting
- **Tool Definition:** Schema validation, input/output formatting
- **Audio Processor:** OGG validation, FLAC conversion, cleanup
- **Google STT Integration:** API calls, response parsing, error handling
- **Configuration:** .env loading, validation
- **Logging:** Log structure, metadata inclusion

### 7.2 Integration Tests (Component Interactions)
- MCP tool invocation → Audio processing → STT → Response flow
- Concurrent tool calls (stress test)
- Error propagation through layers
- Audio validation before STT

### 7.3 End-to-End Tests (MCP Protocol)
- Full MCP tool invocation cycle
- JSON-RPC message format compliance
- Tool discovery functionality
- Error response format

## 8. Security & Best Practices

### 8.1 Credential Management
- **NEVER commit** `.env` file or service account keys
- Use environment variables for all secrets
- No audio/transcription logging in production
- Rotate credentials regularly

### 8.2 MCP Server Security
- Require authentication tokens
- Implement rate limiting (60 calls/minute per client)
- Validate all inputs
- Sanitize metadata to prevent injection
- Log only metadata (no audio content)

### 8.3 Privacy & Data Protection
- **Ephemeral processing:** Audio deleted immediately after transcription
- **No storage:** Transcriptions not stored (only returned as tool response)
- **Opt-in logging:** Content logging only in debug mode
- **Secure transport:** Use TLS for MCP connections

## 9. Deployment & Operations

### 9.1 Running the MCP Server

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.template .env
# Edit .env with actual credentials

# Run server
python mcp_server.py
```

### 9.2 Client (Agent) Configuration

```python
# Agent connects to MCP server
from mcp import Client

client = Client("http://localhost:8765")
client.connect()

# List available tools
tools = client.list_tools()

# Invoke transcription tool
response = client.invoke_tool(
    "transcribe_audio",
    {
        "audio_data": base64_audio,
        "metadata": {"format": "ogg", "duration": 3.2}
    }
)

transcription = response["transcription"]
```

### 9.3 Docker Deployment (Optional)

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8765

CMD ["python", "mcp_server.py"]
```

## 10. Development Workflow

This section describes the standard workflow for making changes to the codebase.

### 10.1 New Development Request Process

When receiving a new development request, follow this workflow:

1. **Update Specification First**
   - Review and understand the request
   - Update this PROJECT_SPEC.md document following existing conventions
   - Document new components, data structures, or API changes
   - Update relevant sections (Components, Data Design, etc.)

2. **Create Implementation Plan**
   - Break down the change into discrete tasks
   - Update TASK_TRACKER.md with new tasks
   - Identify dependencies between tasks
   - Estimate complexity and order of implementation

3. **Implement Changes**
   - Follow the module design patterns established in Section 1
   - Maintain privacy requirements (no audio content logging)
   - Use existing configuration and logging infrastructure
   - Follow MCP protocol compliance guidelines

4. **Write Tests**
   - Write unit tests for new functionality (target 80% coverage)
   - Write integration tests for component interactions
   - Mock external dependencies (Google Cloud, etc.)
   - Follow existing test patterns in `tests/` directory

5. **Verify All Tests Pass**
   - Run the full test suite: `pytest tests/ -v`
   - Ensure no regressions in existing functionality
   - Verify coverage targets are met: `pytest --cov=src tests/`
   - Fix any failing tests before considering work complete

### 10.2 Code Quality Standards

- **Type Hints**: Use type hints for all function signatures
- **Docstrings**: Google-style docstrings for all public functions
- **Error Handling**: Use custom exception classes from respective modules
- **Logging**: Use MCPLogger for all logging (never log sensitive data)
- **Testing**: Minimum 80% code coverage for new code

### 10.3 Commit Guidelines

- Make atomic commits with clear messages
- Reference task IDs when applicable
- Ensure tests pass before committing

## 11. Future Enhancements

**Out of Scope:**
- Support for longer audio (>60 seconds)
- Batch transcription (multiple audio files)
- Real-time streaming transcription
- Speaker diarization
- Multi-language support in single audio
- Audio enhancement/cleanup preprocessing

---

**Last Updated:** 2026-02-02  
**Version:** 3.3 (MCP SERVER)  
**Status:** Phase 4 In Progress  
**Review:** MCP Server core implementation complete, integration and security tests needed