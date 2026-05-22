import os
import numpy as np

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Camelot wheel: chromatic root index (0=C) → position
_CAMELOT_MAJOR = {
    0: "8B", 1: "3B", 2: "10B", 3: "5B", 4: "12B", 5: "7B",
    6: "2B", 7: "9B", 8:  "4B", 9: "11B", 10: "6B", 11: "1B",
}
_CAMELOT_MINOR = {
    0: "5A", 1: "12A", 2: "7A", 3: "2A", 4: "9A", 5: "4A",
    6: "11A", 7: "6A", 8: "1A", 9: "8A", 10: "3A", 11: "10A",
}

# Krumhansl–Schmuckler tonal hierarchy profiles
_MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def _detect_key(chroma_mean: np.ndarray):
    major_corrs = [np.corrcoef(np.roll(_MAJOR_PROFILE, i), chroma_mean)[0, 1] for i in range(12)]
    minor_corrs = [np.corrcoef(np.roll(_MINOR_PROFILE, i), chroma_mean)[0, 1] for i in range(12)]
    bm  = max(range(12), key=lambda i: major_corrs[i])
    bmi = max(range(12), key=lambda i: minor_corrs[i])
    if major_corrs[bm] >= minor_corrs[bmi]:
        return bm, "major"
    return bmi, "minor"


def analyze_audio(filepath: str) -> dict:
    """Detect BPM and musical key from audio file.

    Loads first 60 s of audio via librosa, runs beat tracking (BPM) and
    chroma-based key detection (Krumhansl–Schmuckler). Returns {} if librosa
    is unavailable or the analysis fails for any reason.
    """
    try:
        import librosa
    except ImportError:
        return {}
    try:
        y, sr = librosa.load(filepath, mono=True, duration=60)

        # BPM via beat tracker
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(round(float(np.atleast_1d(tempo)[0]), 2))

        # Key via chroma CQT + Krumhansl–Schmuckler correlation
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        root, mode = _detect_key(chroma.mean(axis=1))

        suffix  = "m" if mode == "minor" else ""
        key_str = f"{_NOTE_NAMES[root]}{suffix}"        # e.g. "Am", "C#", "Gbm"
        camelot = (_CAMELOT_MINOR if mode == "minor" else _CAMELOT_MAJOR)[root]

        return {"bpm": bpm, "key": key_str, "camelot": camelot}
    except Exception:
        return {}


def analyze_and_tag(filepath: str) -> dict:
    """Analyze audio and write BPM / key / Camelot to ID3 tags in-place.

    Returns the analysis dict (or {} on failure).
    """
    from mutagen.id3 import ID3, TBPM, TKEY, TXXX, ID3NoHeaderError

    result = analyze_audio(filepath)
    if not result:
        return {}
    try:
        try:
            tags = ID3(filepath)
        except ID3NoHeaderError:
            tags = ID3()

        if result.get("bpm"):
            tags["TBPM"] = TBPM(encoding=3, text=str(int(round(result["bpm"]))))
        if result.get("key"):
            tags["TKEY"] = TKEY(encoding=3, text=result["key"])
        if result.get("camelot"):
            tags.delall("TXXX:CAMELOT")
            tags.add(TXXX(encoding=3, desc="CAMELOT", text=result["camelot"]))

        tags.save(filepath)
    except Exception:
        pass
    return result


def analyze_directory(directory: str, force: bool = False):
    """Walk directory and analyze every MP3 that lacks a TBPM tag.

    Yields (filepath, result_dict) for each file processed.
    Skips files that already have TBPM unless force=True.
    """
    from mutagen.id3 import ID3, ID3NoHeaderError

    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for fname in sorted(files):
            if not fname.lower().endswith(".mp3"):
                continue
            fpath = os.path.join(root, fname)
            if not force:
                try:
                    if ID3(fpath).get("TBPM"):
                        continue
                except Exception:
                    pass
            result = analyze_and_tag(fpath)
            yield fpath, result
