"""SpotiDL FastAPI server — backend for the Tauri GUI.

Run directly:  python3 server.py
Entry point:   dj-server (via pyproject.toml)

All long-running operations (downloads, analysis, scans) are dispatched to a
thread pool and progress is streamed to the client via Server-Sent Events (SSE).
"""

import asyncio
import json
import os
import re
import uuid
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed as futures_done
from typing import Optional

warnings.filterwarnings("ignore")

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config import DEFAULT_OUTPUT_DIR, DEFAULT_QUALITY
from core.spotify_client import get_info as get_spotify_info, get_tracks_by_ids
from core.trending import get_trending, list_regions
from core.auth import (
    authorize_url, handle_callback, get_user_client,
    get_user_profile, logout as auth_logout,
)
from core.youtube import get_info as get_yt_info, is_youtube_url
from core.downloader import download_track, SKIP
from core.tagger import tag_file
from core.analyzer import analyze_and_tag, analyze_directory
from core.language import detect_language
from core.watcher import PlaylistWatcher, load_watched, add_playlist, remove_playlist, update_playlist
from core.rekordbox import export_rekordbox_xml
from core.dupes import find_duplicates
from core.scanner import scan_library
from core.crate import build_crate
from core.setcheck import check_set

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="SpotiDL", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Tauri WebView + Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the React build when it exists (production)
_FRONTEND = os.path.join(os.path.dirname(__file__), "tauri-app", "dist")
if os.path.isdir(_FRONTEND):
    app.mount("/app", StaticFiles(directory=_FRONTEND, html=True), name="frontend")

_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="spotidl")
_jobs: dict[str, dict] = {}       # job_id → {status, queue, loop}
_watcher = PlaylistWatcher(quality=DEFAULT_QUALITY)


# ── Pydantic request models ───────────────────────────────────────────────────

class DownloadRequest(BaseModel):
    url: str
    output_dir: str = DEFAULT_OUTPUT_DIR
    quality: str = DEFAULT_QUALITY
    organize: bool = False
    browser: Optional[str] = None
    jobs: int = 4


class PlaylistAddRequest(BaseModel):
    url: str
    folder: Optional[str] = None


class PlaylistUpdateRequest(BaseModel):
    url: str                      # current URL used as identifier
    new_url: Optional[str] = None
    new_name: Optional[str] = None
    new_folder: Optional[str] = None
    reset_ids: bool = False


class AnalyzeRequest(BaseModel):
    directory: str = DEFAULT_OUTPUT_DIR
    force: bool = False


class RekordboxRequest(BaseModel):
    directory: str = DEFAULT_OUTPUT_DIR
    output_path: str = os.path.join(os.path.expanduser("~"), "Desktop", "rekordbox.xml")


class CrateRequest(BaseModel):
    directory: str = DEFAULT_OUTPUT_DIR
    bpm_min: Optional[float] = None
    bpm_max: Optional[float] = None
    key: Optional[str] = None
    energy_min: Optional[float] = None
    output_m3u: Optional[str] = None


class SetCheckRequest(BaseModel):
    url: str
    directory: str = DEFAULT_OUTPUT_DIR


class WatcherStartRequest(BaseModel):
    quality: str = DEFAULT_QUALITY
    browser: Optional[str] = None
    organize: bool = False
    poll_interval_mins: int = 15


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _new_job(loop: asyncio.AbstractEventLoop) -> tuple[str, asyncio.Queue]:
    job_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    _jobs[job_id] = {"status": "running", "queue": queue, "loop": loop}
    return job_id, queue


def _emitter(queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    """Returns a thread-safe emit callable that pushes events into the SSE queue."""
    def emit(event: Optional[dict]):
        loop.call_soon_threadsafe(queue.put_nowait, event)
    return emit


async def _sse(job_id: str):
    """Async generator that yields text/event-stream lines for a job."""
    if job_id not in _jobs:
        yield 'data: {"type":"error","message":"job not found"}\n\n'
        return
    queue = _jobs[job_id]["queue"]
    try:
        while True:
            event = await queue.get()
            if event is None:                       # sentinel — job finished
                yield 'data: {"type":"done"}\n\n'
                break
            yield f"data: {json.dumps(event)}\n\n"
    finally:
        _jobs[job_id]["status"] = "done"


_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                "Connection": "keep-alive"}


def _sse_response(job_id: str) -> StreamingResponse:
    return StreamingResponse(_sse(job_id), media_type="text/event-stream",
                             headers=_SSE_HEADERS)


# ── Tag reader (shared by /library and /scan) ─────────────────────────────────

def _read_mp3_tags(filepath: str) -> dict:
    from mutagen.id3 import ID3, ID3NoHeaderError

    def _t(tags, key):
        f = tags.get(key)
        return str(f.text[0]).strip() if f and hasattr(f, "text") and f.text else ""

    def _x(tags, desc):
        f = tags.get(f"TXXX:{desc}")
        return str(f.text[0]).strip() if f and hasattr(f, "text") and f.text else ""

    def _f(s):
        try:    return float(s)
        except: return None

    try:
        tags = ID3(filepath)
    except Exception:
        return {}

    return {
        "title":        _t(tags, "TIT2"),
        "artist":       _t(tags, "TPE1"),
        "album":        _t(tags, "TALB"),
        "year":         _t(tags, "TDRC")[:4],
        "bpm":          _f(_t(tags, "TBPM")),
        "key":          _t(tags, "TKEY"),
        "camelot":      _x(tags, "CAMELOT"),
        "energy":       _f(_x(tags, "ENERGY")),
        "danceability": _f(_x(tags, "DANCEABILITY")),
        "valence":      _f(_x(tags, "VALENCE")),
        "spotify_bpm":  _f(_x(tags, "SPOTIFY_BPM")),
        "has_cover":    any(k.startswith("APIC") for k in tags.keys()),
    }


# ── General ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.1.0"}


@app.get("/api/config")
async def get_config():
    return {
        "output_dir": DEFAULT_OUTPUT_DIR,
        "quality":    DEFAULT_QUALITY,
        "home":       os.path.expanduser("~"),
        "desktop":    os.path.join(os.path.expanduser("~"), "Desktop"),
    }


@app.get("/api/info")
async def get_info(url: str = Query(..., description="Spotify or YouTube URL")):
    """Fetch metadata for a URL without downloading."""
    loop = asyncio.get_running_loop()
    try:
        fn = get_yt_info if is_youtube_url(url) else get_spotify_info
        info = await loop.run_in_executor(_executor, fn, url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        **{k: v for k, v in info.items() if k != "tracks"},
        "tracks_preview": info["tracks"][:30],
    }


# ── Download ──────────────────────────────────────────────────────────────────

def _download_tracks(tracks: list, output_dir: str, quality: str,
                     organize: bool, browser, jobs: int, emit, name: str = "Selection"):
    """Shared loop for downloading a list of track dicts with SSE event emission."""
    emit({"type": "start", "name": name, "total": len(tracks)})

    downloaded = skipped = failed = 0
    failed_tracks = []

    def _process(track: dict):
        nonlocal downloaded, skipped, failed
        emit({"type": "track_start",
              "artist": track["artist"], "title": track["title"]})

        track_dir = output_dir
        if organize:
            lang      = detect_language(track["artist"], track["title"])
            track_dir = os.path.join(output_dir, lang)

        path = download_track(track, track_dir, quality, cookies_browser=browser)
        if path == SKIP:
            skipped += 1
            emit({"type": "track_done", "status": "skip",
                  "artist": track["artist"], "title": track["title"]})
        elif path is None:
            failed += 1
            failed_tracks.append(track)
            emit({"type": "track_done", "status": "fail",
                  "artist": track["artist"], "title": track["title"]})
        else:
            tag_file(path, track)
            analysis = analyze_and_tag(path)
            downloaded += 1
            emit({"type": "track_done", "status": "ok",
                  "artist": track["artist"], "title": track["title"], "path": path,
                  "bpm": analysis.get("bpm"), "key": analysis.get("key"),
                  "camelot": analysis.get("camelot")})

    n = min(len(tracks), jobs) if tracks else 0
    if n <= 1:
        for t in tracks:
            _process(t)
    else:
        with ThreadPoolExecutor(max_workers=n) as pool:
            for fut in futures_done({pool.submit(_process, t): t for t in tracks}):
                try:
                    fut.result()
                except Exception:
                    pass

    emit({"type": "summary", "downloaded": downloaded,
          "skipped": skipped, "failed": failed,
          "failed_tracks": [{"artist": t["artist"], "title": t["title"]}
                            for t in failed_tracks]})


@app.post("/api/download")
async def start_download(req: DownloadRequest):
    """Download an entire Spotify or YouTube playlist/album/track."""
    loop = asyncio.get_running_loop()
    job_id, queue = _new_job(loop)
    emit = _emitter(queue, loop)

    def _run():
        try:
            fn   = get_yt_info if is_youtube_url(req.url) else get_spotify_info
            info = fn(req.url)
            _download_tracks(info["tracks"], req.output_dir, req.quality,
                             req.organize, req.browser, req.jobs, emit,
                             name=info["name"])
        except Exception as e:
            emit({"type": "error", "message": str(e)})
        finally:
            emit(None)

    loop.run_in_executor(_executor, _run)
    return {"job_id": job_id}


class DownloadTracksRequest(BaseModel):
    track_ids: list[str]
    output_dir: str = DEFAULT_OUTPUT_DIR
    quality:    str = DEFAULT_QUALITY
    organize:   bool = False
    browser:    Optional[str] = None
    jobs:       int = 4
    name:       Optional[str] = None


@app.post("/api/download-tracks")
async def start_download_tracks(req: DownloadTracksRequest):
    """Download a custom selection of Spotify tracks by ID list."""
    loop = asyncio.get_running_loop()
    job_id, queue = _new_job(loop)
    emit = _emitter(queue, loop)

    def _run():
        try:
            tracks = get_tracks_by_ids(req.track_ids)
            if not tracks:
                emit({"type": "error", "message": "No valid tracks resolved from IDs"})
                return
            _download_tracks(tracks, req.output_dir, req.quality,
                             req.organize, req.browser, req.jobs, emit,
                             name=req.name or f"Selection ({len(tracks)})")
        except Exception as e:
            emit({"type": "error", "message": str(e)})
        finally:
            emit(None)

    loop.run_in_executor(_executor, _run)
    return {"job_id": job_id}


# ── Trending ──────────────────────────────────────────────────────────────────

@app.get("/api/trending/regions")
async def trending_regions():
    return list_regions()


@app.get("/api/trending")
async def trending(region: str = Query("bollywood")):
    """Fetch the current trending Spotify playlist for a region."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(_executor, get_trending, region, 50)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Spotify OAuth ─────────────────────────────────────────────────────────────

@app.get("/api/auth/status")
async def auth_status():
    profile = get_user_profile()
    return {"authenticated": bool(profile), "profile": profile}


@app.get("/api/auth/login")
async def auth_login():
    """Returns the Spotify authorization URL for the frontend to open."""
    return {"url": authorize_url()}


@app.get("/api/auth/callback")
async def auth_callback(code: Optional[str] = None, error: Optional[str] = None):
    """Spotify redirects here after the user authorizes (or denies) the app."""
    if error:
        return HTMLResponse(_auth_html(False, error), status_code=400)
    if not code:
        return HTMLResponse(_auth_html(False, "Missing code"), status_code=400)
    try:
        handle_callback(code)
        return HTMLResponse(_auth_html(True))
    except Exception as e:
        return HTMLResponse(_auth_html(False, str(e)), status_code=500)


@app.post("/api/auth/logout")
async def auth_logout_endpoint():
    auth_logout()
    return {"authenticated": False}


_AUTH_OK_HTML = """<!doctype html><html><body style="font-family:-apple-system,sans-serif;
background:#0d0d0d;color:#f0f0f0;display:flex;align-items:center;justify-content:center;
height:100vh;margin:0;flex-direction:column;gap:16px;">
<div style="font-size:48px;color:#1db954;">&#10003;</div>
<h1 style="font-weight:600;margin:0;">Connected to Spotify</h1>
<p style="color:#888;margin:0;">You can close this window and return to SpotiDL.</p>
<script>setTimeout(()=>window.close(),1500);</script>
</body></html>"""


def _auth_html(ok: bool, error: str = "") -> str:
    """Self-closing HTML page shown after the Spotify auth redirect."""
    if ok:
        return _AUTH_OK_HTML
    return (
        '<!doctype html><html><body style="font-family:-apple-system,sans-serif;'
        'background:#0d0d0d;color:#f0f0f0;display:flex;align-items:center;'
        'justify-content:center;height:100vh;margin:0;flex-direction:column;gap:12px;">'
        '<div style="font-size:48px;color:#ef4444;">&#10005;</div>'
        '<h1 style="font-weight:600;margin:0;">Authorization failed</h1>'
        f'<p style="color:#888;max-width:480px;text-align:center;">{error}</p>'
        '<p style="color:#666;font-size:12px;max-width:480px;text-align:center;">'
        'Make sure <code style="background:#1f1f1f;padding:2px 6px;border-radius:4px;">'
        'http://127.0.0.1:8765/api/auth/callback</code> is added to your Spotify app\'s '
        'Redirect URIs at developer.spotify.com/dashboard.</p>'
        '</body></html>'
    )


# ── User Spotify playlists (write access) ─────────────────────────────────────

class CreatePlaylistRequest(BaseModel):
    name:        str
    description: str = ""
    public:      bool = False


class AddTracksToPlaylistRequest(BaseModel):
    playlist_id: str
    track_ids:   list[str]


@app.get("/api/spotify/playlists")
async def list_user_playlists():
    sp = get_user_client()
    if not sp:
        raise HTTPException(status_code=401, detail="Not authenticated with Spotify")

    def _fetch():
        results = sp.current_user_playlists(limit=50)
        return [
            {
                "id":            p["id"],
                "name":          p["name"],
                "tracks_total":  p["tracks"]["total"],
                "url":           (p.get("external_urls") or {}).get("spotify"),
                "cover_url":     (p["images"][0]["url"] if p.get("images") else None),
                "owner":         (p.get("owner") or {}).get("display_name", ""),
                "collaborative": p.get("collaborative", False),
                "public":        p.get("public", False),
            }
            for p in (results.get("items") or [])
        ]

    loop = asyncio.get_running_loop()
    return {"playlists": await loop.run_in_executor(_executor, _fetch)}


@app.post("/api/spotify/playlists")
async def create_user_playlist(req: CreatePlaylistRequest):
    sp = get_user_client()
    if not sp:
        raise HTTPException(status_code=401, detail="Not authenticated with Spotify")
    loop = asyncio.get_running_loop()

    def _create():
        user = sp.current_user()
        pl   = sp.user_playlist_create(
            user["id"], req.name, public=req.public, description=req.description
        )
        return {
            "id":           pl["id"],
            "name":         pl["name"],
            "url":          (pl.get("external_urls") or {}).get("spotify"),
            "tracks_total": 0,
        }

    return await loop.run_in_executor(_executor, _create)


@app.post("/api/spotify/playlists/add-tracks")
async def add_tracks_to_user_playlist(req: AddTracksToPlaylistRequest):
    sp = get_user_client()
    if not sp:
        raise HTTPException(status_code=401, detail="Not authenticated with Spotify")
    if not req.track_ids:
        raise HTTPException(status_code=400, detail="track_ids is empty")

    def _add():
        uris = [f"spotify:track:{tid}" for tid in req.track_ids]
        # Spotify limits playlist_add_items to 100 per call
        for i in range(0, len(uris), 100):
            sp.playlist_add_items(req.playlist_id, uris[i : i + 100])
        return {"added": len(uris)}

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _add)


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    """SSE stream for a running download or analyze job."""
    return _sse_response(job_id)


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, "status": _jobs[job_id]["status"]}


# ── Library ───────────────────────────────────────────────────────────────────

@app.get("/api/library")
async def get_library(dir: str = Query(default=DEFAULT_OUTPUT_DIR)):
    """List all MP3s in the directory with their ID3 tags."""
    if not os.path.isdir(dir):
        raise HTTPException(status_code=404, detail="Directory not found")

    def _scan():
        result = []
        for root, dirs, files in os.walk(dir):
            dirs.sort()
            for fname in sorted(files):
                if fname.lower().endswith(".mp3"):
                    fpath = os.path.join(root, fname)
                    result.append({
                        "path": fpath,
                        "filename": fname,
                        "size_kb": os.path.getsize(fpath) // 1024,
                        **_read_mp3_tags(fpath),
                    })
        return result

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _scan)


@app.get("/api/scan")
async def tag_scan(dir: str = Query(default=DEFAULT_OUTPUT_DIR)):
    """Find MP3s with incomplete ID3 tags."""
    if not os.path.isdir(dir):
        raise HTTPException(status_code=404, detail="Directory not found")
    loop = asyncio.get_running_loop()
    issues = await loop.run_in_executor(_executor, scan_library, dir)
    return {"total": len(issues), "issues": issues}


@app.get("/api/dupes")
async def dupe_scan(dir: str = Query(default=DEFAULT_OUTPUT_DIR)):
    """Find duplicate MP3s by hash and tag match."""
    if not os.path.isdir(dir):
        raise HTTPException(status_code=404, detail="Directory not found")
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(_executor, find_duplicates, dir)
    return {
        "by_hash_count": len(result["by_hash"]),
        "by_tags_count": len(result["by_tags"]),
        **result,
    }


@app.post("/api/analyze")
async def start_analyze(req: AnalyzeRequest):
    """Start batch BPM + key analysis. Stream progress via /api/jobs/{id}/events."""
    if not os.path.isdir(req.directory):
        raise HTTPException(status_code=404, detail="Directory not found")
    loop = asyncio.get_running_loop()
    job_id, queue = _new_job(loop)
    emit = _emitter(queue, loop)

    def _run():
        try:
            analyzed = skipped = 0
            for fpath, result in analyze_directory(req.directory, force=req.force):
                if result:
                    analyzed += 1
                    emit({"type": "analyzed", "path": fpath,
                          "file": os.path.basename(fpath),
                          "bpm": result.get("bpm"),
                          "key": result.get("key"),
                          "camelot": result.get("camelot")})
                else:
                    skipped += 1
            emit({"type": "summary", "analyzed": analyzed, "skipped": skipped})
        except Exception as e:
            emit({"type": "error", "message": str(e)})
        finally:
            emit(None)

    loop.run_in_executor(_executor, _run)
    return {"job_id": job_id}


@app.post("/api/rekordbox")
async def rekordbox_export(req: RekordboxRequest):
    """Export library as Rekordbox-compatible XML."""
    if not os.path.isdir(req.directory):
        raise HTTPException(status_code=404, detail="Directory not found")
    loop = asyncio.get_running_loop()
    count = await loop.run_in_executor(
        _executor, export_rekordbox_xml, req.directory, req.output_path
    )
    if count == 0:
        raise HTTPException(status_code=404, detail="No MP3 files found in directory")
    return {"exported": count, "path": req.output_path}


@app.post("/api/crate")
async def build_crate_endpoint(req: CrateRequest):
    """Filter library by BPM / key / energy and optionally save as M3U."""
    if not os.path.isdir(req.directory):
        raise HTTPException(status_code=404, detail="Directory not found")
    loop = asyncio.get_running_loop()
    paths = await loop.run_in_executor(
        _executor,
        lambda: build_crate(req.directory, bpm_min=req.bpm_min, bpm_max=req.bpm_max,
                             key=req.key, energy_min=req.energy_min,
                             output_m3u=req.output_m3u),
    )
    return {"count": len(paths), "tracks": paths, "m3u": req.output_m3u}


@app.post("/api/setcheck")
async def setcheck_endpoint(req: SetCheckRequest):
    """Compare a Spotify playlist against the local library."""
    loop = asyncio.get_running_loop()
    try:
        info = await loop.run_in_executor(_executor, get_spotify_info, req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    result = await loop.run_in_executor(_executor, check_set, info["tracks"], req.directory)
    return {
        "playlist":      info["name"],
        "total":         info["total_tracks"],
        "found":         len(result["found"]),
        "missing":       len(result["missing"]),
        "found_tracks":  result["found"],
        "missing_tracks": result["missing"],
    }


# ── Watcher ───────────────────────────────────────────────────────────────────

@app.get("/api/watcher/status")
async def watcher_status():
    return {
        "running":       _watcher.is_running(),
        "poll_interval": _watcher.poll_interval,
        "playlists":     len(load_watched()["playlists"]),
    }


@app.post("/api/watcher/start")
async def watcher_start(req: WatcherStartRequest):
    _watcher.quality       = req.quality
    _watcher.browser       = req.browser
    _watcher.organize      = req.organize
    _watcher.poll_interval = req.poll_interval_mins * 60
    if not _watcher.is_running():
        _watcher.start()
    return {"running": True}


@app.post("/api/watcher/stop")
async def watcher_stop():
    _watcher.stop()
    return {"running": False}


@app.post("/api/watcher/check")
async def watcher_check():
    if not _watcher.is_running():
        raise HTTPException(status_code=400, detail="Watcher is not running — start it first")
    _watcher.check_now()
    return {"triggered": True}


_RICH_TAG = re.compile(r"\[/?[a-z0-9_ ]+\]")


def _strip_rich(s: str) -> str:
    """Strip Rich console markup tags like [bold red]…[/bold red] from a string."""
    return _RICH_TAG.sub("", s)


@app.get("/api/watcher/events")
async def watcher_events():
    """SSE stream that forwards watcher notifications in real time."""
    async def _stream():
        while True:
            while not _watcher.notifications.empty():
                try:
                    msg = _strip_rich(_watcher.notifications.get_nowait())
                    yield f"data: {json.dumps({'type': 'notification', 'message': msg})}\n\n"
                except Exception:
                    break
            await asyncio.sleep(0.5)

    return StreamingResponse(_stream(), media_type="text/event-stream",
                             headers=_SSE_HEADERS)


# ── Playlists (watched) ───────────────────────────────────────────────────────

@app.get("/api/playlists")
async def list_playlists():
    return load_watched()


@app.post("/api/playlists")
async def create_playlist(req: PlaylistAddRequest):
    loop = asyncio.get_running_loop()
    try:
        info = await loop.run_in_executor(_executor, get_spotify_info, req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    folder = req.folder or os.path.join(DEFAULT_OUTPUT_DIR, info["name"])
    return add_playlist(req.url, info["name"], folder, total_tracks=info["total_tracks"])


@app.put("/api/playlists")
async def update_playlist_endpoint(req: PlaylistUpdateRequest):
    ok = update_playlist(
        req.url,
        new_url=req.new_url, new_name=req.new_name,
        new_folder=req.new_folder, reset_ids=req.reset_ids,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return {"updated": True}


@app.delete("/api/playlists")
async def delete_playlist(url: str = Query(...)):
    if not remove_playlist(url):
        raise HTTPException(status_code=404, detail="Playlist not found")
    return {"deleted": True}


# ── Entry point ───────────────────────────────────────────────────────────────

def start():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")


if __name__ == "__main__":
    start()
