#!/usr/bin/env python3
"""
ARIA - Advanced Responsive Intelligent Assistant
Powered by Ollama + Faster-Whisper (CUDA) + OpenWakeWord + TTS
"""

import os
import sys
import time
import threading

# Suppress ALSA/JACK warnings on Linux (cosmetic noise from audio backend probing)
os.environ["PYTHONWARNINGS"] = "ignore"
os.environ["SDL_AUDIODRIVER"] = "pulseaudio"
os.environ["JACK_NO_START_SERVER"] = "1"
os.environ["JACK_NO_AUDIO_RESERVATION"] = "1"
import ctypes
ERROR_HANDLER_FUNC = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_int,
                                       ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p)
def _alsa_error_handler(filename, line, function, err, fmt):
    pass
_c_alsa_error_handler = ERROR_HANDLER_FUNC(_alsa_error_handler)
try:
    asound = ctypes.cdll.LoadLibrary("libasound.so.2")
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

# Faster-Whisper model (medium model for accuracy with accented English + CUDA support)
WHISPER_MODEL = "medium"

SYSTEM_PROMPT = """You are ARIA. Respond in 1-2 sentences. No filler.

For tools, reply ONLY with JSON:
{"tool":"open_app","args":{"app_name":"brave|spotify|terminal|vscode|files"}}
{"tool":"open_url","args":{"url":"https://..."}}
{"tool":"search_web","args":{"query":"..."}}
{"tool":"play_on_spotify","args":{"query":"..."}}

Non-tool questions: plain text only, 1-2 sentences."""

# ─────────────────────────────────────────────
# APP MAPPING
# ─────────────────────────────────────────────
APP_MAP = {
    "brave": "brave-browser",
    "firefox": "firefox",
    "chrome": "google-chrome",
    "google chrome": "google-chrome",
    "spotify": "spotify",
    "vscode": "code",
    "vs code": "code",
    "code": "code",
    "terminal": "gnome-terminal",
    "term": "gnome-terminal",
    "files": "nautilus",
    "file manager": "nautilus",
    "nautilus": "nautilus",
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
        print("Loading Faster-Whisper (medium/CUDA)...", file=sys.stderr)
        try:
            whisper_model = WhisperModel(WHISPER_MODEL, device="cuda", compute_type="float16")
        except Exception:
            whisper_model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
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
    """Launch a desktop application."""
    try:
        # Normalize app name to lowercase
        app_name_normalized = app_name.lower().strip()

        # Look up the actual command
        cmd = APP_MAP.get(app_name_normalized, app_name_normalized)

        # Launch the app
        subprocess.Popen([cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Launching {app_name}..."
    except FileNotFoundError:
        return f"Application '{app_name}' not found on this system."
    except Exception as e:
        return f"Error launching {app_name}: {e}"


def run_open_url(url: str, browser: str = "default") -> str:
    """Open a URL in a specific browser or default application."""
    try:
        # Add https:// if no protocol specified
        if not url.startswith(("http://", "https://", "file://")):
            url = "https://" + url

        if browser.lower() == "default":
            # Use default application
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # Open in specific browser
            browser_normalized = browser.lower().strip()
            browser_cmd = APP_MAP.get(browser_normalized, browser_normalized)
            subprocess.Popen([browser_cmd, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
        # Use Spotify URI scheme for search
        spotify_uri = f"spotify:search:{query.replace(' ', '%20')}"
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


# ─────────────────────────────────────────────
# PIPER TTS (fully offline)
# ─────────────────────────────────────────────
PIPER_MODEL_DIR = "data/piper"
PIPER_MODEL_NAME = "en_US-lessac-medium"
PIPER_MODEL_PATH = f"{PIPER_MODEL_DIR}/{PIPER_MODEL_NAME}.onnx"
PIPER_CONFIG_PATH = f"{PIPER_MODEL_DIR}/{PIPER_MODEL_NAME}.onnx.json"
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

                    # Execute the tool
                    if tool_name in TOOL_DISPATCH:
                        result = TOOL_DISPATCH[tool_name](**tool_args)
                        results.append(result)
                    else:
                        results.append(f"Unknown tool: {tool_name}")
                except (json.JSONDecodeError, ValueError):
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
