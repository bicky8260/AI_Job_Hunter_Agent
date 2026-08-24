# ============================================================
# AI Job Hunter — Dockerfile
# Multi-stage build for a small production image
# ============================================================

FROM python:3.11-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies needed for lxml, asyncpg, pdfplumber
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libxml2-dev \
    libxslt-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ──────────────────────────────────────────────────────────────
# Dependencies layer (cached separately from code)
# ──────────────────────────────────────────────────────────────
FROM base AS deps

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ──────────────────────────────────────────────────────────────
# Production image
# ──────────────────────────────────────────────────────────────
FROM deps AS production

# Copy application code
COPY app/ ./app/
COPY config.yaml .

# Create runtime directories
RUN mkdir -p uploads logs email_output

# Non-root user for security
RUN useradd -m -u 1001 jobhunter && chown -R jobhunter:jobhunter /app
USER jobhunter

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
