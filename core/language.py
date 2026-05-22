import re
import urllib.parse
import requests
from langdetect import detect, LangDetectException

_LANG_NAMES = {
    "en": "English",    "es": "Spanish",    "fr": "French",
    "de": "German",     "pt": "Portuguese", "it": "Italian",
    "ja": "Japanese",   "ko": "Korean",     "zh-cn": "Chinese",
    "zh-tw": "Chinese", "ar": "Arabic",     "hi": "Hindi",
    "ru": "Russian",    "nl": "Dutch",      "sv": "Swedish",
    "no": "Norwegian",  "da": "Danish",     "fi": "Finnish",
    "pl": "Polish",     "tr": "Turkish",    "id": "Indonesian",
    "ms": "Malay",      "th": "Thai",       "vi": "Vietnamese",
    "cs": "Czech",      "sk": "Slovak",     "hu": "Hungarian",
    "ro": "Romanian",   "bg": "Bulgarian",  "uk": "Ukrainian",
    "el": "Greek",      "he": "Hebrew",     "fa": "Persian",
    "hr": "Croatian",   "sr": "Serbian",    "sl": "Slovenian",
    "et": "Estonian",   "lv": "Latvian",    "lt": "Lithuanian",
    "sq": "Albanian",   "is": "Icelandic",  "cy": "Welsh",
    "af": "Afrikaans",  "ca": "Catalan",
}

# Split on comma, feat., &, x  — keep only the primary artist for the lookup
_ARTIST_SPLIT = re.compile(r'\s*,\s*|\s+feat\.?\s+|\s+&\s+|\s+x\s+', re.IGNORECASE)
# Strip parenthetical/bracketed extras from titles (feat., remix, remaster, etc.)
_TITLE_NOISE = re.compile(
    r'\s*[\(\[][^)\]]*(feat\.?|ft\.?|remix|remaster|version|edit|live|acoustic)[^)\]]*[\)\]]',
    re.IGNORECASE,
)


def _primary_artist(artist: str) -> str:
    return _ARTIST_SPLIT.split(artist)[0].strip()


def _clean_title(title: str) -> str:
    return _TITLE_NOISE.sub("", title).strip()


def _fetch_lyrics(artist: str, title: str) -> str:
    try:
        a = urllib.parse.quote(_primary_artist(artist))
        t = urllib.parse.quote(_clean_title(title))
        resp = requests.get(f"https://api.lyrics.ovh/v1/{a}/{t}", timeout=6)
        if resp.status_code == 200:
            return resp.json().get("lyrics", "")
    except Exception:
        pass
    return ""


def _lang_from_text(text: str) -> str:
    try:
        code = detect(text)
        return _LANG_NAMES.get(code, code.capitalize())
    except LangDetectException:
        return "Unknown"


def detect_language(artist: str, title: str) -> str:
    lyrics = _fetch_lyrics(artist, title)
    if lyrics and len(lyrics.strip()) >= 20:
        return _lang_from_text(lyrics)
    # Fallback: detect from title + artist text (works well when titles are
    # in the native language, e.g. Korean/Japanese/Spanish tracks)
    return _lang_from_text(f"{title} {_primary_artist(artist)}")
