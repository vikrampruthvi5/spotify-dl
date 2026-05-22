import os
import re
from mutagen.id3 import ID3, ID3NoHeaderError


def _read_dj_tags(filepath: str) -> dict:
    try:
        tags = ID3(filepath)
    except (ID3NoHeaderError, Exception):
        return {}

    def _text(key):
        f = tags.get(key)
        return str(f.text[0]).strip() if f and hasattr(f, "text") and f.text else ""

    def _txxx(desc):
        f = tags.get(f"TXXX:{desc}")
        return str(f.text[0]).strip() if f and hasattr(f, "text") and f.text else ""

    def _float(s):
        try:
            return float(s)
        except (ValueError, TypeError):
            return None

    return {
        "bpm":          _float(_text("TBPM")),
        "key":          _text("TKEY"),
        "camelot":      _txxx("CAMELOT"),
        "energy":       _float(_txxx("ENERGY")),
        "danceability": _float(_txxx("DANCEABILITY")),
        "valence":      _float(_txxx("VALENCE")),
        "title":        _text("TIT2"),
        "artist":       _text("TPE1"),
        "album":        _text("TALB"),
    }


def build_crate(
    directory: str,
    bpm_min: float = None,
    bpm_max: float = None,
    key: str = None,
    energy_min: float = None,
    output_m3u: str = None,
) -> list:
    """Filter local MP3s by BPM range, Camelot/key, and min energy.

    Args:
        directory:  Root folder to scan recursively.
        bpm_min:    Lower BPM bound (inclusive). None = no lower bound.
        bpm_max:    Upper BPM bound (inclusive). None = no upper bound.
        key:        Camelot key (e.g. "8A", "8B") or standard key ("Am", "C").
                    Match is case-insensitive substring match against TXXX:CAMELOT
                    or TKEY. None = no key filter.
        energy_min: Minimum Spotify energy 0.0–1.0. None = no filter.
        output_m3u: If given, write an extended M3U to this path.

    Returns:
        List of matching file paths.
    """
    matches = []

    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for fname in sorted(files):
            if not fname.lower().endswith(".mp3"):
                continue
            fpath = os.path.join(root, fname)
            info  = _read_dj_tags(fpath)

            # BPM filter
            if bpm_min is not None or bpm_max is not None:
                if info.get("bpm") is None:
                    continue
                b = info["bpm"]
                if bpm_min is not None and b < bpm_min:
                    continue
                if bpm_max is not None and b > bpm_max:
                    continue

            # Key / Camelot filter
            if key:
                key_q = key.strip().upper()
                camelot = (info.get("camelot") or "").upper()
                tkey    = (info.get("key")     or "").upper()
                if key_q not in camelot and key_q not in tkey:
                    continue

            # Energy filter
            if energy_min is not None:
                if info.get("energy") is None or info["energy"] < energy_min:
                    continue

            matches.append((fpath, info))

    if output_m3u and matches:
        with open(output_m3u, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for fpath, info in matches:
                artist  = info.get("artist", "")
                title   = info.get("title", "") or os.path.splitext(os.path.basename(fpath))[0]
                bpm_tag = f" [{info['bpm']:.0f}bpm]" if info.get("bpm") else ""
                key_tag = f" [{info.get('camelot') or info.get('key', '')}]" \
                          if info.get("camelot") or info.get("key") else ""
                f.write(f"#EXTINF:-1,{artist} - {title}{bpm_tag}{key_tag}\n")
                f.write(f"{os.path.abspath(fpath)}\n")

    return [fp for fp, _ in matches]
