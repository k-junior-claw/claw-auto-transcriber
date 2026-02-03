# Setup Guide

This guide walks you through setting up the Claw Auto-Transcriber MCP server from scratch.

## Prerequisites

Before you begin, ensure you have:

- **Python 3.10+**: Verify with `python3 --version`
- **pip**: Python package manager
- **Google Cloud Account**: With billing enabled

### Optional: Installing FFmpeg

FFmpeg is **optional** and only needed as a fallback for certain audio formats. The primary audio processing uses the `soundfile` library which is installed automatically with the Python dependencies.

If you encounter audio conversion issues, you can install FFmpeg:

**Ubuntu/Debian:**
```bash
sudo apt install ffmpeg
```

**macOS (Homebrew):**
```bash
brew install ffmpeg
```

**Windows:**
Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH.

## 1. Google Cloud Setup

### 1.1 Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **Select a project** → **New Project**
3. Enter a project name (e.g., `claw-transcriber`)
4. Click **Create**
5. Note your **Project ID** (you'll need this later)

### 1.2 Enable the Speech-to-Text API

1. In Google Cloud Console, go to **APIs & Services** → **Library**
2. Search for "Cloud Speech-to-Text API"
3. Click on it and click **Enable**
4. Wait for the API to be enabled

### 1.3 Create a Service Account

1. Go to **IAM & Admin** → **Service Accounts**
2. Click **Create Service Account**
3. Enter details:
   - **Name**: `claw-transcriber-sa`
   - **ID**: auto-generated
   - **Description**: "Service account for Claw Auto-Transcriber"
4. Click **Create and Continue**

### 1.4 Grant Permissions

1. In the "Grant this service account access" step
2. Click **Select a role**
3. Search for and add: **Cloud Speech-to-Text API User**
4. Click **Continue** → **Done**

### 1.5 Create and Download Credentials

1. Click on the service account you just created
2. Go to **Keys** tab
3. Click **Add Key** → **Create new key**
4. Select **JSON** format
5. Click **Create**
6. Save the downloaded file securely (e.g., `~/.config/gcloud/claw-transcriber-sa.json`)

> ⚠️ **Security Warning**: Never commit this file to version control!

## 2. Project Installation

### 2.1 Clone the Repository

```bash
git clone https://github.com/k-junior-claw/claw-auto-transcriber.git
cd claw-auto-transcriber
```

### 2.2 Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
```

On Windows:
```cmd
python -m venv venv
venv\Scripts\activate
```

### 2.3 Install Dependencies

```bash
pip install -r requirements.txt
```

### 2.4 Install Development Dependencies (Optional)

```bash
pip install -e ".[dev]"
```

## 3. Environment Configuration

### 3.1 Create Environment File

```bash
cp .env.template .env
```

### 3.2 Configure Required Variables

Edit `.env` with your values:

```bash
# Required: Your Google Cloud Project ID
GOOGLE_CLOUD_PROJECT_ID=your-project-id

# Required: Path to your service account credentials
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

### 3.3 Configure Optional Variables

Adjust these as needed:

```bash
# Maximum audio duration (default: 60 seconds)
MAX_AUDIO_DURATION=60

# Default language for transcription
DEFAULT_LANGUAGE_CODE=en-US

# Logging level (DEBUG for troubleshooting)
LOG_LEVEL=INFO
```

## 4. Verify Installation

### 4.1 Test Configuration

```bash
# Activate virtual environment
source venv/bin/activate

# Run the config test
python -c "from src.config import init_config; c = init_config(); print(f'Project: {c.google_cloud.project_id}')"
```

You should see your project ID printed.

### 4.2 Run Tests

```bash
# Run the test suite
python -m pytest tests/ -v

# All 262 tests should pass
```

### 4.3 Start the Server

```bash
python -m src.mcp_server
```

The server is now running and waiting for MCP connections via stdio.

## 5. Directory Structure

After setup, your credentials should be organized:

```
~/.config/gcloud/
└── claw-transcriber-sa.json   # Service account credentials

~/projects/claw-auto-transcriber/
├── .env                        # Your configuration (not in git)
├── .env.template               # Template (in git)
├── venv/                       # Virtual environment (not in git)
└── ...                         # Project files
```

## 6. Security Best Practices

### Credentials Storage

- Store credentials outside the project directory
- Use environment variables for sensitive values
- Never commit `.env` or credential files

### File Permissions

```bash
# Restrict credentials file access
chmod 600 ~/.config/gcloud/claw-transcriber-sa.json
```

### Environment Isolation

- Use virtual environments for each project
- Pin dependency versions in `requirements.txt`

## 7. Troubleshooting

### "Could not automatically determine credentials"

**Cause**: `GOOGLE_APPLICATION_CREDENTIALS` not set or invalid path.

**Solution**:
```bash
# Verify the path exists
ls -la $GOOGLE_APPLICATION_CREDENTIALS

# Ensure it's set in .env
echo $GOOGLE_APPLICATION_CREDENTIALS
```

### "Permission denied" on credentials file

**Cause**: File permissions too restrictive or wrong ownership.

**Solution**:
```bash
chmod 644 /path/to/credentials.json
# Or if running as different user:
sudo chown $USER:$USER /path/to/credentials.json
```

### "Speech-to-Text API has not been enabled"

**Cause**: API not enabled in Google Cloud project.

**Solution**:
1. Go to Google Cloud Console
2. Navigate to APIs & Services → Library
3. Search for "Cloud Speech-to-Text API"
4. Click Enable

### Audio conversion errors (optional FFmpeg fallback)

**Cause**: Some audio formats may fail to convert with the default soundfile library.

**Solution**: Install FFmpeg as an optional fallback:
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# Verify installation
ffmpeg -version
```

Note: FFmpeg is optional. Most audio files work without it.

## Next Steps

- [Configure MCP Clients](mcp-client-config.md) - Connect Claude Desktop or other clients
- [Usage Examples](usage-examples.md) - Learn how to use the transcription tool
- [README](../README.md) - Full API reference
