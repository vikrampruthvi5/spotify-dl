# SpotiDL

Download Spotify playlists, albums, and tracks as high-quality MP3 files.  
Searches YouTube for each track, downloads the best audio, and writes full ID3 metadata (title, artist, album, year, track number, cover art).

```
   _____             __  _ ____  __
  / ___/____  ____  / /_(_) __ \/ /
  \__ \/ __ \/ __ \/ __/ / / / / /
 ___/ / /_/ / /_/ / /_/ / /_/ / /___
/____/ .___/\____/\__/_/_____/_____/
    /_/
```

---

## Features

- Downloads **playlists**, **albums**, and **single tracks** from Spotify
- Searches YouTube automatically — no YouTube API key required
- Writes complete **ID3 tags**: title, artist, album, year, track number, and cover art
- **Skips already-downloaded tracks** (safe to re-run)
- Configurable **MP3 bitrate**: 128 / 192 / 256 / 320 kbps
- **Parallel downloads** via `--jobs N`
- Colorful terminal UI with progress bar and per-track status

---

## Requirements

- Python 3.9+
- [ffmpeg](https://ffmpeg.org/) (required by yt-dlp for audio conversion)
- Spotify Developer credentials (free)

### Install ffmpeg

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# Windows (via Chocolatey)
choco install ffmpeg
```

---

## Installation

```bash
git clone https://github.com/yourname/spotify-dl.git
cd spotify-dl
pip install -r requirements.txt
```

---

## Setup

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and create an app.
2. Copy your **Client ID** and **Client Secret**.
3. Create a `.env` file in the project directory:

```env
SPOTIFY_CLIENT_ID=your_client_id_here
SPOTIFY_CLIENT_SECRET=your_client_secret_here
```

---

## Usage

```
python3 main.py <spotify_url> [options]
```

### Arguments

| Argument | Description |
|---|---|
| `url` | Spotify playlist, album, or track URL |
| `-o, --output DIR` | Output directory (default: `~/Downloads/SpotiDL`) |
| `-q, --quality KBPS` | MP3 bitrate: `128`, `192`, `256`, `320` (default: `320`) |
| `-j, --jobs N` | Parallel downloads (default: `1`) |

### Examples

```bash
# Download a playlist at 320 kbps
python3 main.py https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M

# Download an album to a custom folder
python3 main.py https://open.spotify.com/album/1DFixLWuPkv3KT3TnV35m3 -o ~/Music/Albums

# Download a single track at 192 kbps
python3 main.py https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC -q 192

# Download a playlist with 4 parallel workers
python3 main.py https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M -j 4
```

---

## Output

Files are saved as:

```
<output_dir>/
  Artist Name - Track Title.mp3
  Artist Name - Track Title.mp3
  ...
```

Each file contains embedded ID3 tags readable by any media player (iTunes, VLC, foobar2000, etc.).

---

## Project Structure

```
spotify-dl/
├── main.py            # CLI entry point, UI rendering, download orchestration
├── spotify_client.py  # Spotify API: fetch playlist / album / track metadata
├── downloader.py      # YouTube search + audio download via yt-dlp
├── tagger.py          # Write ID3 metadata + cover art via mutagen
├── config.py          # Load .env credentials and defaults
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## How It Works

1. **Fetch metadata** — SpotiDL calls the Spotify API to get track names, artists, albums, release years, and cover art URLs.
2. **Search YouTube** — For each track, yt-dlp searches `ytsearch1:<artist> - <title>` and picks the top result.
3. **Download & convert** — yt-dlp downloads the best available audio and ffmpeg converts it to MP3 at the requested bitrate.
4. **Tag** — mutagen writes ID3v2 tags and embeds the album cover from Spotify's CDN.

---

## Notes

- Track matching is best-effort via YouTube search. Accuracy depends on how well-indexed the track is on YouTube.
- SpotiDL does not download DRM-protected content directly from Spotify. It finds equivalent audio on YouTube.
- Re-running on the same output directory skips files that already exist.

---

## Dependencies

| Package | Purpose |
|---|---|
| `spotipy` | Spotify Web API client |
| `yt-dlp` | YouTube download + audio extraction |
| `mutagen` | ID3 tag writing |
| `rich` | Terminal UI (colors, progress bar, panels) |
| `pyfiglet` | ASCII banner |
| `requests` | Fetch album cover art |
| `python-dotenv` | Load `.env` credentials |
