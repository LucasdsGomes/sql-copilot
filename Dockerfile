# syntax=docker/dockerfile:1
# ──────────────────────────────────────────────────────────────────────────────
# SQL Copilot – production image
#
# Runtime env vars required:
#   ANTHROPIC_API_KEY   – your Anthropic key (never baked in)
#   API_KEYS            – comma-separated accepted API keys
#
# Optional overrides (with sensible defaults):
#   PORT                – port uvicorn listens on (default 8000; cloud platforms inject this)
#   DATABASE_PATH       – SQLite path inside the container (default /app/data/sales.db)
#   FORWARDED_ALLOW_IPS – uvicorn trusted proxy IPs (default 127.0.0.1; set to * only behind a
#                         known reverse-proxy)
#   RATE_LIMIT          – e.g. "30/minute"
#   MAX_ROWS            – hard cap on query rows (default 100)
# ──────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

# ── System hardening ──────────────────────────────────────────────────────────
# Prevent .pyc spam and enable unbuffered logs in container stdout.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ── Install Python dependencies (no dev extras) ────────────────────────────
# Copy only the files needed for installation first so Docker can cache this
# layer independently of source-code changes.
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

# ── Copy application code ──────────────────────────────────────────────────
COPY scripts/ ./scripts/

# ── Seed the sample database at build time ────────────────────────────────
# The .db file is not in git; we generate it here so the image is self-contained.
# DATABASE_PATH is set explicitly so seed_db.py writes to the right place even
# if the default in config.py is a relative path.
ENV DATABASE_PATH=/app/data/sales.db
RUN python scripts/seed_db.py

# ── Non-root user ─────────────────────────────────────────────────────────
RUN useradd --no-create-home --shell /bin/false appuser \
 && chown -R appuser:appuser /app
USER appuser

# ── Runtime defaults ──────────────────────────────────────────────────────
ENV PORT=8000 \
    FORWARDED_ALLOW_IPS=127.0.0.1

EXPOSE ${PORT}

# ── Health check ──────────────────────────────────────────────────────────
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c \
        "import urllib.request, sys; \
         r = urllib.request.urlopen('http://localhost:' + __import__('os').environ.get('PORT','8000') + '/health', timeout=4); \
         sys.exit(0 if r.status == 200 else 1)"

# ── Entrypoint ────────────────────────────────────────────────────────────
# PORT and FORWARDED_ALLOW_IPS are expanded by the shell at container start.
CMD ["sh", "-c", \
     "exec uvicorn sql_copilot.api.main:app \
      --host 0.0.0.0 \
      --port ${PORT} \
      --forwarded-allow-ips ${FORWARDED_ALLOW_IPS}"]
