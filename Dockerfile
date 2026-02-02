# Claw Auto-Transcriber MCP Server
# Multi-stage build for minimal production image

# =============================================================================
# Stage 1: Builder
# =============================================================================
FROM python:3.12-slim as builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# =============================================================================
# Stage 2: Runtime
# =============================================================================
FROM python:3.12-slim as runtime

# Labels
LABEL org.opencontainers.image.title="Claw Auto-Transcriber" \
      org.opencontainers.image.description="MCP Server for audio transcription using Google Cloud Speech-to-Text" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.source="https://github.com/k-junior-claw/claw-auto-transcriber"

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    # Application defaults
    MCP_SERVER_NAME=claw-auto-transcriber \
    MAX_AUDIO_DURATION=60 \
    MAX_AUDIO_SIZE=10485760 \
    DEFAULT_LANGUAGE_CODE=en-US \
    LOG_LEVEL=INFO \
    LOG_FORMAT=json \
    TEMP_AUDIO_DIR=/tmp/claw_transcriber

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    # Clean up
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN groupadd --gid 1000 claw \
    && useradd --uid 1000 --gid claw --shell /bin/bash --create-home claw

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Set working directory
WORKDIR /app

# Copy application code
COPY --chown=claw:claw src/ ./src/
COPY --chown=claw:claw tools/ ./tools/

# Create directories
RUN mkdir -p /app/credentials /tmp/claw_transcriber \
    && chown -R claw:claw /app /tmp/claw_transcriber

# Switch to non-root user
USER claw

# Health check - verify the server can be imported
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from src.mcp_server import MCPTranscriptionServer; print('OK')" || exit 1

# Default command - run MCP server
# Server uses stdio, so it waits for input
CMD ["python", "-m", "src.mcp_server"]
