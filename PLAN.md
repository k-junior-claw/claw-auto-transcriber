# Phase 2: Google STT Integration - Implementation Plan

## Overview

This document outlines the implementation plan for the Google Cloud Speech-to-Text integration (Phase 2) of the Claw Auto-Transcriber MCP Server.

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
