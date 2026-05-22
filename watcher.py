import json
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import psutil

from spotify_client import get_playlist_info
from downloader import download_track, SKIP
from tagger import tag_file
from language import detect_language

_CONFIG_DIR  = os.path.expanduser("~/.spotidl")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "watched.json")

_DEFAULT_POLL_INTERVAL = 900   # 15 minutes
_CPU_BACKOFF_THRESHOLD = 75    # % — pause downloads above this
_MAX_WORKERS           = 2     # parallel downloads while watching


def load_watched() -> dict:
    if not os.path.exists(_CONFIG_FILE):
        return {"playlists": []}
    with open(_CONFIG_FILE) as f:
        return json.load(f)


def save_watched(config: dict):
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    with open(_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def add_playlist(url: str, name: str, folder: str) -> dict:
    config = load_watched()
    for entry in config["playlists"]:
        if entry["url"] == url:
            entry["folder"] = folder
            entry["name"]   = name
            save_watched(config)
            return entry
    entry = {"url": url, "name": name, "folder": folder, "downloaded_ids": []}
    config["playlists"].append(entry)
    save_watched(config)
    return entry


def remove_playlist(url: str) -> bool:
    config = load_watched()
    before = len(config["playlists"])
    config["playlists"] = [p for p in config["playlists"] if p["url"] != url]
    if len(config["playlists"]) < before:
        save_watched(config)
        return True
    return False


class PlaylistWatcher:
    def __init__(self, quality: str, browser: str = None,
                 poll_interval: int = _DEFAULT_POLL_INTERVAL, organize: bool = False):
        self.quality       = quality
        self.browser       = browser
        self.poll_interval = poll_interval
        self.organize      = organize
        self.notifications = queue.Queue()
        self._stop_event   = threading.Event()
        self._check_event  = threading.Event()
        self._thread       = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="playlist-watcher"
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._check_event.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def check_now(self):
        self._check_event.set()

    def _loop(self):
        self._check_event.set()  # run immediately on start
        while not self._stop_event.is_set():
            self._check_event.wait(timeout=self.poll_interval)
            self._check_event.clear()
            if self._stop_event.is_set():
                break
            try:
                self._check_playlists()
            except Exception as e:
                self.notifications.put(f"[bold red]Watcher error:[/bold red] {e}")

    def _wait_for_cpu(self):
        cpu = psutil.cpu_percent(interval=0.5)
        while cpu > _CPU_BACKOFF_THRESHOLD and not self._stop_event.is_set():
            time.sleep(5)
            cpu = psutil.cpu_percent(interval=0.5)

    def _check_playlists(self):
        config = load_watched()
        if not config["playlists"]:
            return

        for entry in config["playlists"]:
            if self._stop_event.is_set():
                break

            self._wait_for_cpu()

            try:
                info = get_playlist_info(entry["url"])
            except Exception as e:
                self.notifications.put(
                    f"[yellow]Watcher:[/yellow] Failed to fetch "
                    f"[bright_cyan]{entry['name']}[/bright_cyan]: {e}"
                )
                continue

            known_ids  = set(entry.get("downloaded_ids", []))
            new_tracks = [t for t in info["tracks"] if t["id"] and t["id"] not in known_ids]

            if not new_tracks:
                continue

            self.notifications.put(
                f"[bright_cyan]Watcher:[/bright_cyan] "
                f"[bold bright_yellow]{len(new_tracks)}[/bold bright_yellow] "
                f"new track{'s' if len(new_tracks) != 1 else ''} in "
                f"[bold bright_magenta]{entry['name']}[/bold bright_magenta] — downloading..."
            )

            newly_done = []
            failed_ids = []

            def _download_one(track: dict):
                self._wait_for_cpu()
                if self._stop_event.is_set():
                    return track["id"], "stop"

                folder = entry["folder"]
                if self.organize:
                    lang   = detect_language(track["artist"], track["title"])
                    folder = os.path.join(folder, lang)

                path = download_track(track, folder, self.quality, cookies_browser=self.browser)
                if path and path != SKIP:
                    tag_file(path, track)
                    return track["id"], "ok"
                elif path == SKIP:
                    return track["id"], "skip"
                else:
                    return track["id"], "fail"

            with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
                futures = [ex.submit(_download_one, t) for t in new_tracks]
                for future in as_completed(futures):
                    if self._stop_event.is_set():
                        break
                    try:
                        tid, status = future.result()
                        if status in ("ok", "skip"):
                            newly_done.append(tid)
                        elif status == "fail":
                            failed_ids.append(tid)
                    except Exception:
                        pass
                    time.sleep(1)  # gentle rate limiting

            if newly_done:
                config = load_watched()
                for e in config["playlists"]:
                    if e["url"] == entry["url"]:
                        existing = set(e.get("downloaded_ids", []))
                        existing.update(newly_done)
                        e["downloaded_ids"] = list(existing)
                        break
                save_watched(config)
                entry["downloaded_ids"] = list(
                    set(entry.get("downloaded_ids", [])) | set(newly_done)
                )

            ok_count   = len(newly_done)
            fail_count = len(failed_ids)
            msg = (
                f"[bright_cyan]Watcher:[/bright_cyan] Done for "
                f"[bold bright_magenta]{entry['name']}[/bold bright_magenta] — "
                f"[bold bright_green]{ok_count}[/bold bright_green] downloaded"
            )
            if fail_count:
                msg += f"  [bold bright_red]{fail_count}[/bold bright_red] failed"
            self.notifications.put(msg)
