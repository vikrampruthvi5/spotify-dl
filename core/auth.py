"""Spotify OAuth — user-scope authentication for playlist write access.

Uses the Authorization Code flow via spotipy.SpotifyOAuth. Tokens are
persisted to ~/.spotidl/spotify_user_cache so the user stays logged in
across app restarts.

Redirect URI:  http://127.0.0.1:8765/api/auth/callback
This URI must be added to the Spotify Developer App's "Redirect URIs"
allowlist (https://developer.spotify.com/dashboard) for the OAuth flow
to succeed.
"""

import os
from typing import Optional

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from .config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET


REDIRECT_URI = "http://127.0.0.1:8765/api/auth/callback"
SCOPES       = " ".join([
    "playlist-modify-private",
    "playlist-modify-public",
    "playlist-read-private",
    "user-read-private",
])

_CONFIG_DIR = os.path.expanduser("~/.spotidl")
CACHE_PATH  = os.path.join(_CONFIG_DIR, "spotify_user_cache")


def _ensure_dir():
    os.makedirs(_CONFIG_DIR, exist_ok=True)


def _oauth() -> SpotifyOAuth:
    _ensure_dir()
    return SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPES,
        cache_path=CACHE_PATH,
        open_browser=False,
    )


def authorize_url() -> str:
    """The URL the frontend should open in the system browser to start login."""
    return _oauth().get_authorize_url()


def handle_callback(code: str) -> dict:
    """Exchange Spotify's redirect ?code= for an access + refresh token."""
    return _oauth().get_access_token(code, as_dict=True, check_cache=False)


def _refresh_if_needed(token_info: dict) -> Optional[dict]:
    auth = _oauth()
    if auth.is_token_expired(token_info):
        try:
            return auth.refresh_access_token(token_info["refresh_token"])
        except Exception:
            return None
    return token_info


def get_user_client() -> Optional[spotipy.Spotify]:
    """Return a spotipy client authenticated as the user, or None if not logged in."""
    token = _oauth().get_cached_token()
    if not token:
        return None
    token = _refresh_if_needed(token)
    if not token:
        return None
    return spotipy.Spotify(auth=token["access_token"])


def get_user_profile() -> Optional[dict]:
    """Return the logged-in user's Spotify profile (id, display_name, avatar)."""
    sp = get_user_client()
    if not sp:
        return None
    try:
        user = sp.current_user()
        avatar = None
        images = user.get("images") or []
        if images:
            avatar = images[0].get("url")
        return {
            "id":           user["id"],
            "display_name": user.get("display_name") or user["id"],
            "avatar_url":   avatar,
            "followers":    (user.get("followers") or {}).get("total", 0),
            "url":          (user.get("external_urls") or {}).get("spotify"),
        }
    except Exception:
        return None


def logout():
    """Delete the cached token so the next request requires re-authentication."""
    if os.path.exists(CACHE_PATH):
        os.remove(CACHE_PATH)
