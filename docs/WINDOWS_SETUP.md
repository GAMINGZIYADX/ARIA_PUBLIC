# ARIA — Windows Setup Guide

ARIA was developed on Linux but is fully Windows-compatible as of commit `de5ed62`.
This guide covers a clean manual install from source using Python and a virtual environment.

> If you prefer a one-click install, use the **[ARIA_Setup.exe](https://github.com/GAMINGZIYADX/ARIA_PUBLIC/releases/latest/download/ARIA_Setup.exe)** from the latest release instead.

---

## Prerequisites

Install all three before proceeding.

### 1. Python 3.11 or 3.12 (64-bit)

Download from [python.org/downloads](https://www.python.org/downloads/).

During install, check **"Add Python to PATH"** — this is unchecked by default and the most common cause of `python is not recognized` errors.

Verify in a new Command Prompt:
```
python --version
```

### 2. Ollama

Download from [ollama.com/download](https://ollama.com/download) and run the installer.

Ollama runs as a background service. Verify it is running:
```
ollama list
```
If that returns a table (even an empty one), Ollama is up.

### 3. Git

Download from [git-scm.com](https://git-scm.com/download/win) and install with defaults.

Verify:
```
git --version
```

---

## Clone the Repo

Open Command Prompt or PowerShell and run:

```bat
git clone https://github.com/GAMINGZIYADX/ARIA_PUBLIC.git
cd ARIA_PUBLIC
```

---

## Create a Virtual Environment

```bat
python -m venv venv
venv\Scripts\activate
```

Your prompt will change to `(venv) C:\...`. Keep this terminal open — always activate the venv before running ARIA.

---

## Create the .env File

ARIA auto-creates a `.env` with safe defaults on first run, but it is better to set it yourself.

Copy the example:
```bat
copy .env.example .env
```

Open `.env` in Notepad and set at minimum:

```env
ARIA_PASSWORD=your_password_here
OLLAMA_URL=http://127.0.0.1:11434/v1
OLLAMA_MODEL=qwen2.5:7b
SKIP_AUTH=0
```

**Quick-start tip:** Set `SKIP_AUTH=1` to skip the login screen entirely during development or on a trusted private machine. You can re-enable it later by setting it back to `0`.

---

## Install Dependencies

With the venv active:

```bat
pip install -r requirements.txt
```

This pulls Flask, faster-whisper, openai, soundfile, and all other dependencies. It may take a few minutes on first run.

---

## Pull an Ollama Model

ARIA defaults to `qwen2.5:7b`. Pull it before launching:

```bat
ollama pull qwen2.5:7b
```

See [ollama.com/library](https://ollama.com/library) for other models. Update `OLLAMA_MODEL` in `.env` to match.

---

## Run ARIA

```bat
python app.py
```

Then open **http://localhost:5000** in your browser.

On first launch you will see:
```
✓ Ollama client initialised at http://127.0.0.1:11434/v1
✓ Proactive engine ready
 * Running on http://127.0.0.1:5000
```

Log in with the password you set in `.env` (default: `aria` if you let ARIA auto-create the file).

---

## Fix a Corrupted Whisper Cache (STT Fails)

If speech-to-text crashes with a model loading error on startup, the Whisper cache is likely corrupted. Delete it and ARIA will re-download on next launch:

1. Press `Win + R`, type `%USERPROFILE%\.cache\huggingface\hub` and press Enter.
2. Delete any folder whose name starts with `models--Systran--faster-whisper-`.
3. Restart `python app.py`.

Alternatively, from PowerShell:
```powershell
Remove-Item "$env:USERPROFILE\.cache\huggingface\hub\models--Systran--*" -Recurse -Force
```

---

## Common Errors and Fixes

### `python is not recognized as an internal or external command`

Python was not added to PATH during install.

**Fix:** Re-run the Python installer, choose **Modify**, and check **"Add Python to environment variables"**. Then open a new terminal.

---

### Login fails — "Invalid password"

The password submitted does not match `ARIA_PASSWORD` in `.env`.

**Fix:** Open `.env`, confirm the value of `ARIA_PASSWORD`, and use that exact string on the login page. For development, set `SKIP_AUTH=1` to bypass the login screen.

---

### Whisper crashes or STT is unavailable at startup

Common causes: corrupted model cache, missing CUDA libraries, or insufficient VRAM.

**Fix:** Delete the cache (see section above). ARIA will fall back through progressively lighter Whisper configurations (`float16 → int8 → base on CPU`) automatically. If all fail, STT is disabled but the rest of ARIA still works.

---

### `ModuleNotFoundError` on startup

A dependency is missing or the venv is not activated.

**Fix:**
```bat
venv\Scripts\activate
pip install -r requirements.txt
```

---

### `templates/login.html` not found — Jinja2 TemplateNotFound

The templates directory is missing or the repo was cloned incompletely.

**Fix:**
```bat
git status
git restore .
```
If that does not help, re-clone the repo.

---

### Favicon returns 500

`static/aria_icon.png` is missing. As of commit `de5ed62` the favicon route returns a `204 No Content` instead of crashing, so this should no longer bring down the server. If you see a 500, you are on an older commit — pull latest.

**Fix:**
```bat
git pull origin main
```

---

### `ollama: command not found` / Ollama not responding

Ollama is not installed or its service is not running.

**Fix:** Download Ollama from [ollama.com/download](https://ollama.com/download). After install, open a new terminal and run `ollama serve` if the service did not start automatically.

---

## Keeping ARIA Updated

```bat
git pull origin main
venv\Scripts\activate
pip install -r requirements.txt
```

---

## Uninstalling

If you used the manual venv method:

1. Delete the `ARIA_PUBLIC` folder.
2. Optionally delete the Whisper cache: `%USERPROFILE%\.cache\huggingface\hub\models--Systran--*`

If you used the `.exe` installer, uninstall through **Windows Settings → Apps → ARIA**.
