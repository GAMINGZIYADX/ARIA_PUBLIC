#!/usr/bin/env python3
"""
One-time Spotify OAuth setup for ARIA.

Run this once from the project root to authorise ARIA to control Spotify:

    python3 scripts/spotify_auth.py

You'll be shown a URL — open it in a browser, authorise, then paste the
redirect URL back here.  The token is cached in data/.spotify_cache and
ARIA will auto-refresh it from then on.

Required env vars (set in your shell or add to .env):
    SPOTIPY_CLIENT_ID      — from https://developer.spotify.com/dashboard
    SPOTIPY_CLIENT_SECRET  — same dashboard
    SPOTIPY_REDIRECT_URI   — must match what you set in the dashboard
                             (default: http://127.0.0.1:8888/callback)
                             IMPORTANT: Spotify banned 'localhost' as a hostname
                             on April 9 2025. You must use 127.0.0.1.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
except ImportError:
    print("ERROR: spotipy not installed.  Run: pip install spotipy")
    sys.exit(1)

client_id     = os.environ.get("SPOTIPY_CLIENT_ID", "").strip()
client_secret = os.environ.get("SPOTIPY_CLIENT_SECRET", "").strip()
redirect_uri  = os.environ.get("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

if not client_id or not client_secret:
    print("ERROR: SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET must be set.")
    print("  Get them from https://developer.spotify.com/dashboard")
    sys.exit(1)

cache_path = os.path.join(ROOT, "data", ".spotify_cache")

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
    open_browser=True,   # open browser automatically for the auth URL
)

print("Opening Spotify authorisation in your browser...")
print(f"Redirect URI: {redirect_uri}")
print()

token = auth.get_access_token(as_dict=False)
if token:
    sp = spotipy.Spotify(auth=token)
    me = sp.me()
    print(f"Authorised as: {me['display_name']} ({me.get('email', 'no email scope')})")
    print(f"Token cached at: {cache_path}")
    print()
    print("ARIA will now use Spotipy for Spotify playback.")
else:
    print("ERROR: authorisation failed — no token returned.")
    sys.exit(1)
