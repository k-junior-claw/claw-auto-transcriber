# MCP Client Configuration Guide

This guide explains how to configure various MCP clients to use the Claw Auto-Transcriber server.

## What is MCP?

The Model Context Protocol (MCP) is a standard for connecting AI models to external tools and data sources. Claw Auto-Transcriber implements an MCP server that exposes a `transcribe_audio` tool.

### How It Works

1. MCP client (e.g., Claude Desktop) connects to the server
2. Server advertises available tools (`transcribe_audio`)
3. When the AI needs to transcribe audio, it invokes the tool
4. Server processes the audio and returns the transcription
5. AI continues the conversation with the transcribed text

## Claude Desktop Configuration

### Location of Config File

**macOS:**
```
~/Library/Application Support/Claude/claude_desktop_config.json
```

**Windows:**
```
%APPDATA%\Claude\claude_desktop_config.json
```

**Linux:**
```
~/.config/Claude/claude_desktop_config.json
```

### Basic Configuration

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "claw-transcriber": {
      "command": "python",
      "args": ["-m", "src.mcp_server"],
      "cwd": "/path/to/claw-auto-transcriber",
      "env": {
        "GOOGLE_CLOUD_PROJECT_ID": "your-project-id",
        "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account.json"
      }
    }
  }
}
```

### Using Virtual Environment

If you installed in a virtual environment:

```json
{
  "mcpServers": {
    "claw-transcriber": {
      "command": "/path/to/claw-auto-transcriber/venv/bin/python",
      "args": ["-m", "src.mcp_server"],
      "cwd": "/path/to/claw-auto-transcriber",
      "env": {
        "GOOGLE_CLOUD_PROJECT_ID": "your-project-id",
        "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account.json"
      }
    }
  }
}
```

### Full Configuration Example

```json
{
  "mcpServers": {
    "claw-transcriber": {
      "command": "/home/user/projects/claw-auto-transcriber/venv/bin/python",
      "args": ["-m", "src.mcp_server"],
      "cwd": "/home/user/projects/claw-auto-transcriber",
      "env": {
        "GOOGLE_CLOUD_PROJECT_ID": "my-transcriber-project",
        "GOOGLE_APPLICATION_CREDENTIALS": "/home/user/.config/gcloud/claw-transcriber-sa.json",
        "MAX_AUDIO_DURATION": "60",
        "DEFAULT_LANGUAGE_CODE": "en-US",
        "LOG_LEVEL": "INFO"
      }
    }
  }
}
```

## Docker-Based Configuration

If running the server in Docker:

```json
{
  "mcpServers": {
    "claw-transcriber": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "GOOGLE_CLOUD_PROJECT_ID=your-project-id",
        "-v", "/path/to/credentials.json:/app/credentials/sa.json:ro",
        "-e", "GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/sa.json",
        "claw-transcriber:latest"
      ]
    }
  }
}
```

## Custom MCP Client Integration

For building your own MCP client:

### Python Example

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    # Server parameters
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "src.mcp_server"],
        cwd="/path/to/claw-auto-transcriber",
        env={
            "GOOGLE_CLOUD_PROJECT_ID": "your-project-id",
            "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/credentials.json"
        }
    )
    
    # Connect to server
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize
            await session.initialize()
            
            # List available tools
            tools = await session.list_tools()
            print(f"Available tools: {[t.name for t in tools.tools]}")
            
            # Call transcribe_audio tool
            result = await session.call_tool(
                "transcribe_audio",
                {
                    "audio_data": "<base64-encoded-audio>",
                    "metadata": {
                        "language_code": "en-US"
                    }
                }
            )
            
            print(f"Result: {result}")

asyncio.run(main())
```

### JavaScript/TypeScript Example

```typescript
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

async function main() {
  const transport = new StdioClientTransport({
    command: "python",
    args: ["-m", "src.mcp_server"],
    cwd: "/path/to/claw-auto-transcriber",
    env: {
      GOOGLE_CLOUD_PROJECT_ID: "your-project-id",
      GOOGLE_APPLICATION_CREDENTIALS: "/path/to/credentials.json"
    }
  });

  const client = new Client({
    name: "my-client",
    version: "1.0.0"
  }, {
    capabilities: {}
  });

  await client.connect(transport);

  // List tools
  const tools = await client.listTools();
  console.log("Tools:", tools.tools.map(t => t.name));

  // Call transcribe_audio
  const result = await client.callTool({
    name: "transcribe_audio",
    arguments: {
      audio_data: "<base64-encoded-audio>",
      metadata: {
        language_code: "en-US"
      }
    }
  });

  console.log("Result:", result);
}

main();
```

## Connection Options

### STDIO Transport (Default)

The server uses STDIO (standard input/output) for communication. This is the default and recommended mode.

- **Pros**: Simple, secure, no network exposure
- **Cons**: Requires starting server as subprocess

### Environment Variables in Client

You can pass all configuration via the client's environment:

| Variable | Purpose |
|----------|---------|
| `GOOGLE_CLOUD_PROJECT_ID` | Google Cloud project |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to credentials |
| `MAX_AUDIO_DURATION` | Max audio length (seconds) |
| `DEFAULT_LANGUAGE_CODE` | Default transcription language |
| `LOG_LEVEL` | Logging verbosity |

## Verifying Connection

After configuring your client:

1. **Start the client** (e.g., restart Claude Desktop)
2. **Check for tool availability** - The `transcribe_audio` tool should appear
3. **Test with a simple request** - Try transcribing a short audio clip

### Debug Mode

For troubleshooting, enable debug logging:

```json
{
  "mcpServers": {
    "claw-transcriber": {
      "command": "python",
      "args": ["-m", "src.mcp_server"],
      "cwd": "/path/to/claw-auto-transcriber",
      "env": {
        "LOG_LEVEL": "DEBUG",
        "LOG_FORMAT": "text"
      }
    }
  }
}
```

## Troubleshooting

### Server Not Starting

**Check**: Server process can be started manually:
```bash
cd /path/to/claw-auto-transcriber
source venv/bin/activate
python -m src.mcp_server
```

### Tool Not Appearing

**Check**: Configuration file is valid JSON:
```bash
python -m json.tool < ~/.config/Claude/claude_desktop_config.json
```

### Permission Errors

**Check**: Credentials file is accessible:
```bash
ls -la /path/to/service-account.json
```

### Connection Timeout

**Check**: Server starts within reasonable time:
- Check Google Cloud credentials are valid
- Verify Python dependencies are installed correctly

## Next Steps

- [Usage Examples](usage-examples.md) - Learn how to use the tool
- [Setup Guide](setup.md) - Complete installation instructions
- [README](../README.md) - Full API reference
