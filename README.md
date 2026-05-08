# ARIA — Advanced Responsive Intelligent Assistant

A fully local, voice-enabled AI assistant that runs on your own hardware. No cloud. No data leaves your machine.

ARIA listens for a wake word, understands spoken commands, and can open apps, search the web, control Spotify, run bash commands, and hold conversations — all powered by a local LLM via Ollama.

---

## Features

- **Wake word detection** — says "Aria" and she wakes up (OpenWakeWord, fully offline)
- **Speech-to-text** — Faster-Whisper (CUDA-accelerated, runs locally)
- **Text-to-speech** — Piper TTS (offline), falls back to Edge TTS
- **Local LLM** — powered by Ollama (tested with Qwen 2.5 14B)
- **Web UI** — Flask dashboard with bash execution, file viewer, and chat
- **Tool calling** — opens apps, URLs, searches DuckDuckGo, controls Spotify
- **World Intelligence** — background RSS aggregator with breaking news alerts
- **Proactive Engine** — ARIA initiates messages based on time and context
- **Memory** — persistent facts, conversation history, and personality model

---

## Requirements

- Python 3.10+
- Linux (tested on Ubuntu 24.04)
- [Ollama](https://ollama.com/) running locally
- CUDA-compatible GPU recommended (CPU works but is slower)
- Microphone for voice mode

---

## Landing Page

A GitHub Pages landing page lives in `docs/index.html`.

To enable it:
1. Push this repo to GitHub
2. Go to **Settings → Pages**
3. Under **Source**, select **Deploy from a branch**
4. Set the branch to `main` (or `master`) and the folder to **`/docs`**
5. Save — your site will be live at `https://YOUR_USERNAME.github.io/ARIA/`

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/YOUR_USERNAME/ARIA.git
cd ARIA
pip install -r requirements.txt
```

### 2. Pull an Ollama model

```bash
ollama pull qwen2.5:14b
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your values (see comments inside)
```

At minimum you need:
- `ARIA_PASSWORD` — password for the web UI
- `SECRET_KEY` — random Flask session key
- `OLLAMA_MODEL` — model name you pulled

### 4. Set your name

Open `data/persona.json` and replace `YOUR_NAME` with your name. This is what ARIA will call you.

### 5. Run

**Voice + web UI (desktop window):**
```bash
python3 launch.py
```

**Web UI only (browser):**
```bash
bash run-web.sh
# Open http://localhost:5000
```

**Voice only (terminal):**
```bash
python3 aria.py
```

**Text only (no mic):**
```bash
python3 aria.py --text
```

---

## Spotify Setup (optional)

ARIA can search and play music via Spotify's API.

1. Create an app at [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Add `http://127.0.0.1:8888/callback` as a Redirect URI
3. Copy your Client ID and Secret into `.env`
4. Run the one-time auth flow:

```bash
python3 scripts/spotify_auth.py
```

The token is cached in `data/.spotify_cache` and auto-refreshed from then on.

---

## Project Structure

```
ARIA/
├── aria.py               # Voice assistant core (wake word + STT + TTS + LLM)
├── app.py                # Flask web UI backend
├── launch.py             # Desktop launcher (PyWebView wrapper)
├── spotify_reader.py     # Spotify playback and now-playing queries
├── proactive_engine.py   # Time-based ARIA-initiated messages
├── diagnostic.py         # System diagnostics tool
├── modules/
│   ├── web_search.py     # DuckDuckGo search (no API key needed)
│   └── world_intelligence.py  # RSS news aggregator
├── scripts/
│   └── spotify_auth.py   # One-time Spotify OAuth setup
├── templates/
│   └── index.html        # Web UI frontend
├── static/               # Icons and CSS
├── data/
│   ├── memory.json       # Persistent facts and history (auto-created)
│   └── persona.json      # User profile and ARIA personality
├── .env.example          # All required environment variables (copy to .env)
├── requirements.txt
└── docs/
    └── index.html        # GitHub Pages landing page
```

---

## License

Source-available — see [License](License) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for terms.  
Commercial use requires written permission. Attribution to the original author must be preserved.

© 2026 Ziyad Noucair
