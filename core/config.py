import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
DEFAULT_OUTPUT_DIR = str(Path.home() / "Downloads" / "SpotiDL")
DEFAULT_QUALITY = "320"
