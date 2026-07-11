#!/usr/bin/env python3
"""
ARIA - Advanced Responsive Intelligent Assistant
Powered by Ollama + Faster-Whisper (CUDA) + OpenWakeWord + TTS
"""

import os
import sys
import time
import shutil
import tempfile
import threading

# Suppress ALSA/JACK warnings on Linux (cosmetic noise from audio backend probing)
os.environ["PYTHONWARNINGS"] = "ignore"
if sys.platform != "win32":
    os.environ["SDL_AUDIODRIVER"] = "pulseaudio"
    os.environ["JACK_NO_START_SERVER"] = "1"
    os.environ["JACK_NO_AUDIO_RESERVATION"] = "1"
    import ctypes as _ctypes_alsa
    _ERROR_HANDLER_FUNC = _ctypes_alsa.CFUNCTYPE(
        None, _ctypes_alsa.c_char_p, _ctypes_alsa.c_int,
        _ctypes_alsa.c_char_p, _ctypes_alsa.c_int, _ctypes_alsa.c_char_p)
    def _alsa_error_handler(filename, line, function, err, fmt):
        pass
    _c_alsa_error_handler = _ERROR_HANDLER_FUNC(_alsa_error_handler)
    try:
        asound = _ctypes_alsa.cdll.LoadLibrary("libasound.so.2")
        asound.snd_lib_error_set_handler(_c_alsa_error_handler)
    except OSError:
        pass

# Redirect stderr briefly during PyAudio import to suppress JACK connection spam
import io as _io
_old_stderr = sys.stderr
sys.stderr = _io.StringIO()
try:
    import pyaudio as _pa_test  # noqa: F401 — triggers PortAudio init
finally:
    sys.stderr = _old_stderr

import asyncio
import json
import subprocess
from openai import OpenAI
import numpy as np
from faster_whisper import WhisperModel
from openwakeword.model import Model
import urllib.request
import wave
import edge_tts
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame
from rich.console import Console

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
# Ollama runs on localhost:11434 by default
OLLAMA_API_BASE = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")

# OpenWakeWord wake word detection (no API key required!)
WAKE_WORD_MODEL = "aria"  # Available models: aria, jarvis, alexa, hey_google, hey_siri, ok_google, etc.
WAKE_WORD_THRESHOLD = 0.5  # Detection confidence threshold (0.0-1.0, higher = stricter)

# TTS Voice (using Aria Neural voice)
TTS_VOICE = "en-US-AriaNeural"

# Faster-Whisper model — size auto-selected from GPU VRAM at runtime (see hw_detect.py)
# Override with WHISPER_MODEL env var if you want to force a specific size.
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "")  # empty → auto-detect

# ─────────────────────────────────────────────
# HARDWARE DETECTION (runs once at startup)
# ─────────────────────────────────────────────
import hw_detect as _hw_detect
_HW = _hw_detect.get_profile()
_hw_detect.add_llm_warning(_HW, OLLAMA_MODEL)

print(f"  HW: {_hw_detect.summarize(_HW)}", file=sys.stderr)
if _HW.llm_warning:
    print(f"  ⚠  LLM warning: {_HW.llm_warning}", file=sys.stderr)

SYSTEM_PROMPT = """You are ARIA. Respond in 1-2 sentences. No filler.

For tools, reply ONLY with JSON:
{"tool":"open_app","args":{"app_name":"brave|spotify|terminal|vscode|files"}}
{"tool":"open_url","args":{"url":"https://..."}}
{"tool":"search_web","args":{"query":"..."}}
{"tool":"play_on_spotify","args":{"query":"..."}}

Non-tool questions: plain text only, 1-2 sentences."""

# ─────────────────────────────────────────────
# APP MAPPING  (platform-aware)
# ─────────────────────────────────────────────
# APP_MAP is a strict allowlist: only these pre-registered apps can ever be
# launched. There is NO raw-string fallback — an unknown app name is rejected,
# never executed. Values are platform-specific launch targets:
#   Linux   → binary name (resolved on PATH by Popen / shutil.which)
#   Windows → executable name (resolved via shutil.which; PATH apps only)
#   macOS   → .app bundle name (resolved by `open -a`, no PATH needed)
# BROWSER_MAP is the equivalent allowlist for open_url's optional `browser` arg.
if sys.platform == "win32":
    APP_MAP = {
        # Browsers
        "brave": "brave", "firefox": "firefox",
        "chrome": "chrome", "google chrome": "chrome",
        "edge": "msedge", "microsoft edge": "msedge",
        # Creative
        "gimp": "gimp-2.10", "blender": "blender", "krita": "krita",
        "inkscape": "inkscape", "obs": "obs64",
        # Communication
        "discord": "Discord", "slack": "slack",
        "telegram": "Telegram", "zoom": "Zoom",
        # Gaming
        "steam": "steam", "epic games": "EpicGamesLauncher",
        # Dev
        "vscode": "code", "vs code": "code", "code": "code",
        "terminal": "cmd", "term": "cmd", "powershell": "powershell",
        # Media / files
        "spotify": "spotify", "vlc": "vlc",
        "files": "explorer", "file manager": "explorer",
    }
    BROWSER_MAP = {
        "brave": "brave", "firefox": "firefox",
        "chrome": "chrome", "edge": "msedge",
    }
elif sys.platform == "darwin":
    APP_MAP = {
        "brave": "Brave Browser", "firefox": "Firefox",
        "chrome": "Google Chrome", "google chrome": "Google Chrome",
        "edge": "Microsoft Edge", "microsoft edge": "Microsoft Edge",
        "gimp": "GIMP", "blender": "Blender", "krita": "Krita",
        "inkscape": "Inkscape", "obs": "OBS",
        "discord": "Discord", "slack": "Slack",
        "telegram": "Telegram", "zoom": "zoom.us",
        "steam": "Steam", "epic games": "Epic Games Launcher",
        "vscode": "Visual Studio Code", "vs code": "Visual Studio Code",
        "code": "Visual Studio Code",
        "terminal": "Terminal", "term": "Terminal",
        "spotify": "Spotify", "vlc": "VLC",
        "files": "Finder", "file manager": "Finder",
    }
    BROWSER_MAP = {
        "brave": "Brave Browser", "firefox": "Firefox",
        "chrome": "Google Chrome", "edge": "Microsoft Edge",
        "safari": "Safari",
    }
else:  # Linux
    APP_MAP = {
        "brave": "brave-browser", "firefox": "firefox",
        "chrome": "google-chrome", "google chrome": "google-chrome",
        "edge": "microsoft-edge",
        "gimp": "gimp", "blender": "blender", "krita": "krita",
        "inkscape": "inkscape", "obs": "obs",
        "discord": "discord", "slack": "slack",
        "telegram": "telegram-desktop", "zoom": "zoom",
        "steam": "steam",
        "vscode": "code", "vs code": "code", "code": "code",
        "terminal": "gnome-terminal", "term": "gnome-terminal",
        "spotify": "spotify", "vlc": "vlc",
        "files": "nautilus", "file manager": "nautilus", "nautilus": "nautilus",
    }
    BROWSER_MAP = {
        "brave": "brave-browser", "firefox": "firefox",
        "chrome": "google-chrome", "edge": "microsoft-edge",
    }

# ─────────────────────────────────────────────
# TOOLS DEFINITION (OpenAI Function Calling Format)
# ─────────────────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Launch a desktop application",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "Name of the app to open (e.g., 'brave', 'spotify', 'vscode', 'terminal')"
                    }
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "Open a URL in a specified browser or default application",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to open (e.g., 'https://youtube.com')"
                    },
                    "browser": {
                        "type": "string",
                        "description": "Browser to use: 'brave', 'firefox', 'chrome', or 'default'. Default is 'default'."
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for a query and open results in a browser",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    },
                    "browser": {
                        "type": "string",
                        "description": "Browser to use: 'brave', 'firefox', 'chrome', or 'default'. Default is 'default'."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "play_on_spotify",
            "description": "Open Spotify and search for a song or artist",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Song name, artist name, or album to search for (e.g., 'Blinding Lights The Weeknd')"
                    }
                },
                "required": ["query"]
            }
        }
    }
]

# ─────────────────────────────────────────────
# INIT
# ─────────────────────────────────────────────
console = Console()
client = OpenAI(api_key="not-needed", base_url=OLLAMA_API_BASE)

# Faster-Whisper: lazy-loaded on first listen() call, pre-warmed in background for voice mode
whisper_model = None
_whisper_lock = threading.Lock()

def _get_whisper_model():
    global whisper_model
    if whisper_model is not None:
        return whisper_model
    with _whisper_lock:
        if whisper_model is not None:
            return whisper_model

        import hw_detect as _hw
        hw = _hw.get_profile()

        # Allow env-var override; otherwise use auto-detected size
        size    = WHISPER_MODEL or hw.whisper_size
        device  = hw.whisper_device
        compute = hw.whisper_compute

        print(f"Loading Faster-Whisper '{size}' on {device.upper()}/{compute}…", file=sys.stderr)

        # Try preferred config first, then progressively lighter fallbacks
        attempts = [(device, compute, size)]
        if device == "cuda":
            # If GPU fails, fall back to CPU with the same size, then tiny
            attempts += [
                ("cuda", "int8", size),         # retry with int8 if float16 failed
                ("cpu",  "int8", size),
                ("cpu",  "int8", "base"),
            ]
        for dev, cmp, sz in dict.fromkeys(map(tuple, attempts)):  # dedup
            try:
                whisper_model = WhisperModel(sz, device=dev, compute_type=cmp)
                print(f"✓ Whisper ready — '{sz}' / {dev.upper()} / {cmp}", file=sys.stderr)
                break
            except Exception as exc:
                print(f"  [{dev}/{cmp}/{sz}] failed: {exc}", file=sys.stderr)

        if whisper_model is None:
            print("✗ Whisper could not load on any configuration", file=sys.stderr)
    return whisper_model

# OpenWakeWord will be lazily initialized when voice_mode is called (not needed for text_mode)
oww_model = None

def init_openwakeword():
    """Lazily initialize OpenWakeWord, suppressing non-critical warnings."""
    global oww_model
    if oww_model is not None:
        return  # Already initialized

    # Suppress stderr during initialization to hide model download warnings
    _old_stderr = sys.stderr
    sys.stderr = _io.StringIO()
    try:
        oww_model = Model([WAKE_WORD_MODEL])
        sys.stderr = _old_stderr  # Restore early on success
    except Exception as e1:
        sys.stderr = _old_stderr  # Restore before retry
        try:
            oww_model = Model(wakeword_models=[WAKE_WORD_MODEL])
        except Exception as e2:
            print(f"Warning: OpenWakeWord initialization failed: {e2}", file=sys.stderr)
            oww_model = None

conversation_history = []
pygame.mixer.init()


# ─────────────────────────────────────────────
# TOOL EXECUTION FUNCTIONS
# ─────────────────────────────────────────────
def run_open_app(app_name: str) -> str:
    """Launch a desktop application from the APP_MAP allowlist.

    Only pre-registered apps are launchable. Unknown names are rejected, never
    executed — there is no raw-string fallback, and no shell is ever used, so an
    LLM-supplied name cannot become a command. On Windows the target is resolved
    with shutil.which() to preserve the PATH/PATHEXT resolution the old
    shelled-out launch was doing implicitly.
    """
    normalized = (app_name or "").lower().strip()
    target = APP_MAP.get(normalized)
    if target is None:
        available = ", ".join(sorted(APP_MAP))
        return f"App '{app_name}' not recognized. Available: {available}"
    try:
        if sys.platform == "darwin":
            # `open -a` resolves registered .app bundles without needing PATH.
            subprocess.Popen(["open", "-a", target],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "win32":
            exe = shutil.which(target)
            if not exe:
                return (f"'{app_name}' is registered but its executable "
                        f"('{target}') was not found on PATH.")
            subprocess.Popen([exe],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:  # Linux — Popen searches PATH; shutil.which is a resolvability check
            exe = shutil.which(target) or target
            subprocess.Popen([exe], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        return f"Launching {app_name}..."
    except FileNotFoundError:
        return f"Application '{app_name}' not found on this system."
    except Exception as e:
        return f"Error launching {app_name}: {e}"


def _open_url_default(url: str) -> None:
    """Open an already-validated http/https URL in the default browser. No shell."""
    if sys.platform == "win32":
        os.startfile(url)  # ShellExecute of a validated http/https URL
    elif sys.platform == "darwin":
        subprocess.Popen(["open", url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["xdg-open", url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_open_url(url: str, browser: str = "default") -> str:
    """Open a URL in the default browser or a named browser from BROWSER_MAP.

    Only http/https URLs are allowed. Other schemes (file://, javascript:,
    data:, ftp:, etc.) are explicitly rejected, not silently normalized. The
    `browser` arg is resolved through the BROWSER_MAP allowlist — a raw
    LLM-supplied browser string never reaches Popen — and no shell is used.
    """
    from urllib.parse import urlparse
    url = (url or "").strip()
    scheme = urlparse(url).scheme.lower()
    if scheme in ("http", "https"):
        pass
    elif scheme == "":
        url = "https://" + url          # bare host like "youtube.com"
    else:
        # file://, javascript:, data:, ftp:, etc. are rejected outright.
        return "Blocked: only http/https URLs are allowed."

    try:
        if (browser or "default").lower().strip() == "default":
            _open_url_default(url)
            return f"Opening {url}..."

        target = BROWSER_MAP.get(browser.lower().strip())
        if target is None:
            # Unknown browser → fall back to the safe default opener,
            # never the raw LLM-supplied string.
            _open_url_default(url)
            return f"Opening {url}..."

        if sys.platform == "darwin":
            subprocess.Popen(["open", "-a", target, url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "win32":
            exe = shutil.which(target)
            if not exe:
                _open_url_default(url)
                return f"Opening {url}..."
            subprocess.Popen([exe, url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            exe = shutil.which(target) or target
            subprocess.Popen([exe, url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Opening {url} in {browser}..."
    except Exception as e:
        return f"Error opening URL: {e}"


def run_search_web(query: str, browser: str = "default") -> str:
    """Search the web using DuckDuckGo."""
    try:
        search_url = f"https://duckduckgo.com/?q={query.replace(' ', '+')}"
        return run_open_url(search_url, browser)
    except Exception as e:
        return f"Error searching web: {e}"


def run_play_on_spotify(query: str) -> str:
    """Open Spotify and search for a song/artist."""
    try:
        spotify_uri = f"spotify:search:{query.replace(' ', '%20')}"
        if sys.platform == "win32":
            os.startfile(spotify_uri)  # ShellExecute handles spotify: URI scheme
        elif sys.platform == "darwin":
            subprocess.Popen(["open", spotify_uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", spotify_uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Searching Spotify for '{query}'..."
    except Exception as e:
        return f"Error opening Spotify: {e}"


# Tool dispatcher
TOOL_DISPATCH = {
    "open_app": run_open_app,
    "open_url": run_open_url,
    "search_web": run_search_web,
    "play_on_spotify": run_play_on_spotify,
}

# Expected arg shape per tool. Used to validate LLM-emitted tool calls BEFORE
# dispatch so a malformed or unexpected call is rejected instead of silently
# executing (or crashing on **kwargs). This is validation only — there is no
# confirmation prompt and no confidence gate, so voice UX stays frictionless.
_TOOL_ARG_SPEC = {
    "open_app":        {"required": {"app_name"}, "optional": set()},
    "open_url":        {"required": {"url"},       "optional": {"browser"}},
    "search_web":      {"required": {"query"},     "optional": {"browser"}},
    "play_on_spotify": {"required": {"query"},     "optional": set()},
}


def _validate_tool_args(tool_name: str, tool_args) -> tuple[bool, str]:
    """Return (ok, reason). Args must be a dict whose keys are exactly the
    tool's required params (plus any optional ones) and whose values are all
    strings. Rejects non-dict args, missing/unexpected keys, and non-string
    values — no execution happens on a bad shape."""
    spec = _TOOL_ARG_SPEC.get(tool_name)
    if spec is None:
        return False, "unknown tool"
    if not isinstance(tool_args, dict):
        return False, "args is not an object"
    keys = set(tool_args)
    allowed = spec["required"] | spec["optional"]
    missing = spec["required"] - keys
    if missing:
        return False, f"missing required args: {sorted(missing)}"
    extra = keys - allowed
    if extra:
        return False, f"unexpected args: {sorted(extra)}"
    for k, v in tool_args.items():
        if not isinstance(v, str):
            return False, f"arg '{k}' must be a string"
    return True, "ok"


# ─────────────────────────────────────────────
# PIPER TTS (fully offline)
# ─────────────────────────────────────────────
PIPER_MODEL_DIR = os.path.join("data", "piper")
PIPER_MODEL_NAME = "en_US-lessac-medium"
PIPER_MODEL_PATH = os.path.join(PIPER_MODEL_DIR, f"{PIPER_MODEL_NAME}.onnx")
PIPER_CONFIG_PATH = os.path.join(PIPER_MODEL_DIR, f"{PIPER_MODEL_NAME}.onnx.json")
PIPER_MODEL_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
PIPER_CONFIG_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"

_piper_voice = None  # lazy-loaded singleton


def _download_piper_model():
    """Download Piper model files if not already present."""
    os.makedirs(PIPER_MODEL_DIR, exist_ok=True)
    for path, url in [(PIPER_MODEL_PATH, PIPER_MODEL_URL), (PIPER_CONFIG_PATH, PIPER_CONFIG_URL)]:
        if not os.path.exists(path):
            print(f"Downloading Piper model: {os.path.basename(path)} ...", file=sys.stderr)
            try:
                urllib.request.urlretrieve(url, path)
            except Exception as e:
                print(f"Piper download failed: {e}", file=sys.stderr)
                raise


def _get_piper_voice():
    """Lazy-load and return the Piper voice singleton."""
    global _piper_voice
    if _piper_voice is None:
        from piper import PiperVoice
        _download_piper_model()
        _piper_voice = PiperVoice.load(PIPER_MODEL_PATH)
    return _piper_voice


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

# Pre-armed mic buffer for parallel TTS/STT overlap
_prefetch_frames: list = []
_prefetch_lock = threading.Lock()


def _prefetch_mic():
    """Pre-arm the mic and buffer ~0.5s of audio while TTS is finishing."""
    try:
        import pyaudio
        CHUNK, RATE = 2048, 16000
        p = pyaudio.PyAudio()
        stream = p.open(format=pyaudio.paFloat32, channels=1, rate=RATE,
                        input=True, frames_per_buffer=CHUNK)
        # Buffer ~0.5 seconds (4 chunks × 2048 / 16000 ≈ 0.51s)
        frames = []
        for _ in range(4):
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(np.frombuffer(data, dtype=np.float32))
        stream.stop_stream()
        stream.close()
        p.terminate()
        with _prefetch_lock:
            _prefetch_frames.clear()
            _prefetch_frames.extend(frames)
    except Exception:
        pass


def _speak_edge_tts(text: str):
    """Fallback TTS using edge-tts (requires internet)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    try:
        asyncio.run(edge_tts.Communicate(text, TTS_VOICE).save(tmp.name))
        if os.path.getsize(tmp.name) > 0:
            pygame.mixer.music.load(tmp.name)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.wait(50)
    except Exception:
        pass
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def speak(text: str, prefetch_next: bool = False):
    """Speak text aloud using Piper TTS (offline), falling back to edge-tts.

    If prefetch_next=True, starts pre-arming the mic in a background thread
    partway through playback so the next listen() call starts faster.
    """
    print(text)
    try:
        voice = _get_piper_voice()
        buf = _io.BytesIO()
        with wave.open(buf, "wb") as wf:
            voice.synthesize(text, wf)
        buf.seek(0)
        sound = pygame.mixer.Sound(buf)
        sound.play()

        # Start mic pre-fetch partway through playback for overlap
        prefetch_thread = None
        if prefetch_next:
            duration_ms = int(sound.get_length() * 1000)
            warmup_delay = max(0, duration_ms - 600) / 1000.0
            def _delayed_prefetch():
                time.sleep(warmup_delay)
                _prefetch_mic()
            prefetch_thread = threading.Thread(target=_delayed_prefetch, daemon=True)
            prefetch_thread.start()

        while pygame.mixer.get_busy():
            pygame.time.wait(50)

        if prefetch_thread is not None:
            prefetch_thread.join(timeout=2)

    except Exception:
        # Piper unavailable — fall back to edge-tts
        _speak_edge_tts(text)


def listen(timeout=5, phrase_limit=10) -> str | None:
    """Listen from mic and return transcribed text using Faster-Whisper.

    Drains any pre-fetched mic frames first (from parallel TTS/STT overlap)
    then records the remainder fresh.
    """
    try:
        import pyaudio

        # Audio parameters for CUDA-optimized recording
        CHUNK = 2048
        FORMAT = pyaudio.paFloat32
        CHANNELS = 1
        RATE = 16000

        # Drain pre-fetched frames if available (from _prefetch_mic)
        with _prefetch_lock:
            frames = list(_prefetch_frames)
            _prefetch_frames.clear()

        p = pyaudio.PyAudio()
        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK
        )

        # Record the remaining chunks (subtract already-buffered frames)
        total_chunks = int(RATE / CHUNK * min(timeout, phrase_limit))
        remaining = max(0, total_chunks - len(frames))

        for _ in range(remaining):
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(np.frombuffer(data, dtype=np.float32))

        stream.stop_stream()
        stream.close()
        p.terminate()

        # Convert to numpy array and transcribe with Whisper
        audio_data = np.concatenate(frames) if frames else np.array([])

        if len(audio_data) == 0:
            return None

        # Use faster-whisper for transcription (handles accented English well)
        model = _get_whisper_model()
        segments, info = model.transcribe(
            audio_data,
            language="en",
            beam_size=1,   # greedy — 2-3x faster, negligible quality loss for short commands
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500)
        )

        text = " ".join([segment.text for segment in segments])
        return text.lower().strip() if text else None

    except Exception as e:
        return None


def ask_claude(user_input: str) -> str:
    """Send message to Ollama and get response, with tool calling support."""
    conversation_history.append({"role": "user", "content": user_input})

    try:
        # Prepare messages with system prompt
        messages = [{"role": "user", "content": SYSTEM_PROMPT + "\n\n" + conversation_history[0]["content"]}]
        messages.extend(conversation_history[1:])

        response = client.chat.completions.create(
            model=OLLAMA_MODEL,
            max_tokens=256,
            messages=messages,
            temperature=0.4,
        )

        # Get the response
        reply = response.choices[0].message.content.strip()

        # Handle empty responses (sometimes reasoning models skip the response)
        if not reply:
            reply = "Got it. What else can I help with?"

        # Check for JSON tool calls (parse each line)
        results = []
        for line in reply.split('\n'):
            line = line.strip()
            if line.startswith('{') and '"tool"' in line:
                try:
                    tool_call = json.loads(line.rstrip(','))
                    tool_name = tool_call.get("tool")
                    tool_args = tool_call.get("args", {})

                    # Dispatch only known tools (allowlist) with a validated
                    # arg shape — a malformed call is rejected, never executed.
                    if tool_name in TOOL_DISPATCH:
                        ok, reason = _validate_tool_args(tool_name, tool_args)
                        if not ok:
                            print(f"[aria] rejected tool call {tool_name!r}: {reason}",
                                  file=sys.stderr)
                            results.append(f"Rejected tool call '{tool_name}': {reason}")
                        else:
                            result = TOOL_DISPATCH[tool_name](**tool_args)
                            results.append(result)
                    else:
                        results.append(f"Unknown tool: {tool_name}")
                except (json.JSONDecodeError, ValueError, TypeError):
                    pass

        if results:
            # All tools executed
            final_result = " ".join(results)
            conversation_history.append({"role": "assistant", "content": final_result})
            return final_result
        else:
            # Normal response (no tools detected)
            conversation_history.append({"role": "assistant", "content": reply})
            return reply

    except Exception as e:
        error_msg = f"Error: {str(e)[:80]}"
        conversation_history.append({"role": "assistant", "content": error_msg})
        return error_msg


def print_banner():
    """Display ARIA banner on startup."""
    banner = """
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║        ⚡ ARIA - Advanced Responsive Intelligent Assistant ⚡ ║
║                                                               ║
║            🎤 Voice Mode | 📝 Text Mode | 🚀 Fast            ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
"""
    print(banner)


def text_mode():
    """Fallback text input mode."""
    print_banner()
    speak("Online. How can I help?")

    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue

            # Check for mode switching commands
            if user_input.lower() in ("voice", "voice mode", "activate voice", "mic", "microphone", "switch to voice"):
                speak("Activating voice mode.")
                voice_mode()
                speak("Back to text mode. How can I help?")
                continue

            if user_input.lower() in ("exit", "quit", "bye", "shutdown"):
                speak("Goodbye.")
                break

            reply = ask_claude(user_input)
            speak(reply)

        except KeyboardInterrupt:
            speak("Goodbye.")
            break


def voice_mode():
    """Full voice interaction mode with OpenWakeWord detection."""
    print_banner()

    # Pre-warm Whisper in background while OWW initializes
    threading.Thread(target=_get_whisper_model, daemon=True).start()

    # Lazily initialize OpenWakeWord on first voice_mode call
    init_openwakeword()

    if oww_model is None:
        speak("Error: OpenWakeWord not initialized.")
        return

    speak("Online. Listening for wake word...")

    try:
        import pyaudio

        CHUNK = 1280  # OpenWakeWord works best with 1280 samples at 16kHz
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 16000

        p = pyaudio.PyAudio()
        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK
        )

        while True:
            try:
                # Listen continuously for wake word
                pcm = stream.read(CHUNK)
                pcm_array = np.frombuffer(pcm, dtype=np.int16)

                # Convert int16 to float32 (-1.0 to 1.0)
                audio_float32 = pcm_array.astype(np.float32) / 32768.0

                # Process audio for wake word detection
                prediction = oww_model.predict(audio_float32)

                # Check if wake word was detected with sufficient confidence
                if prediction.get(WAKE_WORD_MODEL, 0) >= WAKE_WORD_THRESHOLD:
                    # Wake word detected
                    speak("Yes?")

                    # Listen for actual command
                    command = listen(timeout=6, phrase_limit=15)
                    if not command:
                        speak("Didn't catch that.")
                        continue

                    if any(word in command for word in ["shutdown", "goodbye", "bye", "exit"]):
                        speak("Goodbye.")
                        break

                    reply = ask_claude(command)
                    speak(reply, prefetch_next=True)

            except KeyboardInterrupt:
                speak("Goodbye.")
                break

        stream.stop_stream()
        stream.close()
        p.terminate()

    except KeyboardInterrupt:
        speak("Goodbye.")
    except Exception as e:
        speak(f"Error in voice mode: {e}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    # Check for --text flag or mic availability
    if "--text" in sys.argv:
        text_mode()
    else:
        try:
            # Quick mic test with PyAudio
            import pyaudio
            p = pyaudio.PyAudio()
            p.get_default_input_device_info()
            p.terminate()
            voice_mode()
        except Exception:
            text_mode()
