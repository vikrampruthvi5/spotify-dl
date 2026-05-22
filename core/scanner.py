import os
from mutagen.id3 import ID3, ID3NoHeaderError

# Tags checked and their friendly labels
_CHECKS = [
    ("TIT2", "Title"),
    ("TPE1", "Artist"),
    ("TALB", "Album"),
    ("TDRC", "Year"),
    ("APIC", "Cover Art"),
    ("TBPM", "BPM"),
    ("TKEY", "Key"),
]


def scan_library(directory: str) -> list:
    """Walk directory and report missing ID3 tags for each MP3.

    Returns a list of dicts:
        {"path": str, "missing": [label, ...], "tags": {label: value}}
    Only files with at least one missing tag are included.
    """
    results = []
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for fname in sorted(files):
            if not fname.lower().endswith(".mp3"):
                continue
            fpath = os.path.join(root, fname)
            try:
                tags = ID3(fpath)
            except ID3NoHeaderError:
                tags = {}
            except Exception:
                continue

            missing = []
            present = {}
            for tag_id, label in _CHECKS:
                if tag_id == "APIC":
                    has = any(k.startswith("APIC") for k in tags.keys()) if tags else False
                    if not has:
                        missing.append(label)
                    else:
                        present[label] = "✓"
                else:
                    val = tags.get(tag_id) if tags else None
                    text = str(val.text[0]).strip() if val and hasattr(val, "text") and val.text else ""
                    if not text:
                        missing.append(label)
                    else:
                        present[label] = text[:40]

            if missing:
                results.append({"path": fpath, "missing": missing, "tags": present})

    return results
