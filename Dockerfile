# =============================================================================
# MiniCode Python — Multi-stage Dockerfile
# =============================================================================
# Inspired by Hermes Agent's flexible deployment model:
#   - Lightweight CLI container for local/CI use
#   - Gateway-ready base for multi-platform access (Telegram/Discord/Web)
#   - Headless mode for cron/scheduled tasks
#
# Quick start:
#   docker build -t minicode-py .
#   docker run -it --rm \
#     -e ANTHROPIC_API_KEY=sk-ant-... \
#     -v $(pwd):/workspace \
#     minicode-py
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder — install package into venv
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Copy package source
COPY pyproject.toml README.md ./
COPY minicode/ ./minicode/

# Install into a clean venv (keeps final image small)
RUN python -m venv /opt/minicode-venv && \
    /opt/minicode-venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/minicode-venv/bin/pip install --no-cache-dir .

# ---------------------------------------------------------------------------
# Stage 2: Runtime — minimal image with only the venv
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="MiniCode Python"
LABEL org.opencontainers.image.description="A lightweight terminal coding assistant — the agent that grows with you"
LABEL org.opencontainers.image.source="https://github.com/QUSETIONS/MiniCode-Python"

# Create non-root user for security
RUN groupadd --gid 1000 minicode && \
    useradd --uid 1000 --gid minicode --create-home --shell /bin/bash minicode

# Copy venv from builder
COPY --from=builder /opt/minicode-venv /opt/minicode-venv

# Make minicode-py available on PATH
ENV PATH="/opt/minicode-venv/bin:${PATH}"

# Create persistent data directories
RUN mkdir -p /home/minicode/.mini-code/memory /home/minicode/.mini-code/skills && \
    chown -R minicode:minicode /home/minicode/.mini-code

# Default workspace
RUN mkdir -p /workspace && chown minicode:minicode /workspace
WORKDIR /workspace

# Environment defaults (override at runtime)
ENV MINI_CODE_LOG_LEVEL=WARNING \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    # Container hint — lets MiniCode know it's running in Docker
    MINI_CODE_CONTAINER=docker

# Health check: verify the CLI entry point works
HEALTHCHECK --interval=60s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from minicode.main import main; print('ok')" || exit 1

# Switch to non-root user
USER minicode

# Default entry: interactive CLI mode
ENTRYPOINT ["minicode-py"]
CMD ["--help"]
