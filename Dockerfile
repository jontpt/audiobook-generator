# ╔══════════════════════════════════════════════════════════════════╗
# ║  Stage 1 — Build React frontend                                  ║
# ╚══════════════════════════════════════════════════════════════════╝
FROM node:20-slim AS frontend-builder

WORKDIR /frontend
COPY audiobook_frontend/package*.json ./
RUN npm ci --silent

COPY audiobook_frontend/ ./
RUN npm run build


# ╔══════════════════════════════════════════════════════════════════╗
# ║  Stage 2 — Python backend + bundled frontend                     ║
# ╚══════════════════════════════════════════════════════════════════╝
FROM python:3.11-slim AS backend

# System deps (ffmpeg for pydub, gcc for some wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        gcc \
        g++ \
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY audiobook_backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy model (small, ~12 MB)
RUN python -m spacy download en_core_web_sm

# Copy backend source
COPY audiobook_backend/ ./

# Copy built React assets into backend so FastAPI can serve them
COPY --from=frontend-builder /frontend/dist ./frontend/dist

# Create storage dirs
RUN mkdir -p storage/uploads storage/audio storage/exports storage/music_cache

# Non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
