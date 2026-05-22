import os
import re
from mutagen.id3 import ID3, ID3NoHeaderError


def _normalize(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"\(feat[^)]*\)", "", s)
    s = re.sub(r"\(ft[^)]*\)",   "", s)
    s = re.sub(r"\([^)]*remix[^)]*\)", "", s)
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _build_local_index(directory: str) -> dict:
    """Walk directory and map normalized 'artist|||title' → filepath."""
    index = {}
    for root, dirs, files in os.walk(directory):
        for fname in files:
            if not fname.lower().endswith(".mp3"):
                continue
            fpath = os.path.join(root, fname)
            try:
                tags   = ID3(fpath)
                artist = str(tags.get("TPE1") or "")
                title  = str(tags.get("TIT2") or "")
                if artist or title:
                    key = f"{_normalize(artist)}|||{_normalize(title)}"
                    index[key] = fpath
                    continue
            except Exception:
                pass
            # Fallback: parse filename as "Artist - Title"
            stem  = os.path.splitext(fname)[0]
            parts = stem.split(" - ", 1)
            if len(parts) == 2:
                key = f"{_normalize(parts[0])}|||{_normalize(parts[1])}"
                index[key] = fpath
    return index


def check_set(tracks: list, directory: str) -> dict:
    """Cross-reference Spotify track list against the local library.

    Args:
        tracks:    List of track dicts with 'artist' and 'title' keys.
        directory: Root folder to scan for MP3s.

    Returns:
        {"found": [track_dict + local_path, ...], "missing": [track_dict, ...]}
    """
    index = _build_local_index(directory)
    found, missing = [], []

    for track in tracks:
        key = f"{_normalize(track['artist'])}|||{_normalize(track['title'])}"
        if key in index:
            found.append({**track, "local_path": index[key]})
        else:
            missing.append(track)

    return {"found": found, "missing": missing}
