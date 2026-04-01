# ╔══════════════════════════════════════════════════════════════════╗
# ║  Single-Stage Python Build                                       ║
# ║  Frontend is pre-built and committed at audiobook_frontend/dist  ║
# ║  No Node.js required — fast, reliable Render free-tier build     ║
# ╚══════════════════════════════════════════════════════════════════╝
FROM python:3.11-slim

# System deps (ffmpeg for pydub, gcc for some wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        gcc \
        g++ \
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps first (layer cache optimisation)
COPY audiobook_backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy model (~12 MB)
RUN python -m spacy download en_core_web_sm

# Copy backend source
COPY audiobook_backend/ ./

# Copy pre-built React frontend assets (committed to repo)
# FastAPI serves these via StaticFiles at /app/frontend/dist
COPY audiobook_frontend/dist ./frontend/dist

# Create persistent storage dirs
RUN mkdir -p storage/uploads storage/audio storage/exports storage/music_cache

# Non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
