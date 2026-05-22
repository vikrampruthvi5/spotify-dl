import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET


def _sp():
    return spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
    ))


def search_tracks(query: str, limit: int = 6):
    results = _sp().search(q=query, type="track", limit=limit)
    out = []
    for item in results["tracks"]["items"]:
        out.append({
            "title":        item["name"],
            "artist":       ", ".join(a["name"] for a in item["artists"]),
            "album":        item["album"]["name"],
            "year":         (item["album"].get("release_date") or "")[:4],
            "track_number": item.get("track_number", 0),
            "cover_url":    (item["album"].get("images") or [{}])[0].get("url"),
            "youtube_url":  None,
            "duration_ms":  item.get("duration_ms", 0),
        })
    return out


def search_albums(query: str, limit: int = 5):
    results = _sp().search(q=query, type="album", limit=limit)
    out = []
    for item in results["albums"]["items"]:
        out.append({
            "id":           item["id"],
            "name":         item["name"],
            "artist":       ", ".join(a["name"] for a in item["artists"]),
            "year":         (item.get("release_date") or "")[:4],
            "total_tracks": item.get("total_tracks", 0),
            "cover_url":    (item.get("images") or [{}])[0].get("url"),
            "spotify_url":  item["external_urls"].get("spotify"),
        })
    return out
