# Implementation Plans - Claw Auto-Transcriber MCP Server

---

# Phase 3: Tool Definition & Integration - Implementation Plan

## Overview

This document outlines the implementation plan for the Tool Definition & Integration phase (Phase 3) of the Claw Auto-Transcriber MCP Server. This phase wires together the audio_processor and transcriber modules into a complete tool invocation flow.

## 1. Implementation Steps

### Step 1: Create `tools/transcribe_audio.py`

1. **Define Exception Classes**
   - `ToolInputError` - Invalid input parameters
   - `ToolExecutionError` - Execution failures

2. **Define Data Classes**
   - `ToolInput` - Validated input container
   - `ToolResponse` - Response container with transcription and metadata

3. **Implement `TranscribeAudioTool` Class**
   - `get_schema()` - Return JSON schema for MCP registration (static)
   - `validate_input(arguments)` - Validate and decode input
   - `execute(input)` - Execute transcription pipeline
   - `format_response(result, metadata)` - Format success response
   - `format_error_response(error)` - Format error response

4. **Module-level Functions**
   - `get_tool_schema()` - Get schema without instantiation
   - `validate_tool_input(arguments)` - Convenience validator

### Step 2: Update `src/mcp_server.py`

1. **Add Transcriber Integration**
   - Import Transcriber and related classes
   - Add lazy initialization for transcriber
   - Wire transcriber to tool invocation handler

2. **Update `_handle_transcribe_audio` method**
   - Use TranscribeAudioTool for input validation
   - Call transcriber.transcribe_with_retry()
   - Return actual transcription results (replace placeholder)
   - Handle NoSpeechDetectedError as valid (empty) result

3. **Add Transcription Error Handling**
   - Handle TranscriptionError variants
   - Handle NoSpeechDetectedError specially

### Step 3: Create `tests/test_tools.py`

1. **Exception Tests**
   - Verify exception hierarchy
   - Test exception messages

2. **Data Class Tests**
   - `ToolInput` creation and validation
   - `ToolResponse` creation and to_dict()

3. **TranscribeAudioTool Tests (with mocks)**
   - Schema validation
   - Input validation (valid/invalid)
   - Execute with mocked audio_processor and transcriber
   - Response formatting (success and error)
   - No speech detected handling

4. **Integration Tests**
   - Full tool invocation flow (mocked)
   - Error propagation

### Step 4: Update Exports

1. Update `tools/__init__.py` with tool exports
2. Update `src/__init__.py` if needed

## 2. Dependencies

### Internal Dependencies
- `src.audio_processor` - Audio validation and conversion
- `src.transcriber` - Google Cloud STT integration
- `src.config` - Configuration management
- `src.logger` - Logging utilities

### No New External Dependencies
- Uses existing `google-cloud-speech` via transcriber module

## 3. Design Decisions

### Architecture
- **Separation of Concerns** - Tool module handles schema/validation/formatting, doesn't do actual processing
- **Delegation Pattern** - Tool delegates to AudioProcessor and Transcriber
- **Privacy First** - Never log audio content or transcription text

### Error Handling Strategy
- **Validation Errors** - Return user-friendly error in response
- **Processing Errors** - Return structured error with type
- **Transcription Errors** - Retry transient, fail graceful for permanent
- **No Speech Detected** - Return success with empty transcription (not an error)

### Response Design
- **Consistent Structure** - Same response shape for success and partial success
- **Rich Metadata** - Include confidence, duration, word_count, processing_time
- **Privacy Aware** - Never include raw audio in response

## 4. Files to Create/Modify

### Create
- `tools/transcribe_audio.py` - Tool definition module
- `tests/test_tools.py` - Comprehensive test suite

### Modify
- `tools/__init__.py` - Add tool exports
- `src/mcp_server.py` - Integrate transcriber, wire tool
- `src/__init__.py` - Add tool-related exports (if needed)
- `tests/conftest.py` - Add tool-related fixtures (if needed)
- `PROJECT_SPEC.md` - Update Phase 3 completion status (DONE)

## 5. Test Strategy

### Unit Tests (Mocked Dependencies)
- All tests mock AudioProcessor and Transcriber
- Test all code paths and error scenarios
- Cover edge cases (empty audio, no speech, etc.)

### Test Categories
1. **Schema Tests**
   - Verify JSON schema structure
   - Verify required fields

2. **Validation Tests**
   - Valid input parsing
   - Missing required fields
   - Invalid base64
   - Invalid format hints

3. **Execution Tests**
   - Successful transcription
   - Audio processing errors
   - Transcription errors
   - No speech detected

4. **Response Formatting Tests**
   - Success response structure
   - Error response structure
   - Metadata inclusion

### Test Coverage Target
- Minimum 80% code coverage
- All public methods tested
- All exception paths tested

## 6. Implementation Order

1. [ ] Update PROJECT_SPEC.md with Phase 3 details
2. [ ] Create this PLAN.md
3. [ ] Implement `tools/transcribe_audio.py`
4. [ ] Update `src/mcp_server.py` with transcriber integration
5. [ ] Update `tools/__init__.py` with exports
6. [ ] Implement `tests/test_tools.py`
7. [ ] Run full test suite (`pytest tests/ -v`)
8. [ ] Verify all tests pass (existing + new)

---

---

# Phase 4: MCP Server Implementation & Testing - Implementation Plan

## Overview

This document outlines the implementation plan for Phase 4 of the Claw Auto-Transcriber MCP Server. This phase focuses on completing integration tests, adding security tests, and ensuring comprehensive test coverage.

## 1. Current State Analysis

### Already Implemented (from Phase 1-3)

#### MCP Protocol
- ✅ Tool discovery (`@server.list_tools()` decorator)
- ✅ Tool invocation handling (`@server.call_tool()` decorator)
- ✅ Error response formatting (exception → TextContent mapping)
- ✅ Connection management (stdio transport)

#### Server Lifecycle
- ✅ Server start/stop methods
- ✅ Graceful shutdown with cleanup
- ✅ Signal handling (SIGINT, SIGTERM)
- ✅ State tracking (ServerState dataclass)

#### Unit Tests
- ✅ 231 existing tests across all modules
- ✅ Comprehensive mocking of external dependencies

### Missing (Phase 4 Tasks)

1. **Integration Tests** - End-to-end MCP flow tests
2. **Security Tests** - Malicious input, edge cases
3. **Additional Format Tests** - Edge case audio formats

## 2. Implementation Steps

### Step 1: Create `tests/test_integration.py`

1. **End-to-End MCP Flow Tests**
   - Full tool invocation cycle (arguments → validate → process → transcribe → response)
   - Test with realistic base64-encoded audio data
   - Verify response structure matches MCP protocol expectations

2. **Pipeline Integration Tests**
   - Audio processing → transcription → formatting flow
   - Error propagation through full pipeline
   - Resource cleanup verification after invocation

3. **Concurrent Invocation Tests**
   - Multiple simultaneous tool calls
   - State tracking accuracy under load
   - No resource leaks between invocations

4. **Server Lifecycle Integration**
   - Start → handle requests → stop flow
   - Graceful shutdown during active processing
   - State persistence across invocations

### Step 2: Add Security Tests

1. **Input Validation Security** (in `test_integration.py` or `test_mcp_server.py`)
   - Malicious patterns in metadata (SQL injection, XSS)
   - Extremely large base64 strings
   - Special characters and Unicode in user_id/message_id
   - Null bytes and control characters

2. **Boundary Condition Tests**
   - Audio at exact max duration limit
   - Audio at exact max size limit
   - Empty audio after base64 decode
   - Minimum valid audio (shortest possible)

### Step 3: Verify All Tests Pass

1. Run full test suite: `pytest tests/ -v`
2. Verify 80%+ coverage: `pytest --cov=src tests/`
3. Fix any regressions

## 3. Files to Create/Modify

### Create
- `tests/test_integration.py` - Integration and end-to-end tests

### Modify
- `tests/test_mcp_server.py` - Add security-focused tests (if needed)
- `PROJECT_SPEC.md` - Update Phase 4 completion status (DONE when complete)

## 4. Test Categories

### Integration Tests (test_integration.py)
1. `TestMCPToolFlow` - Full tool invocation cycle
2. `TestPipelineIntegration` - Audio → transcription flow
3. `TestConcurrentInvocations` - Parallel request handling
4. `TestServerLifecycleIntegration` - Start/stop with requests

### Security Tests
1. `TestInputSanitization` - Malicious input handling
2. `TestBoundaryConditions` - Edge case values
3. `TestResourceLimits` - Size/duration limits enforcement

## 5. Design Decisions

### Integration Test Approach
- **Mocked External Services** - Google Cloud STT always mocked
- **Real Internal Flow** - Actual AudioProcessor and Transcriber classes
- **Realistic Test Data** - Base64-encoded data similar to production

### Security Test Approach
- **Defense in Depth** - Test validation at multiple layers
- **No Secrets in Tests** - Use dummy/placeholder values
- **Privacy Preserved** - Never log actual test audio

## 6. Implementation Order

1. [ ] Create `tests/test_integration.py` with MCP flow tests
2. [ ] Add security-focused tests
3. [ ] Run full test suite
4. [ ] Verify 80%+ coverage
5. [ ] Update PROJECT_SPEC.md status

---

# Phase 2: Google STT Integration - Implementation Plan (COMPLETED)

## Overview

This section documents the completed implementation plan for the Google Cloud Speech-to-Text integration (Phase 2) of the Claw Auto-Transcriber MCP Server.

## 1. Implementation Steps

### Step 1: Create `src/transcriber.py`

1. **Define Exception Classes**
   - `TranscriptionError` - Base exception
   - `TranscriptionAPIError` - API-level errors
   - `TranscriptionTimeoutError` - Request timeouts
   - `TranscriptionQuotaError` - Quota exceeded
   - `NoSpeechDetectedError` - No speech in audio

2. **Define Data Classes**
   - `WordInfo` - Word-level timing information
   - `TranscriptionResult` - Container for transcription results

3. **Implement `Transcriber` Class**
   - Constructor with config and logger injection
   - Lazy initialization of Google Cloud client
   - `transcribe()` - Main transcription method
   - `transcribe_with_retry()` - Retry wrapper
   - `_parse_response()` - Response parsing
   - `_handle_api_error()` - Error mapping
   - `_is_retryable_error()` - Retry decision logic

4. **Module-level Convenience Functions**
   - `get_transcriber()` - Singleton access
   - `transcribe()` - Direct transcription function

### Step 2: Create `tests/test_transcriber.py`

1. **Exception Tests**
   - Verify exception hierarchy
   - Test exception messages

2. **Data Class Tests**
   - `WordInfo` creation and to_dict()
   - `TranscriptionResult` creation and to_dict()

3. **Transcriber Tests (with mocked Google client)**
   - Client initialization
   - Successful transcription
   - Empty/no speech handling
   - Error handling (API, timeout, quota)
   - Retry logic (success after retry, max retries)
   - Response parsing (single/multiple results)

4. **Module Function Tests**
   - `get_transcriber()` singleton behavior
   - `transcribe()` convenience function

### Step 3: Update Exports

1. Update `src/__init__.py` with transcriber exports
2. Update `tests/conftest.py` with transcriber fixtures

## 2. Dependencies

### Required (already in requirements.txt)
- `google-cloud-speech>=2.21.0` - Google Cloud Speech-to-Text client

### Google Cloud Setup Requirements
- Google Cloud project with Speech-to-Text API enabled
- Service account with `roles/speech.client` role
- Service account JSON key file
- `GOOGLE_APPLICATION_CREDENTIALS` environment variable

## 3. Design Decisions

### Class Structure
- **Single `Transcriber` class** - Encapsulates all Google Cloud STT logic
- **Lazy client initialization** - Client created on first use, not constructor
- **Dependency injection** - Config and logger passed to constructor
- **Singleton pattern** - Module-level `get_transcriber()` for convenience

### Error Handling Strategy
- **Custom exception hierarchy** - All errors inherit from `TranscriptionError`
- **Error mapping** - Google Cloud errors mapped to specific exceptions
- **Detailed error messages** - Include error codes but never sensitive data
- **Privacy preservation** - Never include audio content or transcription in errors

### Retry Logic
- **Exponential backoff** - Delay increases with each attempt
- **Configurable parameters** - Max attempts, base delay from config
- **Selective retry** - Only retry transient/retryable errors
- **Final error propagation** - Raise original error after max attempts

### Integration Patterns
- **Config integration** - Use existing `Config` class for all settings
- **Logger integration** - Use existing `MCPLogger` for all logging
- **Audio processor integration** - Expect FLAC audio at 16kHz (from AudioProcessor)

## 4. Files to Create/Modify

### Create
- `src/transcriber.py` - Main transcriber module
- `tests/test_transcriber.py` - Comprehensive test suite

### Modify
- `src/__init__.py` - Add transcriber exports
- `tests/conftest.py` - Add transcriber fixtures (reset singleton)
- `PROJECT_SPEC.md` - Update Phase 2 completion status (DONE)

## 5. Test Strategy

### Unit Tests (Mocked Google Client)
- All tests mock `google.cloud.speech.SpeechClient`
- No actual API calls during testing
- Cover all code paths and error scenarios

### Test Categories
1. **Happy Path Tests**
   - Successful transcription with good confidence
   - Multiple word results with timing
   - Different language codes

2. **Error Handling Tests**
   - API errors (invalid request, authentication)
   - Timeout errors
   - Quota exceeded errors
   - No speech detected

3. **Retry Logic Tests**
   - Successful retry after transient error
   - Max retries exceeded
   - Non-retryable errors not retried

4. **Edge Case Tests**
   - Empty response handling
   - Zero confidence results
   - Missing optional fields

### Test Coverage Target
- Minimum 80% code coverage
- All public methods tested
- All exception paths tested

## 6. Implementation Order

1. ✅ Update PROJECT_SPEC.md with Phase 2 details
2. ✅ Create this PLAN.md
3. ✅ Implement `src/transcriber.py`
4. ✅ Implement `tests/test_transcriber.py`
5. ✅ Update `src/__init__.py`
6. ✅ Update `tests/conftest.py`
7. ✅ Run full test suite (`pytest tests/ -v`)
8. ✅ Verify all tests pass (187 tests, up from 141)
