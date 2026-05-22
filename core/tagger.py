import requests
from mutagen.id3 import (
    ID3, TIT2, TPE1, TALB, TDRC, TRCK, APIC, TXXX, ID3NoHeaderError
)


def tag_file(filepath: str, track: dict) -> bool:
    try:
        try:
            tags = ID3(filepath)
        except ID3NoHeaderError:
            tags = ID3()

        tags["TIT2"] = TIT2(encoding=3, text=track["title"])
        tags["TPE1"] = TPE1(encoding=3, text=track["artist"])
        tags["TALB"] = TALB(encoding=3, text=track["album"])
        if track.get("year"):
            tags["TDRC"] = TDRC(encoding=3, text=track["year"])
        if track.get("track_number"):
            tags["TRCK"] = TRCK(encoding=3, text=str(track["track_number"]))

        if track.get("cover_url"):
            try:
                resp = requests.get(track["cover_url"], timeout=10)
                if resp.status_code == 200:
                    tags["APIC"] = APIC(
                        encoding=3,
                        mime="image/jpeg",
                        type=3,
                        desc="Cover",
                        data=resp.content,
                    )
            except Exception:
                pass

        # Spotify audio features — stored as TXXX custom frames
        for feat, desc in [
            ("danceability",     "DANCEABILITY"),
            ("energy",           "ENERGY"),
            ("valence",          "VALENCE"),
            ("instrumentalness", "INSTRUMENTALNESS"),
        ]:
            val = track.get(feat)
            if val is not None:
                tags.delall(f"TXXX:{desc}")
                tags.add(TXXX(encoding=3, desc=desc, text=str(round(float(val), 3))))

        # Spotify's own tempo estimate (not from audio analysis)
        if track.get("spotify_bpm") is not None:
            tags.delall("TXXX:SPOTIFY_BPM")
            tags.add(TXXX(encoding=3, desc="SPOTIFY_BPM",
                          text=str(round(float(track["spotify_bpm"]), 2))))

        tags.save(filepath)
        return True
    except Exception:
        return False
