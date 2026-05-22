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


def _fetch_lyrics(artist: str, title: str) -> str:
    try:
        a = urllib.parse.quote(artist)
        t = urllib.parse.quote(title)
        resp = requests.get(f"https://api.lyrics.ovh/v1/{a}/{t}", timeout=6)
        if resp.status_code == 200:
            return resp.json().get("lyrics", "")
    except Exception:
        pass
    return ""


def detect_language(artist: str, title: str) -> str:
    lyrics = _fetch_lyrics(artist, title)
    if not lyrics or len(lyrics.strip()) < 20:
        return "Unknown"
    try:
        code = detect(lyrics)
        return _LANG_NAMES.get(code, code.capitalize())
    except LangDetectException:
        return "Unknown"
