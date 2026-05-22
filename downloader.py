import os
import re
from pathlib import Path
import yt_dlp


class _SilentLogger:
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass

SKIP = "__skipped__"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def sanitize(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip()


def download_track(track: dict, output_dir: str, quality: str = "320", cookies_browser: str = None):
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    safe_name = sanitize(f"{track['artist']} - {track['title']}")
    final_path = os.path.join(output_dir, f"{safe_name}.mp3")

    if os.path.exists(final_path):
        return SKIP

    query = f"{track['artist']} - {track['title']}"
    template = os.path.join(output_dir, f"{safe_name}.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": quality,
            }
        ],
        "outtmpl": template,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "logger": _SilentLogger(),
        "retries": 3,
        "fragment_retries": 3,
        "noprogress": True,
        "http_headers": {"User-Agent": _USER_AGENT},
        # android client bypasses YouTube's SABR/403 restrictions without needing a PO token
        "extractor_args": {"youtube": {"player_client": ["android"]}},
    }

    if cookies_browser:
        ydl_opts["cookiesfrombrowser"] = (cookies_browser,)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"ytsearch1:{query}"])
    except Exception:
        pass  # post-processing warnings can raise; still check if the mp3 was written

    return final_path if os.path.exists(final_path) else None
