import re
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from .config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET


def _make_client() -> spotipy.Spotify:
    return spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
        )
    )


def _extract_id(url: str, resource_type: str) -> str:
    match = re.search(rf"{resource_type}/([a-zA-Z0-9]+)", url)
    if not match:
        raise ValueError(f"Could not find a {resource_type} ID in: {url}")
    return match.group(1)


def _track_dict(track: dict, album_name: str, cover_url, year: str) -> dict:
    return {
        "id":           track.get("id", ""),
        "title":        track["name"],
        "artist":       ", ".join(a["name"] for a in track["artists"]),
        "album":        album_name,
        "duration_ms":  track["duration_ms"],
        "cover_url":    cover_url,
        "year":         year,
        "track_number": track.get("track_number", 0),
        # audio feature fields — populated by _apply_audio_features()
        "danceability":     None,
        "energy":           None,
        "valence":          None,
        "instrumentalness": None,
        "spotify_bpm":      None,
    }


def _fetch_audio_features(sp, tracks: list) -> dict:
    """Batch-fetch Spotify audio features. Returns {track_id: features_dict}."""
    ids = [t["id"] for t in tracks if t.get("id")]
    if not ids:
        return {}
    features = {}
    try:
        for i in range(0, len(ids), 50):
            for feat in (sp.audio_features(ids[i : i + 50]) or []):
                if feat:
                    features[feat["id"]] = feat
    except Exception:
        pass
    return features


def _apply_audio_features(tracks: list, features: dict):
    for t in tracks:
        feat = features.get(t.get("id", "")) or {}
        t["danceability"]     = feat.get("danceability")
        t["energy"]           = feat.get("energy")
        t["valence"]          = feat.get("valence")
        t["instrumentalness"] = feat.get("instrumentalness")
        t["spotify_bpm"]      = feat.get("tempo")


def get_playlist_info(url: str) -> dict:
    sp = _make_client()
    playlist_id = _extract_id(url, "playlist")
    playlist = sp.playlist(playlist_id)

    tracks = []
    results = playlist["tracks"]

    while results:
        for item in results["items"]:
            track = item.get("track")
            if not track or track.get("is_local"):
                continue
            images = track["album"].get("images", [])
            cover_url = images[0]["url"] if images else None
            year = (track["album"].get("release_date") or "")[:4]
            tracks.append(_track_dict(track, track["album"]["name"], cover_url, year))
        results = sp.next(results) if results.get("next") else None

    _apply_audio_features(tracks, _fetch_audio_features(sp, tracks))

    cover_images = playlist.get("images", [])
    return {
        "type": "playlist",
        "name": playlist["name"],
        "owner": playlist["owner"]["display_name"],
        "description": playlist.get("description", ""),
        "total_tracks": len(tracks),
        "cover_url": cover_images[0]["url"] if cover_images else None,
        "tracks": tracks,
    }


def get_album_info(url: str) -> dict:
    sp = _make_client()
    album_id = _extract_id(url, "album")
    album = sp.album(album_id)

    cover_images = album.get("images", [])
    cover_url = cover_images[0]["url"] if cover_images else None
    year = (album.get("release_date") or "")[:4]

    tracks = []
    results = album["tracks"]
    while results:
        for item in results["items"]:
            tracks.append(_track_dict(item, album["name"], cover_url, year))
        results = sp.next(results) if results.get("next") else None

    _apply_audio_features(tracks, _fetch_audio_features(sp, tracks))

    return {
        "type": "album",
        "name": album["name"],
        "owner": ", ".join(a["name"] for a in album["artists"]),
        "description": "",
        "total_tracks": len(tracks),
        "cover_url": cover_url,
        "tracks": tracks,
    }


def get_track_info(url: str) -> dict:
    sp = _make_client()
    track_id = _extract_id(url, "track")
    track = sp.track(track_id)

    images = track["album"].get("images", [])
    cover_url = images[0]["url"] if images else None
    year = (track["album"].get("release_date") or "")[:4]
    t = _track_dict(track, track["album"]["name"], cover_url, year)
    _apply_audio_features([t], _fetch_audio_features(sp, [t]))

    return {
        "type": "track",
        "name": track["name"],
        "owner": t["artist"],
        "description": "",
        "total_tracks": 1,
        "cover_url": cover_url,
        "tracks": [t],
    }


def get_tracks_by_ids(track_ids: list) -> list:
    """Fetch full track dicts for an arbitrary list of Spotify track IDs.

    Batches the request in groups of 50 (Spotify API limit), filters out
    unavailable / local tracks, and enriches with audio features so the
    returned tracks are ready to feed into download_track + tag_file.
    """
    if not track_ids:
        return []
    sp = _make_client()
    tracks = []
    for i in range(0, len(track_ids), 50):
        batch = sp.tracks(track_ids[i : i + 50]) or {}
        for t in (batch.get("tracks") or []):
            if not t or t.get("is_local"):
                continue
            images    = t["album"].get("images", [])
            cover_url = images[0]["url"] if images else None
            year      = (t["album"].get("release_date") or "")[:4]
            tracks.append(_track_dict(t, t["album"]["name"], cover_url, year))
    _apply_audio_features(tracks, _fetch_audio_features(sp, tracks))
    return tracks


def get_info(url: str) -> dict:
    if "/playlist/" in url:
        return get_playlist_info(url)
    elif "/album/" in url:
        return get_album_info(url)
    elif "/track/" in url:
        return get_track_info(url)
    else:
        raise ValueError("URL must be a Spotify playlist, album, or track URL")
