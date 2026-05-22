import asyncio
import os
import tempfile


def record_audio(duration: int, sample_rate: int = 44100):
    import sounddevice as sd
    import numpy as np
    audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype="int16")
    sd.wait()
    return audio, sample_rate


def _save_wav(audio, sample_rate: int) -> str:
    import scipy.io.wavfile
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    scipy.io.wavfile.write(tmp.name, sample_rate, audio)
    return tmp.name


async def _shazam_identify(path: str) -> dict:
    from shazamio import Shazam
    return await Shazam().recognize(path)


def _parse_result(result: dict):
    track = result.get("track")
    if not track:
        return None

    title  = track.get("title", "Unknown")
    artist = track.get("subtitle", "Unknown")
    album  = ""

    for section in track.get("sections", []):
        for meta in section.get("metadata", []):
            if meta.get("title", "").lower() == "album":
                album = meta.get("text", "")
                break

    spotify_url = None
    for provider in track.get("hub", {}).get("providers", []):
        if "spotify" in provider.get("caption", "").lower():
            for action in provider.get("actions", []):
                if action.get("type") == "uri":
                    spotify_url = action.get("uri")
                    break

    cover_url = track.get("images", {}).get("coverart") or track.get("images", {}).get("background")

    return {
        "title":       title,
        "artist":      artist,
        "album":       album,
        "cover_url":   cover_url,
        "spotify_url": spotify_url,
        "track_number": 0,
        "year":        "",
        "youtube_url": None,
    }


def record_and_identify(duration: int = 10):
    """Record `duration` seconds from the default mic and return identified track dict or None."""
    audio, sample_rate = record_audio(duration)
    path = _save_wav(audio, sample_rate)
    try:
        result = asyncio.run(_shazam_identify(path))
        return _parse_result(result)
    finally:
        os.unlink(path)


def identify_file(path: str):
    """Identify a song from an existing audio file and return track dict or None."""
    result = asyncio.run(_shazam_identify(path))
    return _parse_result(result)
