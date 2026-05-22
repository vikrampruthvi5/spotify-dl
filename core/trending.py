"""Trending playlists per region.

Uses Spotify search to discover the current top-matching playlist for each
region (queries are stable; the playlists Spotify returns are updated by them
on whatever cadence they choose, so this stays fresh automatically).
"""

from .spotify_client import _make_client


REGIONS = {
    "bollywood": {"query": "Bollywood Hot Hits",  "label": "Bollywood", "language": "Hindi"},
    "hollywood": {"query": "Today's Top Hits",    "label": "Hollywood", "language": "English"},
    "tollywood": {"query": "Telugu Hot Hits Top", "label": "Tollywood", "language": "Telugu"},
    "tamil":     {"query": "Tamil Hot Hits",      "label": "Kollywood", "language": "Tamil"},
    "punjabi":   {"query": "Punjabi Hot Hits",    "label": "Punjabi",   "language": "Punjabi"},
}


def get_trending(region: str, limit: int = 50) -> dict:
    """Return the current top-matching trending playlist for a region.

    Args:
        region: One of REGIONS keys.
        limit:  Max tracks to return (cap is 50 per Spotify response anyway).

    Returns:
        {
            "region":        str,
            "label":         str,
            "language":      str,
            "playlist_name": str,
            "playlist_id":   str,
            "playlist_url":  str,
            "cover_url":     str | None,
            "tracks":        [ {id, title, artist, album, year, duration_ms,
                                cover_url, popularity, spotify_url}, ... ]
        }
    """
    key = region.lower()
    if key not in REGIONS:
        raise ValueError(f"Unknown region: {region}")
    cfg = REGIONS[key]

    sp = _make_client()
    results   = sp.search(q=cfg["query"], type="playlist", limit=5)
    playlists = [p for p in (results.get("playlists", {}) or {}).get("items", []) or [] if p]
    if not playlists:
        return {"region": key, "label": cfg["label"], "language": cfg["language"],
                "playlist_name": "", "playlist_id": "", "playlist_url": "",
                "cover_url": None, "tracks": []}

    meta = playlists[0]
    pl   = sp.playlist(meta["id"])

    tracks = []
    for item in (pl.get("tracks", {}).get("items") or [])[:limit]:
        t = item.get("track")
        if not t or t.get("is_local"):
            continue
        images = t["album"].get("images", [])
        tracks.append({
            "id":          t["id"],
            "title":       t["name"],
            "artist":      ", ".join(a["name"] for a in t["artists"]),
            "album":       t["album"]["name"],
            "duration_ms": t["duration_ms"],
            "year":        (t["album"].get("release_date") or "")[:4],
            "cover_url":   images[0]["url"] if images else None,
            "popularity":  t.get("popularity", 0),
            "spotify_url": (t.get("external_urls") or {}).get("spotify"),
            "preview_url": t.get("preview_url"),  # 30 s MP3 preview, may be null
        })

    pl_images = pl.get("images") or []
    return {
        "region":        key,
        "label":         cfg["label"],
        "language":      cfg["language"],
        "playlist_name": pl["name"],
        "playlist_id":   pl["id"],
        "playlist_url":  (pl.get("external_urls") or {}).get("spotify", ""),
        "cover_url":     pl_images[0]["url"] if pl_images else None,
        "tracks":        tracks,
    }


def list_regions() -> list:
    """List supported regions with display metadata."""
    return [{"id": k, **v} for k, v in REGIONS.items()]
