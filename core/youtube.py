import re
import yt_dlp
from downloader import _SilentLogger, _USER_AGENT

# Web client for metadata (richer fields); android client is only needed for actual downloads
_YDL_META = {
    "quiet": True,
    "no_warnings": True,
    "logger": _SilentLogger(),
    "http_headers": {"User-Agent": _USER_AGENT},
}

# Noise patterns to strip from YouTube video titles
_TITLE_NOISE = re.compile(
    r"\s*[\(\[]("
    r"official\s*(music\s*)?video|official\s*(audio|mv|lyric\s*video|visualizer)"
    r"|lyric\s*video|audio|m/v|mv|performance\s*video|visualizer"
    r")[\)\]]\s*",
    re.IGNORECASE,
)


def is_youtube_url(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url))


def _best_thumbnail(entry: dict):
    thumbs = entry.get("thumbnails") or []
    if thumbs:
        return max(thumbs, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0)).get("url")
    return entry.get("thumbnail")


def _parse_artist_title(raw_title: str, channel: str):
    """
    Extract artist / title from a YouTube video title.
    Handles 'Artist - Title (Official Video)' patterns.
    Falls back to channel name as artist when no dash separator exists.
    """
    clean = _TITLE_NOISE.sub("", raw_title).strip().rstrip("-").strip()
    if " - " in clean:
        artist, title = clean.split(" - ", 1)
        return artist.strip(), title.strip()
    return channel or "Unknown", clean


def _make_track(entry: dict, album: str = "", index: int = 0) -> dict:
    vid_id  = entry.get("id") or ""
    channel = entry.get("uploader") or entry.get("channel") or ""

    # Prefer music-specific metadata (available for YouTube Music URLs)
    if entry.get("artist"):
        artist = entry["artist"]
        title  = entry.get("track") or entry.get("title", "Unknown")
    else:
        artist, title = _parse_artist_title(entry.get("title", "Unknown"), channel)

    return {
        "title":        title,
        "artist":       artist,
        "album":        entry.get("album") or album,
        "year":         (entry.get("upload_date") or "")[:4],
        "track_number": index or entry.get("playlist_index") or 0,
        "cover_url":    _best_thumbnail(entry),
        "youtube_url":  f"https://www.youtube.com/watch?v={vid_id}" if vid_id else None,
    }


def get_video_info(url: str) -> dict:
    opts = {**_YDL_META, "noplaylist": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        entry = ydl.extract_info(url, download=False)
    track = _make_track(entry)
    return {
        "type":         "track",
        "name":         track["title"],
        "owner":        track["artist"],
        "description":  "",
        "total_tracks": 1,
        "cover_url":    track["cover_url"],
        "tracks":       [track],
    }


def get_playlist_info(url: str) -> dict:
    opts = {**_YDL_META, "extract_flat": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        data = ydl.extract_info(url, download=False)
    entries = [e for e in (data.get("entries") or []) if e]
    title   = data.get("title", "YouTube Playlist")
    channel = data.get("uploader") or data.get("channel") or "YouTube"
    tracks  = [_make_track(e, album=title, index=i) for i, e in enumerate(entries, 1)]
    return {
        "type":         "playlist",
        "name":         title,
        "owner":        channel,
        "description":  "",
        "total_tracks": len(tracks),
        "cover_url":    _best_thumbnail(data),
        "tracks":       tracks,
    }


def get_info(url: str) -> dict:
    if "playlist" in url or "list=" in url:
        return get_playlist_info(url)
    return get_video_info(url)
