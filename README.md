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
- Windows 10/11, Linux (tested on Ubuntu 24.04), or macOS
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

### Linux / macOS

#### 1. Clone and install dependencies

```bash
git clone https://github.com/YOUR_USERNAME/ARIA.git
cd ARIA
pip install -r requirements.txt
```

#### 2. Pull an Ollama model

```bash
ollama pull qwen2.5:14b
```

#### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your values (see comments inside)
```

Or run the interactive wizard:

```bash
python3 setup.py
```

#### 4. Run

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

### Windows 10 / 11

#### Prerequisites

1. **Python 3.10+** — download from [python.org](https://www.python.org/downloads/) (check *Add Python to PATH* during install)
2. **Ollama for Windows** — download from [ollama.com](https://ollama.com/download/windows) and run the installer
3. **Git** — [git-scm.com](https://git-scm.com/download/win) (optional, or download the zip from GitHub)
4. **Microsoft C++ Build Tools** — required by some Python packages.  
   Install the "Desktop development with C++" workload from [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/).

#### 1. Clone and install dependencies

Open **PowerShell** or **Command Prompt**:

```powershell
git clone https://github.com/YOUR_USERNAME/ARIA.git
cd ARIA
pip install -r requirements.txt
```

> **Optional extras for Windows:**  
> `pip install win10toast Pillow`  
> `win10toast` enables native Windows toast notifications.  
> `Pillow` enables the screenshot tool.

#### 2. Pull an Ollama model

```powershell
ollama pull qwen2.5:14b
```

Ollama on Windows runs as a background service after install; no `ollama serve` needed.

#### 3. Configure environment

Run the interactive wizard (recommended):

```powershell
python setup.py
```

Or copy the example file manually:

```powershell
copy .env.example .env
# Edit .env with Notepad or any editor
```

At minimum you need:
- `ARIA_PASSWORD` — password for the web UI
- `SECRET_KEY` — random Flask session key (the wizard generates this for you)
- `OLLAMA_MODEL` — model name you pulled

#### 4. Run

**Web UI only (browser):**
```powershell
python app.py
# Open http://localhost:5000
```

**Desktop window (PyWebView):**
```powershell
python launch.py
```

**Voice only (terminal):**
```powershell
python aria.py
```

**Text only (no mic):**
```powershell
python aria.py --text
```

#### Windows feature notes

| Feature | Windows support |
|---------|----------------|
| Wake word detection | ✅ Full support |
| Speech-to-text (Whisper) | ✅ Full support |
| Text-to-speech (Piper / Edge TTS) | ✅ Full support |
| Local LLM via Ollama | ✅ Full support |
| Web UI | ✅ Full support |
| Open URLs / apps | ✅ Uses `os.startfile` / shell |
| Volume control | ✅ Windows media keys via ctypes |
| Lock / sleep / shutdown / reboot | ✅ Windows API equivalents |
| Clipboard read/write | ✅ PowerShell `Get-Clipboard` / `Set-Clipboard` |
| Screenshot | ✅ Requires `pip install Pillow` |
| Desktop notifications | ⚠️ Requires `pip install win10toast` |
| Shell (bash) execution | ⚠️ Uses `cmd.exe`; POSIX commands need Git Bash on PATH |
| Spotify MPRIS control | ⚠️ Spotipy Web API works; dbus controls are Linux-only |
| CPU temperature sensor | ⚠️ WMI query (may need elevated permissions) |

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
