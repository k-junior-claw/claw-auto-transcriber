# Usage Examples

This guide provides practical examples of using the `transcribe_audio` tool.

## Basic Usage

### Simple Transcription

The most basic usage - transcribe a base64-encoded audio file:

```json
{
  "audio_data": "T2dnUwACAAAAAAAAAAC8dwEAAAAAAEkh..."
}
```

**Response:**
```json
{
  "success": true,
  "transcription": "Hello, how can I help you today?",
  "confidence": 0.94,
  "language_code": "en-US",
  "duration_seconds": 2.5,
  "word_count": 6,
  "processing_time_ms": 1250.5
}
```

### With Language Specification

Specify the language for better accuracy:

```json
{
  "audio_data": "T2dnUwACAAAAAAAAAAC8dwEAAAAAAEkh...",
  "metadata": {
    "language_code": "es-ES"
  }
}
```

### With Full Metadata

Include all available metadata for tracking:

```json
{
  "audio_data": "T2dnUwACAAAAAAAAAAC8dwEAAAAAAEkh...",
  "metadata": {
    "original_format": "ogg",
    "language_code": "en-US",
    "user_id": "user_12345",
    "message_id": "msg_67890"
  }
}
```

## Python Integration

### Reading Audio File

```python
import base64
from pathlib import Path

def encode_audio_file(file_path: str) -> str:
    """Read and base64-encode an audio file."""
    audio_bytes = Path(file_path).read_bytes()
    return base64.b64encode(audio_bytes).decode("utf-8")

# Example usage
audio_base64 = encode_audio_file("voice_message.ogg")
```

### Complete Example with MCP Client

```python
import asyncio
import base64
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def transcribe_file(audio_path: str) -> dict:
    """Transcribe an audio file using the MCP server."""
    
    # Encode audio
    audio_bytes = Path(audio_path).read_bytes()
    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
    
    # Server connection parameters
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "src.mcp_server"],
        cwd="/path/to/claw-auto-transcriber",
        env={
            "GOOGLE_CLOUD_PROJECT_ID": "your-project",
            "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/creds.json"
        }
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            result = await session.call_tool(
                "transcribe_audio",
                {
                    "audio_data": audio_base64,
                    "metadata": {
                        "language_code": "en-US"
                    }
                }
            )
            
            import json
            return json.loads(result.content[0].text)

# Run transcription
async def main():
    result = await transcribe_file("voice_message.ogg")
    
    if result["success"]:
        print(f"Transcription: {result['transcription']}")
        print(f"Confidence: {result['confidence']:.2%}")
    else:
        print(f"Error: {result['error']}")

asyncio.run(main())
```

### Processing Telegram Voice Messages

```python
import base64
import asyncio
from telegram import Update
from telegram.ext import Application, MessageHandler, filters

async def handle_voice(update: Update, context):
    """Handle incoming voice messages from Telegram."""
    voice = update.message.voice
    
    # Download the voice file
    file = await context.bot.get_file(voice.file_id)
    audio_bytes = await file.download_as_bytearray()
    
    # Encode for transcription
    audio_base64 = base64.b64encode(bytes(audio_bytes)).decode("utf-8")
    
    # Call transcription (assuming mcp_client is set up)
    result = await transcribe_with_mcp(
        audio_base64,
        metadata={
            "original_format": "ogg",
            "language_code": "en-US",
            "user_id": str(update.effective_user.id),
            "message_id": str(update.message.message_id)
        }
    )
    
    if result["success"]:
        # Process the transcribed text as if it were a text message
        await process_user_input(result["transcription"], update, context)
    else:
        await update.message.reply_text(
            "Sorry, I couldn't transcribe your voice message."
        )
```

## Error Handling

### Handling All Error Types

```python
async def transcribe_with_error_handling(audio_base64: str) -> str:
    """Transcribe audio with comprehensive error handling."""
    
    result = await call_transcribe_tool(audio_base64)
    
    if result["success"]:
        return result["transcription"]
    
    # Handle specific error types
    error_type = result.get("error_type", "unknown")
    
    if error_type == "duration_error":
        raise ValueError("Audio is too long. Maximum is 60 seconds.")
    
    elif error_type == "size_error":
        raise ValueError("Audio file is too large. Maximum is 10MB.")
    
    elif error_type == "format_error":
        raise ValueError("Unsupported audio format. Use OGG, MP3, WAV, or FLAC.")
    
    elif error_type == "validation_error":
        raise ValueError("Invalid or corrupted audio file.")
    
    elif error_type == "timeout_error":
        # Retry might help
        raise TimeoutError("Transcription timed out. Please try again.")
    
    elif error_type == "quota_error":
        # Wait and retry
        raise RuntimeError("Service quota exceeded. Please try again later.")
    
    elif error_type == "api_error":
        raise RuntimeError("Transcription service error. Please try again.")
    
    else:
        raise RuntimeError(f"Transcription failed: {result.get('error', 'Unknown error')}")
```

### Retry Logic

```python
import asyncio
from typing import Optional

async def transcribe_with_retry(
    audio_base64: str,
    max_retries: int = 3,
    retry_delay: float = 1.0
) -> dict:
    """Transcribe with automatic retry for transient errors."""
    
    retryable_errors = {"timeout_error", "api_error"}
    last_error = None
    
    for attempt in range(max_retries):
        result = await call_transcribe_tool(audio_base64)
        
        if result["success"]:
            return result
        
        error_type = result.get("error_type", "")
        
        if error_type not in retryable_errors:
            # Non-retryable error, fail immediately
            return result
        
        last_error = result
        
        if attempt < max_retries - 1:
            # Exponential backoff
            wait_time = retry_delay * (2 ** attempt)
            await asyncio.sleep(wait_time)
    
    return last_error
```

## Language Support

### Supported Languages

Google Cloud Speech-to-Text supports 125+ languages. Common language codes:

| Language | Code |
|----------|------|
| English (US) | `en-US` |
| English (UK) | `en-GB` |
| Spanish | `es-ES` |
| French | `fr-FR` |
| German | `de-DE` |
| Italian | `it-IT` |
| Portuguese | `pt-BR` |
| Japanese | `ja-JP` |
| Chinese (Mandarin) | `zh-CN` |
| Korean | `ko-KR` |
| Russian | `ru-RU` |
| Arabic | `ar-SA` |

### Multi-Language Support

```python
async def transcribe_multilingual(
    audio_base64: str,
    primary_language: str = "en-US",
    fallback_languages: list[str] = None
) -> dict:
    """Try transcription with multiple languages."""
    
    # First try primary language
    result = await call_transcribe_tool(audio_base64, language_code=primary_language)
    
    if result["success"] and result["confidence"] > 0.7:
        return result
    
    # Try fallback languages if confidence is low
    if fallback_languages:
        best_result = result
        
        for lang in fallback_languages:
            alt_result = await call_transcribe_tool(audio_base64, language_code=lang)
            
            if (alt_result["success"] and 
                alt_result.get("confidence", 0) > best_result.get("confidence", 0)):
                best_result = alt_result
        
        return best_result
    
    return result
```

## Audio Format Examples

### Converting Audio Formats

If you have audio in other formats, convert before sending:

```python
from pydub import AudioSegment
import base64
import io

def convert_to_ogg(audio_path: str) -> str:
    """Convert any audio file to OGG and return base64."""
    audio = AudioSegment.from_file(audio_path)
    
    # Export to OGG
    buffer = io.BytesIO()
    audio.export(buffer, format="ogg", codec="libopus")
    
    return base64.b64encode(buffer.getvalue()).decode("utf-8")
```

### Handling Large Files

For files approaching the size limit:

```python
def check_audio_size(audio_base64: str, max_mb: float = 10.0) -> bool:
    """Check if audio is within size limits."""
    # Base64 is ~4/3 the size of binary
    estimated_bytes = len(audio_base64) * 3 / 4
    estimated_mb = estimated_bytes / (1024 * 1024)
    return estimated_mb <= max_mb
```

## Batch Processing

### Processing Multiple Files

```python
import asyncio
from pathlib import Path

async def transcribe_batch(audio_files: list[str]) -> list[dict]:
    """Transcribe multiple audio files concurrently."""
    
    async def transcribe_one(file_path: str) -> dict:
        audio_base64 = encode_audio_file(file_path)
        result = await call_transcribe_tool(audio_base64)
        return {"file": file_path, **result}
    
    # Process in batches to avoid overwhelming the service
    batch_size = 5
    results = []
    
    for i in range(0, len(audio_files), batch_size):
        batch = audio_files[i:i + batch_size]
        batch_results = await asyncio.gather(
            *[transcribe_one(f) for f in batch]
        )
        results.extend(batch_results)
        
        # Small delay between batches
        if i + batch_size < len(audio_files):
            await asyncio.sleep(0.5)
    
    return results
```

## Testing

### Test with Sample Audio

```python
import base64

# Minimal valid OGG file header for testing
def create_test_ogg() -> str:
    """Create a minimal OGG header for testing."""
    # This is just a header - not real audio
    ogg_header = bytes([
        0x4F, 0x67, 0x67, 0x53,  # OggS
        0x00, 0x02, 0x00, 0x00,  # Flags
        0x00, 0x00, 0x00, 0x00,  # Granule position
        0x00, 0x00, 0x00, 0x00,
        0xBC, 0x77, 0x01, 0x00,  # Stream serial
        0x00, 0x00, 0x00, 0x00,  # Page sequence
        0x49, 0x21, 0xC2, 0xBD,  # CRC
        0x01, 0x1E,              # Segments
    ])
    return base64.b64encode(ogg_header).decode("utf-8")
```

## Next Steps

- [Setup Guide](setup.md) - Complete installation instructions
- [MCP Client Config](mcp-client-config.md) - Configure your MCP client
- [README](../README.md) - Full API reference
