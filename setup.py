#!/usr/bin/env python3
"""
ARIA Interactive Configuration Wizard

Run once after setup.sh to configure credentials and personal settings.
Writes .env and data/persona.json.

Usage:
    python3 setup.py
"""

import getpass
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

# ── Optional: requests for Ollama API fallback ────────────────────────────────
try:
    import urllib.request as _urllib_req
    import urllib.error as _urllib_err
    _HAS_URLLIB = True
except ImportError:
    _HAS_URLLIB = False

ROOT        = Path(__file__).resolve().parent
ENV_FILE    = ROOT / ".env"
PERSONA_FILE = ROOT / "data" / "persona.json"

# ─────────────────────────────────────────────────────────────────────────────
# UI helpers
# ─────────────────────────────────────────────────────────────────────────────

BOLD  = "\033[1m"
CYAN  = "\033[0;36m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED   = "\033[0;31m"
DIM   = "\033[2m"
NC    = "\033[0m"

def _c(code: str, text: str) -> str:
    """Wrap text in ANSI colour if stdout is a tty."""
    if sys.stdout.isatty():
        return f"{code}{text}{NC}"
    return text


def banner() -> None:
    print(_c(BOLD + CYAN, """
  ╔══════════════════════════════════════════════════════╗
  ║         ARIA — Configuration Wizard                 ║
  ╚══════════════════════════════════════════════════════╝
"""))


def section(title: str) -> None:
    print(_c(BOLD, f"\n── {title} " + "─" * max(0, 50 - len(title))))


def ok(msg: str) -> None:
    print(f"  {_c(GREEN, '[OK]')}    {msg}")


def info(msg: str) -> None:
    print(f"  {_c(CYAN, '[INFO]')}  {msg}")


def warn(msg: str) -> None:
    print(f"  {_c(YELLOW, '[WARN]')}  {msg}")


def ask(prompt: str, default: str | None = None, password: bool = False) -> str:
    """Prompt the user and return the answer (stripped). Uses default if blank."""
    if default is not None:
        label = f"  {prompt} {_c(DIM, f'[{default}]')}: "
    else:
        label = f"  {prompt}: "
    try:
        val = (getpass.getpass(label) if password else input(label)).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise
    return val if val else (default or "")


def ask_yn(prompt: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = ask(f"{prompt} ({hint})", default="y" if default else "n")
    return raw.lower() in ("y", "yes")


# ─────────────────────────────────────────────────────────────────────────────
# Ollama helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ollama_models_via_cli() -> list[str]:
    """Return model names from `ollama list`, or [] on failure."""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=6,
        )
        if result.returncode != 0:
            return []
        lines = result.stdout.strip().splitlines()
        models = []
        for line in lines[1:]:            # skip header row
            name = line.split()[0] if line.split() else ""
            if name and name != "NAME":
                models.append(name)
        return models
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []


def _ollama_models_via_api(base_url: str) -> list[str]:
    """Return model names from the Ollama /api/tags endpoint, or [] on failure."""
    if not _HAS_URLLIB:
        return []
    # base_url may be http://127.0.0.1:11434/v1 — strip the /v1
    api_root = base_url.rstrip("/").removesuffix("/v1")
    url = f"{api_root}/api/tags"
    try:
        req = _urllib_req.Request(url, headers={"Accept": "application/json"})
        with _urllib_req.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def get_ollama_models(base_url: str) -> list[str]:
    """Try CLI first, then API. Return sorted unique list."""
    models = _ollama_models_via_cli() or _ollama_models_via_api(base_url)
    seen: set[str] = set()
    out: list[str] = []
    for m in models:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def pick_model(models: list[str], prompt: str) -> str:
    """Interactive numbered picker. Returns selected model name."""
    print()
    for i, name in enumerate(models, 1):
        print(f"    {_c(CYAN, str(i))}.  {name}")
    print(f"    {_c(DIM, '0.  Enter a different model name')}")

    while True:
        raw = ask(f"{prompt} (number or name)").strip()
        if raw.isdigit():
            idx = int(raw)
            if idx == 0:
                custom = ask("Model name").strip()
                if custom:
                    return custom
            elif 1 <= idx <= len(models):
                return models[idx - 1]
            else:
                warn(f"Enter a number between 0 and {len(models)}.")
        elif raw:
            return raw
        else:
            warn("Please select a number or type a model name.")


# ─────────────────────────────────────────────────────────────────────────────
# .env writer
# ─────────────────────────────────────────────────────────────────────────────

def write_env(cfg: dict[str, str]) -> None:
    lines = [
        "# ARIA — generated by setup.py",
        "# Edit this file to update your configuration.",
        "",
        "# ── Authentication ──────────────────────────────────────",
        f"ARIA_PASSWORD={cfg['ARIA_PASSWORD']}",
        f"SECRET_KEY={cfg['SECRET_KEY']}",
        "",
        "# ── Ollama (local LLM) ──────────────────────────────────",
        f"OLLAMA_URL={cfg['OLLAMA_URL']}",
        f"OLLAMA_MODEL={cfg['OLLAMA_MODEL']}",
        f"OLLAMA_VISION_MODEL={cfg['OLLAMA_VISION_MODEL']}",
        "",
        "# ── Spotify (optional) ──────────────────────────────────",
        f"SPOTIPY_CLIENT_ID={cfg['SPOTIPY_CLIENT_ID']}",
        f"SPOTIPY_CLIENT_SECRET={cfg['SPOTIPY_CLIENT_SECRET']}",
        f"SPOTIPY_REDIRECT_URI={cfg['SPOTIPY_REDIRECT_URI']}",
        "",
        "# ── Behaviour ───────────────────────────────────────────",
        f"ARIA_SILENT_MODE={cfg['ARIA_SILENT_MODE']}",
        "FLASK_DEBUG=0",
    ]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# persona.json writer
# ─────────────────────────────────────────────────────────────────────────────

def write_persona(name: str) -> None:
    PERSONA_FILE.parent.mkdir(parents=True, exist_ok=True)

    if PERSONA_FILE.exists():
        try:
            persona = json.loads(PERSONA_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            persona = {}
    else:
        persona = {}

    persona.setdefault("user", {})["name"] = name
    persona.setdefault("aria", {
        "personality": "direct, no fluff, slightly sarcastic",
        "opinions": {"linux": "superior", "windows": "tolerated"},
        "last_reflection": None,
        "reflection_message_count": 0,
    })
    persona.setdefault("meta", {
        "first_seen": None,
        "last_seen": None,
        "total_sessions": 0,
    })

    # Ensure required user sub-keys exist
    user = persona["user"]
    user.setdefault("session_times", {"morning": 0, "afternoon": 0, "evening": 0, "late_night": 0})
    user.setdefault("music_history", [])
    user.setdefault("apps_used", {})
    user.setdefault("topics", {})
    user.setdefault("message_count", 0)

    PERSONA_FILE.write_text(json.dumps(persona, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    banner()

    # ── Overwrite check ───────────────────────────────────────────────────────
    if ENV_FILE.exists():
        warn(".env already exists.")
        if not ask_yn("  Overwrite it with new settings?", default=False):
            info("Keeping existing .env. Exiting.")
            sys.exit(0)
        print()

    cfg: dict[str, str] = {}

    # ── Personal ──────────────────────────────────────────────────────────────
    section("Personal")
    print("  ARIA will use your name to address you.\n")
    name = ask("Your name", default="User")

    # ── Ollama ────────────────────────────────────────────────────────────────
    section("Ollama")
    print("  ARIA runs entirely on local models via Ollama.")
    print(f"  {_c(DIM, 'Install at: https://ollama.com — then run: ollama serve')}\n")

    ollama_url = ask("Ollama base URL", default="http://127.0.0.1:11434/v1")
    cfg["OLLAMA_URL"] = ollama_url

    info("Checking for installed models...")
    models = get_ollama_models(ollama_url)

    if models:
        ok(f"Found {len(models)} model(s).")
        cfg["OLLAMA_MODEL"] = pick_model(models, "Main chat model")
        print()
        if ask_yn("Configure a separate vision/multimodal model?", default=False):
            cfg["OLLAMA_VISION_MODEL"] = pick_model(models, "Vision model")
        else:
            cfg["OLLAMA_VISION_MODEL"] = cfg["OLLAMA_MODEL"]
    else:
        warn("Could not reach Ollama or no models installed.")
        print(f"  {_c(DIM, 'Start Ollama with: ollama serve')}")
        print(f"  {_c(DIM, 'Pull a model with: ollama pull qwen2.5:14b')}\n")
        cfg["OLLAMA_MODEL"] = ask("Main chat model name", default="qwen2.5:14b")
        cfg["OLLAMA_VISION_MODEL"] = ask(
            "Vision model name (or same as above)",
            default=cfg["OLLAMA_MODEL"],
        )

    # ── Web UI auth ───────────────────────────────────────────────────────────
    section("Web UI")
    print("  Set a password to protect the ARIA web interface.")
    print(f"  {_c(DIM, 'Leave blank to disable authentication (local-only use).')}\n")

    password = getpass.getpass("  Web UI password (blank = no auth): ").strip()
    cfg["ARIA_PASSWORD"] = password
    cfg["SECRET_KEY"] = secrets.token_hex(32)

    if not password:
        warn("No password set — ARIA web UI will be open to anyone on the network.")

    # ── Spotify ───────────────────────────────────────────────────────────────
    section("Spotify  (optional)")
    print("  ARIA can control Spotify playback and read now-playing info.")
    print(f"  {_c(DIM, 'Get credentials from: https://developer.spotify.com/dashboard')}\n")

    if ask_yn("Set up Spotify integration?", default=False):
        cfg["SPOTIPY_CLIENT_ID"]     = ask("Spotify Client ID")
        cfg["SPOTIPY_CLIENT_SECRET"] = ask("Spotify Client Secret", password=True)
        cfg["SPOTIPY_REDIRECT_URI"]  = ask(
            "Redirect URI",
            default="http://127.0.0.1:8888/callback",
        )
        info("After setup, run once: python3 scripts/spotify_auth.py")
    else:
        cfg["SPOTIPY_CLIENT_ID"]     = ""
        cfg["SPOTIPY_CLIENT_SECRET"] = ""
        cfg["SPOTIPY_REDIRECT_URI"]  = "http://127.0.0.1:8888/callback"

    # ── Behaviour ─────────────────────────────────────────────────────────────
    section("Behaviour")
    silent = ask_yn(
        "Disable ARIA's proactive messages (time-based check-ins)?",
        default=False,
    )
    cfg["ARIA_SILENT_MODE"] = "1" if silent else "0"

    # ── Write files ───────────────────────────────────────────────────────────
    section("Writing configuration")

    write_env(cfg)
    ok(f".env written to {ENV_FILE}")

    write_persona(name)
    ok(f"persona.json updated — ARIA will call you '{name}'")

    # ── Done ──────────────────────────────────────────────────────────────────
    print(_c(BOLD + GREEN, """
  ╔══════════════════════════════════════════════════════╗
  ║              Setup complete!                        ║
  ╚══════════════════════════════════════════════════════╝
"""))

    print("  To start ARIA:\n")
    print(f"    {_c(CYAN, 'Web UI (browser):  ')}  bash run-web.sh")
    print(f"    {_c(CYAN, 'Desktop window:    ')}  python3 launch.py")
    print(f"    {_c(CYAN, 'Voice only:        ')}  python3 aria.py")
    print(f"    {_c(CYAN, 'Text only:         ')}  python3 aria.py --text")

    if cfg.get("SPOTIPY_CLIENT_ID"):
        print(f"\n  {_c(YELLOW, 'Spotify:')} run python3 scripts/spotify_auth.py to authorise.")

    if not cfg["ARIA_PASSWORD"]:
        print(f"\n  {_c(YELLOW, 'Tip:')} Add ARIA_PASSWORD to .env before exposing to a network.")

    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSetup cancelled.")
        sys.exit(1)
