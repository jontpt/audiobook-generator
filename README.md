# 🎧 AI Audiobook Generator

> Convert any book (PDF, DOCX, ePub, TXT) into a multi-voice AI audiobook with emotion-aware narration, character voice assignment, and background music.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/yourname/audiobook-generator)

---

## ✨ Features

| Feature | Details |
|---|---|
| **Multi-voice TTS** | ElevenLabs integration with automatic character detection |
| **Emotion-aware narration** | NLP detects emotion per segment → adjusts delivery |
| **Background music** | Mubert & Soundraw API integration (per-emotion tracks) |
| **Real-time progress** | WebSocket updates during processing |
| **JWT authentication** | Register/login, per-user API key vault |
| **Scalable pipeline** | Celery + Redis workers (swappable from BackgroundTasks) |
| **PostgreSQL / SQLite** | Auto-detected from DATABASE_URL |
| **React + TypeScript UI** | Dark-themed, responsive, served by FastAPI |

---

## 🚀 Quick Start (Local)

### Option A — Single command (Docker Compose)

```bash
git clone https://github.com/yourname/audiobook-generator
cd audiobook-generator

# Copy and edit env file
cp audiobook_backend/.env.example .env
# ↑ Add ELEVENLABS_API_KEY, SECRET_KEY (openssl rand -hex 32)

docker compose up -d

# View logs
docker compose logs -f app

# Open in browser
open http://localhost:8000
```

**Services started:**
- `http://localhost:8000` — App (React frontend + API)
- `http://localhost:5555` — Flower (Celery monitoring, admin/admin)

---

### Option B — Dev mode (no Docker)

**Backend:**
```bash
cd audiobook_backend
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm

cp .env.example .env  # Add your ELEVENLABS_API_KEY and SECRET_KEY
python main.py        # API at http://localhost:8000
```

**Frontend (separate terminal):**
```bash
cd audiobook_frontend
npm install
npm run dev           # UI at http://localhost:5173
```

**Demo account:** `demo` / `demo1234`

---

## ☁️ Cloud Deployment

### 🟢 Render.com (Recommended — Free tier available)

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → **New** → **Blueprint**
3. Connect your repo — Render reads `render.yaml` automatically
4. In the Render dashboard, set:
   - `ELEVENLABS_API_KEY` = your ElevenLabs key
   - `SECRET_KEY` = output of `openssl rand -hex 32`
5. Click **Deploy** → your app is live at `https://audiobook-api.onrender.com`

> ⚠️ Free tier spins down after 15 min idle. Upgrade to Starter ($7/mo) for always-on.

---

### 🚂 Railway.app

```bash
npm install -g @railway/cli
railway login
railway init
railway add --plugin postgresql
railway add --plugin redis
railway up
railway open
```

Set environment variables in Railway dashboard:
```
ELEVENLABS_API_KEY=your_key_here
SECRET_KEY=$(openssl rand -hex 32)
USE_CELERY=true
```

---

### 🪂 Fly.io (Free tier available)

```bash
# Install flyctl: https://fly.io/docs/hands-on/install-flyctl/
flyctl auth login
flyctl launch       # auto-detects Dockerfile, creates fly.toml
flyctl secrets set \
  ELEVENLABS_API_KEY=your_key_here \
  SECRET_KEY=$(openssl rand -hex 32)
flyctl deploy
flyctl open
```

Add Postgres + Redis:
```bash
flyctl postgres create --name audiobook-db
flyctl redis create --name audiobook-redis
flyctl postgres attach --app audiobook-generator audiobook-db
```

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        Browser                               │
│          React + TypeScript (Vite, Tailwind, Framer)         │
└──────────────────────┬───────────────────────────────────────┘
                       │  HTTP + WebSocket
┌──────────────────────▼───────────────────────────────────────┐
│                    FastAPI (Python 3.11)                      │
│  /api/v1/auth    JWT register/login/me                       │
│  /api/v1/books   Upload, list, detail, progress WS           │
│  /api/v1/chars   Character detection, voice assignment       │
│  /api/v1/tts     ElevenLabs synthesis endpoints              │
│  /api/v1/export  Download audiobooks                         │
│  /api/v1/settings API-key vault                              │
│  /*              → React SPA (index.html)                    │
└────────┬─────────────────────┬────────────────────────────────┘
         │                     │
┌────────▼────────┐   ┌────────▼────────┐
│  PostgreSQL /   │   │   Redis          │
│  SQLite         │   │  (Celery broker) │
└─────────────────┘   └────────┬─────────┘
                               │
                      ┌────────▼────────┐
                      │  Celery Worker   │
                      │  (pipeline.py)   │
                      │  TTS synthesis   │
                      │  Audio mixing    │
                      └─────────────────┘
```

### Processing Pipeline

```
Upload (PDF/DOCX/ePub/TXT)
  ↓
Text Extraction (PyMuPDF / python-docx / ebooklib)
  ↓
NLP Analysis (spaCy — characters, emotions, segments)
  ↓
Voice Assignment (ElevenLabs catalogue / defaults)
  ↓
TTS Synthesis (ElevenLabs or mock mode)
  ↓
Background Music (Mubert / Soundraw — optional)
  ↓
Audio Mixing (pydub — chapter assembly)
  ↓
Export (MP3 / M4B)
```

---

## 🔑 API Keys

| Service | Purpose | Where to get |
|---|---|---|
| **ElevenLabs** | Text-to-speech | [elevenlabs.io](https://elevenlabs.io) → Profile → API Keys |
| **Mubert** | Background music | [mubert.com/render](https://mubert.com/render/pricing) (B2B) |
| **Soundraw** | Background music | [soundraw.io/api_access](https://soundraw.io/api_access) |
| **Jamendo** | Free background music API (non-commercial dev usage) | [developer.jamendo.com](https://developer.jamendo.com/) → create app (`client_id`) |

API keys can be stored **per-user** in Settings → API Keys (encrypted in DB), or set globally in the `.env` file.

---

## 📁 Project Structure

```
.
├── Dockerfile              # Multi-stage build (React + Python)
├── docker-compose.yml      # Full stack: app + worker + redis + postgres
├── render.yaml             # Render.com blueprint
├── railway.toml            # Railway.app config
├── fly.toml                # Fly.io config
│
├── audiobook_backend/
│   ├── main.py             # FastAPI app entry point
│   ├── config.py           # Settings (env vars)
│   ├── celery_app.py       # Celery task definitions
│   ├── requirements.txt
│   ├── .env.example
│   ├── api/routes/
│   │   ├── auth.py         # JWT auth endpoints
│   │   ├── books.py        # Upload, list, WebSocket progress
│   │   ├── characters.py   # Character / voice management
│   │   ├── export.py       # Download audiobooks
│   │   ├── settings.py     # API key vault
│   │   └── tts.py          # Direct TTS endpoints
│   ├── models/
│   │   ├── database.py     # SQLAlchemy async (SQLite/Postgres)
│   │   └── schemas.py      # Pydantic models
│   └── services/
│       ├── pipeline.py     # Main processing orchestrator
│       ├── tts_service.py  # ElevenLabs TTS
│       ├── nlp_processor.py # spaCy NLP
│       ├── audio_mixer.py  # pydub audio assembly
│       ├── music_service.py # Mubert / Soundraw
│       ├── voice_manager.py # Voice assignment
│       ├── text_extraction.py # Document parsing
│       ├── auth_service.py # JWT + password hashing
│       └── websocket_manager.py # WS connection manager
│
└── audiobook_frontend/
    ├── src/
    │   ├── App.tsx           # Router + auth
    │   ├── api/              # Axios API clients
    │   ├── contexts/         # AuthContext
    │   ├── hooks/
    │   │   └── useBookProgress.ts  # WebSocket hook
    │   ├── pages/            # All page components
    │   ├── components/       # UI, Layout, Books, Audio
    │   └── types/index.ts    # TypeScript interfaces
    └── dist/                 # Built static assets (served by FastAPI)
```

---

## 🛠️ Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(required)* | JWT signing key (`openssl rand -hex 32`) |
| `DATABASE_URL` | SQLite | PostgreSQL or SQLite URL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for Celery |
| `USE_CELERY` | `false` | Enable Celery workers |
| `ELEVENLABS_API_KEY` | — | ElevenLabs API key |
| `MUBERT_API_KEY` | — | Mubert music API key |
| `SOUNDRAW_API_KEY` | — | Soundraw music API key |
| `DEBUG` | `false` | Enable debug logging |
| `CORS_ORIGINS` | `*` | Allowed CORS origins |

---

## 🧪 Running Tests

```bash
cd audiobook_backend
python tests/test_pipeline.py
```

---

## 📄 License

MIT — see [LICENSE](LICENSE)
