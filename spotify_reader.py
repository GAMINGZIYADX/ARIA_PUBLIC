"""
ARIA Spotify Reader — playback control and currently-playing queries.

Playback strategy (play_search):
  1. Spotipy Web API — search for track → start_playback with exact track URI
     Requires SPOTIPY_CLIENT_ID + SPOTIPY_CLIENT_SECRET + one-time OAuth auth.
     Token is cached in data/.spotify_cache and auto-refreshed on subsequent runs.
  2. xdg-open spotify:track:URI — if spotipy found the track but start_playback failed
     (e.g. no active device).  Opens Spotify and plays the track directly.
  3. xdg-open spotify:search:QUERY — last resort; opens Spotify search page.

Now-playing query strategy:
  1. playerctl (dbus wrapper) — works with Spotify Flatpak/Snap/native
  2. dbus-send directly — fallback if playerctl is missing
  3. Spotify Web API — if SPOTIFY_TOKEN env var is set

Pause / next / prev always use dbus (MPRIS).
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
import urllib.error
from typing import Any


# ── low-level helpers ─────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 3) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return -1, ""


def _run_logged(cmd: list[str], timeout: int = 4) -> tuple[int, str, str]:
    """Like _run but also returns stderr."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -1, "", f"command not found: {cmd[0]}"
    except OSError as e:
        return -1, "", str(e)


# ── Spotipy client (Option 1) ─────────────────────────────────────────────────

_sp_client = None   # cached after first successful init
_sp_client_tried = False


def _get_spotify_client():
    """
    Return a cached spotipy.Spotify client, or None if not configured.

    Credentials are read from env vars (set in .env or shell):
      SPOTIPY_CLIENT_ID     — from Spotify Developer Dashboard
      SPOTIPY_CLIENT_SECRET — from Spotify Developer Dashboard
      SPOTIPY_REDIRECT_URI  — default: http://127.0.0.1:8888/callback
                             NOTE: Spotify banned 'localhost' as a hostname on
                             April 9 2025. Use 127.0.0.1, not localhost.

    Token is cached in data/.spotify_cache so auth is only needed once.
    Run scripts/spotify_auth.py once to perform the first-time OAuth dance.
    """
    global _sp_client, _sp_client_tried
    if _sp_client_tried:
        return _sp_client
    _sp_client_tried = True

    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError:
        import sys
        print("[spotify] spotipy not installed — run: pip install spotipy", file=sys.stderr)
        return None

    client_id     = os.environ.get("SPOTIPY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SPOTIPY_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        import sys
        print("[spotify] SPOTIPY_CLIENT_ID / SPOTIPY_CLIENT_SECRET not set", file=sys.stderr)
        return None

    cache_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", ".spotify_cache"
    )
    redirect_uri = os.environ.get("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

    try:
        auth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=(
                "user-read-playback-state "
                "user-modify-playback-state "
                "user-read-currently-playing"
            ),
            cache_path=cache_path,
            open_browser=False,
        )
        # Will raise if there's no cached token (user hasn't authed yet)
        token = auth.get_cached_token()
        if not token:
            import sys
            print(
                "[spotify] No cached OAuth token — run scripts/spotify_auth.py once to authorise",
                file=sys.stderr,
            )
            return None

        _sp_client = spotipy.Spotify(auth_manager=auth)
        return _sp_client
    except Exception as e:
        import sys
        print(f"[spotify] spotipy init error: {e}", file=sys.stderr)
        return None


def _play_via_spotipy(query: str, title: str = "", artist: str = "") -> tuple[bool, str | None]:
    """
    Search for query via Spotify Web API and start playback.
    Returns (success, track_uri_or_None).
    track_uri is returned even on playback failure so the caller can fall
    back to xdg-open with the exact track URI.

    If title and artist are provided, tries structured search first
    (track:TITLE artist:ARTIST) then falls back to the raw query.
    """
    import sys
    sp = _get_spotify_client()
    if sp is None:
        return False, None

    # ── search ────────────────────────────────────────────────────────────────
    def _search(q: str) -> list:
        print(f"[spotify] search query: {q!r}", file=sys.stderr)
        try:
            results = sp.search(q=q, type="track", limit=1)
            return (results.get("tracks") or {}).get("items", [])
        except Exception as e:
            print(f"[spotify] spotipy search error: {e}", file=sys.stderr)
            return []

    tracks: list = []
    if title and artist:
        # Structured query — most precise
        tracks = _search(f"track:{title} artist:{artist}")
    if not tracks and title and artist:
        # Unstructured fallback — handles typos / alternate spellings
        tracks = _search(f"{title} {artist}")
    if not tracks:
        # Last resort — use whatever raw query was passed in
        tracks = _search(query)

    if not tracks:
        print(f"[spotify] spotipy: no results for {query!r}", file=sys.stderr)
        return False, None

    track      = tracks[0]
    track_uri  = track["uri"]
    track_name = track.get("name", "")
    artist     = (track.get("artists") or [{}])[0].get("name", "")
    print(f"[spotify] spotipy found: {track_name!r} by {artist!r} → {track_uri}", file=sys.stderr)

    # ── start_playback ────────────────────────────────────────────────────────
    try:
        # If there's an active device (Spotify is open) this plays immediately.
        # Pass device_id=None so Spotify chooses the active device automatically.
        sp.start_playback(uris=[track_uri])
        print(f"[spotify] spotipy start_playback accepted", file=sys.stderr)
        return True, track_uri
    except Exception as e:
        print(f"[spotify] spotipy start_playback failed: {e} — will try xdg-open", file=sys.stderr)
        return False, track_uri   # caller can use the URI with xdg-open


def _play_via_xdg_open(uri: str) -> bool:
    """
    Open a spotify: URI via xdg-open.
    Works for both spotify:track:XXX (plays immediately) and
    spotify:search:QUERY (opens search results).
    Returns True if the command launched without an immediate error.
    """
    import sys
    try:
        proc = subprocess.Popen(
            ["xdg-open", uri],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            _, err = proc.communicate(timeout=2)
            if proc.returncode not in (None, 0):
                print(
                    f"[spotify] xdg-open failed rc={proc.returncode} "
                    f"err={err.decode(errors='replace')!r}",
                    file=sys.stderr,
                )
                return False
        except subprocess.TimeoutExpired:
            pass  # still running — normal for a UI app
        print(f"[spotify] xdg-open launched: {uri}", file=sys.stderr)
        return True
    except FileNotFoundError:
        print("[spotify] xdg-open not found", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[spotify] xdg-open error: {e}", file=sys.stderr)
        return False


def play_search(query: str, title: str = "", artist: str = "") -> bool:
    """
    Play the track best matching query.  Returns True if a play command was sent.

    Pass title and artist separately when available — the structured
    Spotify field operators (track: artist:) are far more precise than
    a plain free-text query.

    Strategy:
      1. Spotipy: structured search (track:TITLE artist:ARTIST) → start_playback
      2. Spotipy: unstructured search (TITLE ARTIST) → start_playback
      3. xdg-open spotify:track:URI  (if search found the track but API playback failed)
      4. xdg-open spotify:search:QUERY  (if search itself failed)
    """
    import sys

    ok, track_uri = _play_via_spotipy(query, title=title, artist=artist)
    if ok:
        return True

    if track_uri:
        # We found the exact track but start_playback failed — open it directly
        print(f"[spotify] falling back to xdg-open with track URI", file=sys.stderr)
        return _play_via_xdg_open(track_uri)

    # No API result at all — fall back to search URI
    safe = query.replace(" ", "%20")
    print(f"[spotify] falling back to xdg-open with search URI", file=sys.stderr)
    return _play_via_xdg_open(f"spotify:search:{safe}")


# ── Playback control via dbus (pause / skip) ──────────────────────────────────

_SPOTIFY_DEST = "org.mpris.MediaPlayer2.spotify"
_SPOTIFY_OBJ  = "/org/mpris/MediaPlayer2"
_PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"


def _dbus_call(method: str, *extra_args: str) -> bool:
    cmd = [
        "dbus-send", "--print-reply",
        f"--dest={_SPOTIFY_DEST}",
        _SPOTIFY_OBJ,
        f"{_PLAYER_IFACE}.{method}",
        *extra_args,
    ]
    rc, _ = _run(cmd, timeout=4)
    return rc == 0


def pause() -> bool:
    return _dbus_call("PlayPause")


def next_track() -> bool:
    return _dbus_call("Next")


def previous_track() -> bool:
    return _dbus_call("Previous")


# ── Now-playing query ─────────────────────────────────────────────────────────

def _via_playerctl() -> dict[str, Any] | None:
    rc, players = _run(["playerctl", "-l"])
    if rc != 0:
        return None
    player_name: str | None = None
    for line in players.splitlines():
        if "spotify" in line.lower():
            player_name = line.strip()
            break
    if not player_name:
        return None

    rc, status = _run(["playerctl", "-p", player_name, "status"])
    if rc != 0:
        return None
    playing = status.lower() == "playing"

    def _meta(field: str) -> str:
        _, val = _run(["playerctl", "-p", player_name, "metadata", field])
        return val

    title  = _meta("title")
    artist = _meta("artist")
    album  = _meta("album")
    if not title:
        return None
    return {"title": title, "artist": artist, "album": album, "playing": playing, "source": "playerctl"}


def _via_dbus() -> dict[str, Any] | None:
    rc, out = _run([
        "dbus-send", "--print-reply", "--dest=org.mpris.MediaPlayer2.spotify",
        "/org/mpris/MediaPlayer2",
        "org.freedesktop.DBus.Properties.Get",
        "string:org.mpris.MediaPlayer2.Player",
        "string:Metadata",
    ])
    if rc != 0 or not out:
        return None

    import re
    def _extract(key: str) -> str:
        m = re.search(
            rf'string\s+"{re.escape(key)}"\s*\n\s*variant\s+array\s*\[\s*\n\s*string\s+"([^"]+)"',
            out,
        )
        if m:
            return m.group(1)
        m2 = re.search(
            rf'string\s+"{re.escape(key)}"\s*\n\s*variant\s+string\s+"([^"]+)"',
            out,
        )
        return m2.group(1) if m2 else ""

    title  = _extract("xesam:title")
    artist = _extract("xesam:artist")
    album  = _extract("xesam:album")
    if not title:
        return None

    rc2, status_out = _run([
        "dbus-send", "--print-reply", "--dest=org.mpris.MediaPlayer2.spotify",
        "/org/mpris/MediaPlayer2",
        "org.freedesktop.DBus.Properties.Get",
        "string:org.mpris.MediaPlayer2.Player",
        "string:PlaybackStatus",
    ])
    playing = "Playing" in status_out
    return {"title": title, "artist": artist, "album": album, "playing": playing, "source": "dbus"}


def _via_web_api() -> dict[str, Any] | None:
    token = os.environ.get("SPOTIFY_TOKEN", "").strip()
    if not token:
        return None
    try:
        req = urllib.request.Request(
            "https://api.spotify.com/v1/me/player/currently-playing",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            if r.status == 204:
                return None
            body = json.loads(r.read())
    except Exception:
        return None
    item = body.get("item") or {}
    if not item:
        return None
    title   = item.get("name", "")
    artists = ", ".join(a["name"] for a in item.get("artists", []))
    album   = (item.get("album") or {}).get("name", "")
    playing = body.get("is_playing", False)
    if not title:
        return None
    return {"title": title, "artist": artists, "album": album, "playing": playing, "source": "web_api"}


def _via_spotipy_api() -> dict[str, Any] | None:
    """
    Query real-time playback state via spotipy sp.current_playback().
    Most accurate source — reflects Spotify's server state immediately.
    Returns None if spotipy is not configured or nothing is playing.
    """
    import sys
    sp = _get_spotify_client()
    if sp is None:
        return None
    try:
        pb = sp.current_playback()
    except Exception as e:
        print(f"[spotify] current_playback error: {e}", file=sys.stderr)
        return None
    if not pb:
        return None
    item = pb.get("item") or {}
    title = item.get("name", "")
    if not title:
        return None
    artists = ", ".join(a["name"] for a in item.get("artists", []))
    album   = (item.get("album") or {}).get("name", "")
    playing = pb.get("is_playing", False)
    return {"title": title, "artist": artists, "album": album, "playing": playing, "source": "spotipy_api"}


def get_current_track() -> dict[str, Any] | None:
    """
    Return currently playing track, or None if Spotify is idle/closed.

    Priority:
      1. spotipy sp.current_playback() — real-time server state, most accurate
      2. playerctl (dbus wrapper) — fast local query
      3. dbus-send directly — fallback if playerctl missing
      4. SPOTIFY_TOKEN env var web API — legacy fallback
    """
    return _via_spotipy_api() or _via_playerctl() or _via_dbus() or _via_web_api()


def format_track(track: dict[str, Any]) -> str:
    parts = [track["title"]]
    if track.get("artist"):
        parts.append(f"by {track['artist']}")
    if track.get("album"):
        parts.append(f"({track['album']})")
    return " ".join(parts)
