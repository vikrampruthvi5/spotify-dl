import os
import re
import hashlib
from collections import defaultdict
from mutagen.id3 import ID3, ID3NoHeaderError


def _normalize(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"\(feat[^)]*\)", "", s)
    s = re.sub(r"\(ft[^)]*\)",   "", s)
    s = re.sub(r"\([^)]*remix[^)]*\)", "", s)
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _artist_title(filepath: str):
    try:
        tags = ID3(filepath)
        artist = str(tags.get("TPE1") or "")
        title  = str(tags.get("TIT2") or "")
        return _normalize(artist), _normalize(title)
    except Exception:
        stem   = os.path.splitext(os.path.basename(filepath))[0]
        parts  = stem.split(" - ", 1)
        if len(parts) == 2:
            return _normalize(parts[0]), _normalize(parts[1])
        return "", _normalize(stem)


def _md5(filepath: str, chunk: int = 65536) -> str:
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        while True:
            data = f.read(chunk)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def find_duplicates(directory: str) -> dict:
    """Scan directory for duplicate MP3s.

    Returns:
        {
          "by_tags":  [[path, path, ...], ...],   # same artist+title
          "by_hash":  [[path, path, ...], ...],   # byte-identical files
        }
    """
    mp3s = []
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for fname in sorted(files):
            if fname.lower().endswith(".mp3"):
                mp3s.append(os.path.join(root, fname))

    by_tags: dict[str, list] = defaultdict(list)
    for fpath in mp3s:
        artist, title = _artist_title(fpath)
        if artist or title:
            by_tags[f"{artist}|||{title}"].append(fpath)

    by_hash: dict[str, list] = defaultdict(list)
    for fpath in mp3s:
        try:
            by_hash[_md5(fpath)].append(fpath)
        except Exception:
            pass

    return {
        "by_tags": [v for v in by_tags.values() if len(v) > 1],
        "by_hash": [v for v in by_hash.values() if len(v) > 1],
    }
