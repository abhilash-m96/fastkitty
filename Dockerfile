FROM python:3.12-slim-bookworm

# Install pinned uv from official image
COPY --from=ghcr.io/astral-sh/uv:0.5.13 /uv /bin/uv

WORKDIR /app

# Enable bytecode compilation, unbuffered stdout, and isolate container venv in /opt/venv
ENV UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Install dependencies first for optimal layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY . .

# Finalize project install
RUN uv sync --frozen --no-dev

# Create non-root system user and drop root privileges
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser \
    && chown -R appuser:appuser /app /opt/venv

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health')" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

