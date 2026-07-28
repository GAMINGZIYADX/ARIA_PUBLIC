#!/usr/bin/env python3
"""
ARIA Desktop Launcher — wraps the Flask web UI in a native PyWebView window.

Usage:
    python3 launch.py          # start normally
    python3 launch.py --port 5001   # override port (default: 5000)
"""

# ── Set process name + WM_CLASS to "ARIA" before any other import ──────────
# Must happen first so /proc/self/comm, GDK, and GTK all see the right name.
import os as _os
import sys as _sys
# X11/GTK WM_CLASS — only meaningful on Linux (GTK/X11/Wayland)
if _sys.platform not in ("win32", "darwin"):
    _os.environ.setdefault("RESOURCE_NAME", "ARIA")
    _os.environ.setdefault("GDK_PROGRAM_CLASS", "ARIA")

try:
    import setproctitle
    setproctitle.setproctitle("ARIA")
except ImportError:
    try:
        import ctypes
        ctypes.CDLL(None).prctl(15, b"ARIA", 0, 0, 0)
    except Exception:
        pass  # Non-Linux or prctl unavailable — graceful fallback

import os
import sys
import time
import signal
import argparse
import threading
import urllib.request
import urllib.error

# ── Locate project root so relative imports work regardless of cwd ──
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ── CLI args ────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="ARIA desktop launcher")
parser.add_argument("--port", type=int, default=5000, help="Flask port (default: 5000)")
args = parser.parse_args()

PORT = args.port
URL  = f"http://127.0.0.1:{PORT}"
ICON = os.path.join(ROOT, "static", "aria_icon.png")

# ── Flask in a daemon thread ─────────────────────────────────────────
_flask_started = threading.Event()
_flask_app = None   # holds the Flask app object after import


def _run_flask():
    global _flask_app
    os.environ.setdefault("FLASK_DEBUG", "0")
    # Silence Werkzeug startup/request noise
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    from app import app
    _flask_app = app
    _flask_started.set()
    try:
        app.run(
            host="127.0.0.1",
            port=PORT,
            debug=False,
            use_reloader=False,
            threaded=True,
        )
    except OSError as e:
        # Port already in use — another instance of Flask is running.
        # The poller will find it and the window will attach to it.
        print(f"[launcher] Flask could not bind port {PORT}: {e}", file=sys.stderr)
        print(f"[launcher] Attaching to existing server at {URL}", file=sys.stderr)


flask_thread = threading.Thread(target=_run_flask, name="flask", daemon=True)
flask_thread.start()

# Wait for the import to finish before polling (avoids a race during heavy import)
_flask_started.wait(timeout=30)


# ── Poll until Flask is accepting connections ────────────────────────
def _wait_for_flask(timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(URL + "/login", timeout=1)
            return True
        except urllib.error.HTTPError:
            return True   # any HTTP response means Flask is up
        except Exception:
            time.sleep(0.15)
    return False


print("Starting ARIA...", flush=True)
if not _wait_for_flask():
    print("ERROR: Flask did not start within 30 seconds.", file=sys.stderr)
    sys.exit(1)

print(f"Flask ready at {URL}", flush=True)

# ── PyWebView window ─────────────────────────────────────────────────
try:
    import webview  # noqa: E402  (import after Flask is ready to avoid GTK/Qt init race)
except ImportError:
    # pywebview is optional and not in the default requirements. Flask is
    # already serving at this point, so fall back to browser mode rather than
    # exiting and taking the running server down with us.
    print(
        "\nNote: pywebview is not installed, so there is no native window.\n"
        "ARIA is running in your browser instead:\n"
        f"\n    {URL}\n\n"
        "For the desktop window:  pip install -r requirements-desktop.txt\n"
        "Press Ctrl+C to stop.\n",
        file=sys.stderr,
        flush=True,
    )
    try:
        flask_thread.join()
    except KeyboardInterrupt:
        pass
    sys.exit(0)

# Clean shutdown: destroy the window when the process is killed
def _on_signal(sig, frame):
    for w in webview.windows:
        w.destroy()

signal.signal(signal.SIGINT,  _on_signal)
signal.signal(signal.SIGTERM, _on_signal)


def _on_closed():
    """Called by pywebview on the main thread when the window is closed."""
    # Flask thread is daemon — it dies automatically when main thread exits.
    # Give it a moment to flush any pending writes before the process exits.
    time.sleep(0.3)
    os._exit(0)


window = webview.create_window(
    title="ARIA",
    url=URL,
    width=1280,
    height=820,
    resizable=True,
    frameless=False,
    easy_drag=False,
)

window.events.closed += _on_closed


def _fix_wm_class():
    """
    After the window appears, try to rename its WM_CLASS via wmctrl (X11)
    or xdotool as a belt-and-suspenders fallback.  Runs in a background
    thread so it doesn't block the GTK main loop.
    Linux/X11 only — no-op on Windows and macOS.
    """
    if sys.platform != "linux":
        return
    import subprocess as _sp
    time.sleep(2)   # wait for the window to be mapped
    pid = os.getpid()
    try:
        _sp.run(
            ["wmctrl", "-i", "-r",
             f":ACTIVE:",
             "-T", "ARIA"],
            timeout=3, capture_output=True
        )
    except Exception:
        pass
    try:
        result = _sp.run(
            ["xdotool", "search", "--pid", str(pid), "--name", "ARIA"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            for wid in result.stdout.strip().splitlines():
                _sp.run(
                    ["xdotool", "set_window", "--classname", "ARIA",
                     "--class", "ARIA", wid],
                    timeout=3, capture_output=True
                )
    except Exception:
        pass


threading.Thread(target=_fix_wm_class, daemon=True, name="wm-class-fix").start()

# Pass the icon path on platforms that support it (Linux/Windows).
# pywebview silently ignores it on macOS (use the .app bundle instead).
icon_kwargs = {}
if os.path.exists(ICON):
    icon_kwargs["icon"] = ICON

# storage_path: persistent WebKit profile so camera permissions survive restarts.
# private_mode=False: required for getUserMedia — ephemeral contexts block camera.
STORAGE = os.path.join(ROOT, "data", "webview_profile")
os.makedirs(STORAGE, exist_ok=True)

webview.start(
    private_mode=False,
    storage_path=STORAGE,
    **icon_kwargs,
)
