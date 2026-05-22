import os
import sys
import warnings
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")

import pyfiglet
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress, SpinnerColumn, BarColumn, TextColumn,
    TimeElapsedColumn, MofNCompleteColumn, TaskProgressColumn,
)
from rich.table import Table
from rich.rule import Rule
from rich.align import Align
from rich import box

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style as PtStyle
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.completion import Completer, Completion

from core.config import DEFAULT_OUTPUT_DIR, DEFAULT_QUALITY, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from core.spotify_client import get_info as get_spotify_info
from core.youtube import get_info as get_yt_info, is_youtube_url
from core.downloader import download_track, SKIP
from core.tagger import tag_file
from core.recognizer import record_and_identify, identify_file
from core.search import search_tracks, search_albums
from core.language import detect_language
from core.monitor import ResourceColumn, run_monitor
from core.watcher import PlaylistWatcher, load_watched, add_playlist, remove_playlist, update_playlist
from core.analyzer import analyze_and_tag, analyze_directory
from core.rekordbox import export_rekordbox_xml
from core.dupes import find_duplicates
from core.scanner import scan_library
from core.crate import build_crate
from core.setcheck import check_set

console = Console()

_BANNER_COLORS = [
    "bold bright_cyan",
    "bold bright_magenta",
    "bold bright_yellow",
    "bold bright_green",
    "bold cyan",
    "bold magenta",
]
_TYPE_COLOR = {"playlist": "bright_cyan", "album": "bright_magenta", "track": "bright_yellow"}
_TYPE_ICON  = {"playlist": "♬", "album": "◉", "track": "♪"}


def print_banner():
    lines = [l for l in pyfiglet.figlet_format("SpotiDL", font="slant").split("\n") if l.strip()]
    console.print()
    for i, line in enumerate(lines):
        console.print(f"[{_BANNER_COLORS[i % len(_BANNER_COLORS)]}]{line}[/{_BANNER_COLORS[i % len(_BANNER_COLORS)]}]")
    console.print()
    console.print(Align.center(
        "[bold bright_white on blue]  ♪  Download Spotify Music as MP3s via YouTube  ♪  [/bold bright_white on blue]"
    ))
    console.print()
    console.print(Rule(style="bright_blue"))
    console.print()


_PT_STYLE = PtStyle.from_dict({
    "prompt":         "bold ansicyan",
    "":               "ansiwhite",
    "bottom-toolbar": "bg:ansiblue fg:ansiwhite bold",
})

_SLASH_COMMANDS = [
    ("\\shazam",     "Listen via mic & identify song"),
    ("\\song",       "Search track by title"),
    ("\\album",      "Browse album & download tracks"),
    ("\\organize",   "Toggle Language/ subfolder sorting"),
    ("\\monitor",    "Live CPU / RAM / temperature display"),
    ("\\configure",  "Manage watched playlists & auto-download"),
    ("\\analyze",    "Detect BPM + key for untagged MP3s in library"),
    ("\\rekordbox",  "Export library to Rekordbox XML for Pioneer CDJs"),
    ("\\dupes",      "Find duplicate tracks in your library"),
    ("\\scan",       "Find tracks with missing BPM, key, or art"),
    ("\\crate",      "Build a filtered DJ crate and save as M3U"),
    ("\\setcheck",   "Check which Spotify playlist tracks you already have"),
]


class _SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("\\"):
            return
        for cmd, meta in _SLASH_COMMANDS:
            if cmd.startswith(text):
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display=cmd,
                    display_meta=meta,
                )


def get_url_interactive(organize: bool = False, watcher_running: bool = False) -> str:
    kb = KeyBindings()

    @kb.add("escape")
    def _quit(event):
        event.app.exit(result=None)

    badges = ""
    if organize:
        badges += "  <b>[organize: ON]</b>"
    if watcher_running:
        badges += "  <b>[watcher: ON]</b>"
    toolbar = HTML(f"  <b>\\</b>  commands      <b>ENTER</b>  download{badges}      <b>ESC</b>  exit  ")

    session = PromptSession(
        style=_PT_STYLE,
        key_bindings=kb,
        bottom_toolbar=toolbar,
        completer=_SlashCompleter(),
        complete_while_typing=True,
    )
    try:
        result = session.prompt(
            HTML("<ansicyan><b>  ♪  URL or \\command  ›  </b></ansicyan>")
        )
    except (KeyboardInterrupt, EOFError):
        result = None

    return result.strip() if result else None


def _prompt_simple(msg: str, default: str = "") -> str:
    kb = KeyBindings()

    @kb.add("escape")
    def _quit(event):
        event.app.exit(result=None)

    session = PromptSession(style=_PT_STYLE, key_bindings=kb)
    try:
        result = session.prompt(
            HTML(f"<ansicyan><b>  {msg}  ›  </b></ansicyan>"),
            default=default,
        )
    except (KeyboardInterrupt, EOFError):
        result = None
    return result.strip() if result else None


def _ms_to_mmss(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


def _parse_track_selection(text: str, total: int):
    text = text.strip().lower()
    if not text or text == "all":
        return list(range(total))
    indices = set()
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                lo, hi = int(a.strip()), int(b.strip())
                indices.update(range(max(1, lo) - 1, min(total, hi)))
            except ValueError:
                pass
        else:
            try:
                n = int(part)
                if 1 <= n <= total:
                    indices.add(n - 1)
            except ValueError:
                pass
    return sorted(indices)


def check_credentials():
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        console.print(Panel(
            "[bold red]Missing Spotify credentials.[/bold red]\n\n"
            "Create a [bold].env[/bold] file with:\n"
            "  [yellow]SPOTIFY_CLIENT_ID[/yellow]=[bright_green]your_client_id[/bright_green]\n"
            "  [yellow]SPOTIFY_CLIENT_SECRET[/yellow]=[bright_green]your_client_secret[/bright_green]\n\n"
            "Get credentials at [link=https://developer.spotify.com/dashboard]"
            "[bright_cyan]developer.spotify.com/dashboard[/bright_cyan][/link]",
            title="[bold red]  !!  Setup Required  !!  [/bold red]",
            border_style="red",
            box=box.DOUBLE_EDGE,
        ))
        sys.exit(1)


def print_source_info(info: dict):
    color = _TYPE_COLOR.get(info["type"], "bright_white")
    icon  = _TYPE_ICON.get(info["type"], "♫")

    t = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    t.add_column(style=f"bold {color}", min_width=10)
    t.add_column(style="bright_white")

    t.add_row(f"{icon}  {info['type'].capitalize()}", f"[bold]{info['name']}[/bold]")
    label = "Owner" if info["type"] == "playlist" else "Artist"
    t.add_row(f"*  {label}", info["owner"])
    t.add_row(f"#  Tracks", f"[bold bright_yellow]{info['total_tracks']}[/bold bright_yellow]")
    if info.get("description"):
        t.add_row(f"»  Info", info["description"][:80])

    console.print(Panel(
        t,
        title=f"[bold {color}]  {icon}  {info['name']}  {icon}  [/bold {color}]",
        border_style=color,
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
    ))


def print_track_table(tracks: list):
    t = Table(
        show_header=True,
        header_style="bold bright_white on blue",
        box=box.HEAVY_HEAD,
        border_style="bright_blue",
        row_styles=["", "on grey11"],
        padding=(0, 1),
    )
    t.add_column("#",      style="bold bright_yellow", width=4,  justify="right")
    t.add_column("Artist", style="bright_cyan",        max_width=30)
    t.add_column("Title",  style="bright_white",       max_width=40)
    t.add_column("Album",  style="dim",                max_width=25)

    preview = tracks[:20]
    for i, tr in enumerate(preview, 1):
        t.add_row(str(i), tr["artist"][:28], tr["title"][:38], tr["album"][:23])

    if len(tracks) > 20:
        t.add_row("...", f"[dim]and {len(tracks) - 20} more[/dim]", "", "")

    console.print(Panel(
        t,
        title="[bold bright_blue]  ♬  Track List  ♬  [/bold bright_blue]",
        border_style="bright_blue",
        box=box.DOUBLE_EDGE,
    ))


def step_print(n: int, total: int, msg: str):
    console.print(
        f"  [bold bright_black][[/bold bright_black]"
        f"[bold bright_cyan]{n}[/bold bright_cyan]"
        f"[bold bright_black]/[/bold bright_black]"
        f"[bold bright_cyan]{total}[/bold bright_cyan]"
        f"[bold bright_black]][/bold bright_black]  "
        f"[bright_white]{msg}[/bright_white]"
    )


def print_search_results(results: list):
    t = Table(
        show_header=True,
        header_style="bold bright_white on blue",
        box=box.HEAVY_HEAD,
        border_style="bright_blue",
        row_styles=["", "on grey11"],
        padding=(0, 1),
    )
    t.add_column("#",      style="bold bright_yellow", width=4,  justify="right")
    t.add_column("Artist", style="bright_cyan",        max_width=28)
    t.add_column("Title",  style="bold bright_white",  max_width=38)
    t.add_column("Album",  style="dim",                max_width=25)
    t.add_column("Time",   style="dim",                width=6, justify="right")
    for i, tr in enumerate(results, 1):
        t.add_row(
            str(i),
            tr["artist"][:26],
            tr["title"][:36],
            tr["album"][:23],
            _ms_to_mmss(tr.get("duration_ms", 0)),
        )
    console.print(Panel(
        t,
        title="[bold bright_blue]  ♬  Search Results  ♬  [/bold bright_blue]",
        border_style="bright_blue",
        box=box.DOUBLE_EDGE,
    ))


def print_album_results(albums: list):
    t = Table(
        show_header=True,
        header_style="bold bright_white on blue",
        box=box.HEAVY_HEAD,
        border_style="bright_magenta",
        row_styles=["", "on grey11"],
        padding=(0, 1),
    )
    t.add_column("#",      style="bold bright_yellow", width=4,  justify="right")
    t.add_column("Artist", style="bright_cyan",        max_width=28)
    t.add_column("Album",  style="bold bright_white",  max_width=35)
    t.add_column("Year",   style="dim",                width=6, justify="right")
    t.add_column("Tracks", style="bright_yellow",      width=7, justify="right")
    for i, al in enumerate(albums, 1):
        t.add_row(str(i), al["artist"][:26], al["name"][:33], al["year"], str(al["total_tracks"]))
    console.print(Panel(
        t,
        title="[bold bright_magenta]  ◉  Albums Found  ◉  [/bold bright_magenta]",
        border_style="bright_magenta",
        box=box.DOUBLE_EDGE,
    ))


def run_song_search(query: str, output_dir: str, quality: str, browser: str = None, organize: bool = False):
    check_credentials()

    if not query:
        console.print()
        query = _prompt_simple("♪  Search for a song")
        if not query:
            console.print("\n  [dim]Cancelled.[/dim]\n")
            return

    console.print()
    step_print(1, 3, f"Searching Spotify  [dim]{query}[/dim]")

    try:
        results = search_tracks(query)
    except Exception as e:
        console.print(f"\n  [bold bright_red]!!  Search failed:[/bold bright_red] [red]{e}[/red]\n")
        return

    if not results:
        console.print("\n  [yellow]No results found.[/yellow]\n")
        return

    console.print()
    print_search_results(results)
    console.print()

    choice_str = _prompt_simple(f"♪  Pick a track (1–{len(results)})")
    if not choice_str:
        console.print("\n  [dim]Cancelled.[/dim]\n")
        return

    try:
        choice = int(choice_str)
        if not 1 <= choice <= len(results):
            raise ValueError
    except ValueError:
        console.print("\n  [bold red]Invalid choice.[/bold red]\n")
        return

    track = results[choice - 1]
    label_rich = (
        f"[bright_cyan]{track['artist'][:30]}[/bright_cyan]"
        f"[dim] - [/dim]"
        f"[bright_white]{track['title'][:40]}[/bright_white]"
    )
    console.print()
    step_print(2, 3, f"Selected  {label_rich}")
    console.print()

    if organize:
        lang = detect_language(track["artist"], track["title"])
        track_dir = os.path.join(output_dir, lang)
        console.print(f"  [dim]Language:[/dim] [bold bright_magenta]{lang}[/bold bright_magenta]")
        console.print()
    else:
        track_dir = output_dir

    step_print(3, 3, f"Downloading to [bright_cyan]{track_dir}[/bright_cyan]")
    console.print()

    path = download_track(track, track_dir, quality, cookies_browser=browser)
    if path == SKIP:
        console.print(f"  [bold yellow]o[/bold yellow]  {label_rich}  [dim yellow](already exists, skipped)[/dim yellow]")
    elif path is None:
        console.print(f"  [bold bright_red]x[/bold bright_red]  {label_rich}  [dim red](failed)[/dim red]")
    else:
        tag_file(path, track)
        analysis = analyze_and_tag(path)
        bpm_tag  = (f"  [dim cyan]{analysis['bpm']:.0f}bpm {analysis.get('camelot', '')}[/dim cyan]"
                    if analysis else "")
        console.print(f"  [bold bright_green]v[/bold bright_green]  {label_rich}{bpm_tag}")

    console.print()
    console.print(f"  [dim]Saved to[/dim] [bright_cyan]{track_dir}[/bright_cyan]")
    console.print()


def run_album_search(query: str, output_dir: str, quality: str, browser: str = None, organize: bool = False):
    check_credentials()

    if not query:
        console.print()
        query = _prompt_simple("◉  Search for an album")
        if not query:
            console.print("\n  [dim]Cancelled.[/dim]\n")
            return

    console.print()
    step_print(1, 4, f"Searching Spotify  [dim]{query}[/dim]")

    try:
        albums = search_albums(query)
    except Exception as e:
        console.print(f"\n  [bold bright_red]!!  Search failed:[/bold bright_red] [red]{e}[/red]\n")
        return

    if not albums:
        console.print("\n  [yellow]No albums found.[/yellow]\n")
        return

    console.print()
    print_album_results(albums)
    console.print()

    choice_str = _prompt_simple(f"◉  Pick an album (1–{len(albums)})")
    if not choice_str:
        console.print("\n  [dim]Cancelled.[/dim]\n")
        return

    try:
        choice = int(choice_str)
        if not 1 <= choice <= len(albums):
            raise ValueError
    except ValueError:
        console.print("\n  [bold red]Invalid choice.[/bold red]\n")
        return

    album = albums[choice - 1]
    console.print()
    step_print(2, 4, f"Fetching tracks for  [bold bright_magenta]{album['name']}[/bold bright_magenta]")

    try:
        info = get_spotify_info(album["spotify_url"])
    except Exception as e:
        console.print(f"\n  [bold bright_red]!!  Failed:[/bold bright_red] [red]{e}[/red]\n")
        return

    console.print()
    print_source_info(info)
    console.print()
    print_track_table(info["tracks"])
    console.print()

    sel_str = _prompt_simple("◉  Tracks to download  (all / 1 / 2-5 / 1,3,5)", default="all")
    if sel_str is None:
        console.print("\n  [dim]Cancelled.[/dim]\n")
        return

    indices = _parse_track_selection(sel_str, len(info["tracks"]))
    if not indices:
        console.print("\n  [yellow]No valid tracks selected.[/yellow]\n")
        return

    tracks = [info["tracks"][i] for i in indices]
    jobs = min(len(tracks), 4)
    worker_str = f"[bold bright_magenta]{jobs}[/bold bright_magenta] worker{'s' if jobs != 1 else ''}"
    console.print()
    step_print(3, 4, f"Downloading [bold bright_yellow]{len(tracks)}[/bold bright_yellow] track{'s' if len(tracks) != 1 else ''} with {worker_str}")
    console.print()

    pending = tracks
    attempt = 0

    while True:
        attempt  += 1
        cur_jobs  = min(len(pending), jobs)
        downloaded = skipped = 0
        failed_tracks = []

        with Progress(
            SpinnerColumn(spinner_name="dots2", style="bright_cyan"),
            TextColumn("[bold bright_white]{task.description}"),
            BarColumn(bar_width=28, style="bright_blue", complete_style="bright_green", finished_style="bright_green"),
            TaskProgressColumn(style="bold bright_yellow"),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            ResourceColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task("[bright_cyan]Downloading[/bright_cyan]", total=len(pending))

            def _process(track: dict) -> str:
                label_rich = (
                    f"[bright_cyan]{track['artist'][:30]}[/bright_cyan]"
                    f"[dim] - [/dim]"
                    f"[bright_white]{track['title'][:40]}[/bright_white]"
                )
                if organize:
                    lang = detect_language(track["artist"], track["title"])
                    track_dir = os.path.join(output_dir, lang)
                    lang_tag = f"  [dim magenta]{lang}[/dim magenta]"
                else:
                    track_dir = output_dir
                    lang_tag = ""
                path = download_track(track, track_dir, quality, cookies_browser=browser)
                if path == SKIP:
                    console.print(f"  [bold yellow]o[/bold yellow]  {label_rich}{lang_tag}  [dim yellow](skipped)[/dim yellow]")
                    status = "skip"
                elif path is None:
                    console.print(f"  [bold bright_red]x[/bold bright_red]  {label_rich}{lang_tag}  [dim red](failed)[/dim red]")
                    failed_tracks.append(track)
                    status = "fail"
                else:
                    tag_file(path, track)
                    analysis = analyze_and_tag(path)
                    bpm_tag  = (f"  [dim cyan]{analysis['bpm']:.0f}bpm"
                                f" {analysis.get('camelot', '')}[/dim cyan]"
                                if analysis else "")
                    console.print(f"  [bold bright_green]v[/bold bright_green]  {label_rich}{lang_tag}{bpm_tag}")
                    status = "ok"
                progress.advance(task)
                return status

            if cur_jobs == 1:
                for tr in pending:
                    r = _process(tr)
                    if r == "skip": skipped    += 1
                    elif r == "ok": downloaded += 1
            else:
                with ThreadPoolExecutor(max_workers=cur_jobs) as ex:
                    futures = {ex.submit(_process, t): t for t in pending}
                    for future in as_completed(futures):
                        r = future.result()
                        if r == "skip": skipped    += 1
                        elif r == "ok": downloaded += 1

        console.print()
        title_text = "Done" if attempt == 1 else f"Retry {attempt - 1} Done"
        step_print(4, 4, (
            f"{title_text}  "
            f"[bold bright_green]{downloaded}[/bold bright_green] downloaded  "
            f"[bold yellow]{skipped}[/bold yellow] skipped  "
            f"[bold bright_red]{len(failed_tracks)}[/bold bright_red] failed"
        ))
        console.print()
        console.print(f"  [dim]Saved to[/dim] [bright_cyan]{output_dir}[/bright_cyan]")

        if failed_tracks:
            console.print()
            confirm = _prompt_simple(
                f"◉  Retry {len(failed_tracks)} failed track{'s' if len(failed_tracks) != 1 else ''}? [Y/n]",
                default="y",
            )
            if confirm and confirm.strip().lower() not in ("n", "no"):
                pending = failed_tracks
                console.print()
                continue
        break

    console.print()


def run_shazam(output_dir: str, quality: str, browser: str = None, duration: int = 10, file: str = None, organize: bool = False):
    if file:
        step_print(1, 3, f"Identifying from file  [dim]{file}[/dim]")
        try:
            track = identify_file(file)
        except Exception as e:
            console.print(f"\n  [bold bright_red]!!  Failed:[/bold bright_red] [red]{e}[/red]\n")
            return
    else:
        console.print(Panel(
            f"  Hold your device near the audio source.\n"
            f"  Recording for [bold bright_yellow]{duration}[/bold bright_yellow] seconds — stay quiet until done.\n\n"
            f"  [dim]Press [bold]Ctrl+C[/bold] to cancel.[/dim]",
            title="[bold bright_magenta]  ♫  Shazam Listening  ♫  [/bold bright_magenta]",
            border_style="bright_magenta",
            box=box.DOUBLE_EDGE,
        ))
        console.print()

        with Progress(
            SpinnerColumn(spinner_name="dots2", style="bright_magenta"),
            TextColumn("[bold bright_white]{task.description}"),
            BarColumn(bar_width=28, style="bright_magenta", complete_style="bright_green"),
            TaskProgressColumn(style="bold bright_yellow"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            rec_task = progress.add_task("[bright_magenta]Recording...[/bright_magenta]", total=None)
            try:
                track = record_and_identify(duration)
            except Exception as e:
                console.print(f"\n  [bold bright_red]!!  Recognition failed:[/bold bright_red] [red]{e}[/red]\n")
                return
            progress.update(rec_task, description="[bright_green]Identified![/bright_green]")

        step_print(1, 3, "Audio recorded and sent to Shazam")

    console.print()

    if not track:
        console.print(Panel(
            "  Shazam could not identify the song.\n"
            "  [dim]Try recording in a quieter environment or move closer to the audio source.[/dim]",
            title="[bold yellow]  !! No Match Found  [/bold yellow]",
            border_style="yellow",
            box=box.DOUBLE_EDGE,
        ))
        console.print()
        return

    lang = detect_language(track["artist"], track["title"]) if organize else None

    color = "bright_magenta"
    t = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    t.add_column(style=f"bold {color}", min_width=10)
    t.add_column(style="bright_white")
    t.add_row("♪  Title",  f"[bold]{track['title']}[/bold]")
    t.add_row("*  Artist", track["artist"])
    if track.get("album"):
        t.add_row("◉  Album", track["album"])
    if lang:
        t.add_row("🌐  Language", f"[bold bright_magenta]{lang}[/bold bright_magenta]")
    if track.get("spotify_url"):
        t.add_row("⊕  Spotify", f"[dim]{track['spotify_url']}[/dim]")

    console.print(Panel(
        t,
        title=f"[bold {color}]  ♫  Shazam Match  ♫  [/bold {color}]",
        border_style=color,
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
    ))
    console.print()

    # Ask user to confirm download
    kb = KeyBindings()

    @kb.add("escape")
    def _quit(event):
        event.app.exit(result="n")

    session = PromptSession(
        style=_PT_STYLE,
        key_bindings=kb,
        bottom_toolbar=HTML("  <b>ENTER</b>  confirm download      <b>ESC</b>  cancel  "),
    )
    try:
        confirm = session.prompt(
            HTML("<ansicyan><b>  ♪  Download this track? [Y/n]  ›  </b></ansicyan>"),
            default="y",
        )
    except (KeyboardInterrupt, EOFError):
        confirm = "n"

    if confirm and confirm.strip().lower() in ("n", "no"):
        console.print("\n  [dim]Cancelled.[/dim]\n")
        return

    console.print()
    step_print(2, 3, f"Matched  [bold bright_magenta]{track['artist']}[/bold bright_magenta]  –  [bold bright_white]{track['title']}[/bold bright_white]")
    console.print()

    track_dir = os.path.join(output_dir, lang) if lang else output_dir
    step_print(3, 3, f"Downloading to [bright_cyan]{track_dir}[/bright_cyan]")
    console.print()

    label_rich = (
        f"[bright_cyan]{track['artist'][:30]}[/bright_cyan]"
        f"[dim] - [/dim]"
        f"[bright_white]{track['title'][:40]}[/bright_white]"
    )

    path = download_track(track, track_dir, quality, cookies_browser=browser)

    if path == SKIP:
        console.print(f"  [bold yellow]o[/bold yellow]  {label_rich}  [dim yellow](already exists, skipped)[/dim yellow]")
    elif path is None:
        console.print(f"  [bold bright_red]x[/bold bright_red]  {label_rich}  [dim red](download failed)[/dim red]")
    else:
        tag_file(path, track)
        analysis = analyze_and_tag(path)
        bpm_tag  = (f"  [dim cyan]{analysis['bpm']:.0f}bpm {analysis.get('camelot', '')}[/dim cyan]"
                    if analysis else "")
        console.print(f"  [bold bright_green]v[/bold bright_green]  {label_rich}{bpm_tag}  [dim green](saved)[/dim green]")

    console.print()
    console.print(f"  [dim]Saved to[/dim] [bright_cyan]{track_dir}[/bright_cyan]")
    console.print()


def run(url: str, output_dir: str, quality: str, jobs, browser: str = None, organize: bool = False):
    if is_youtube_url(url):
        step_print(1, 3, f"Fetching from YouTube  [dim]{url}[/dim]")
        try:
            info = get_yt_info(url)
        except Exception as e:
            console.print(f"\n  [bold bright_red]!!  Failed:[/bold bright_red] [red]{e}[/red]\n")
            return
    else:
        check_credentials()
        step_print(1, 3, f"Connecting to Spotify  [dim]{url}[/dim]")
        try:
            info = get_spotify_info(url)
        except ValueError as e:
            console.print(f"\n  [bold bright_red]!!  Error:[/bold bright_red] [red]{e}[/red]\n")
            return
        except Exception as e:
            console.print(f"\n  [bold bright_red]!!  Failed:[/bold bright_red] [red]{e}[/red]\n")
            return

    console.print()
    print_source_info(info)
    console.print()

    step_print(2, 3, f"Found [bold bright_yellow]{info['total_tracks']}[/bold bright_yellow] tracks  ->  [bright_cyan]{output_dir}[/bright_cyan]")
    console.print()
    print_track_table(info["tracks"])
    console.print()

    # auto: cap at 4 to stay under YouTube rate limits; fewer if playlist is small
    if jobs is None:
        jobs = min(len(info["tracks"]), 4)

    worker_str = f"[bold bright_magenta]{jobs}[/bold bright_magenta] worker{'s' if jobs != 1 else ''}"
    browser_str = f"  [dim]cookies from[/dim] [bright_magenta]{browser}[/bright_magenta]" if browser else ""
    step_print(3, 3, f"Downloading with {worker_str}{browser_str}")
    console.print()

    pending      = info["tracks"]
    had_failures = False
    attempt      = 0

    while True:
        attempt  += 1
        cur_jobs  = min(len(pending), jobs)
        downloaded = skipped = 0
        failed_tracks = []

        with Progress(
            SpinnerColumn(spinner_name="dots2", style="bright_cyan"),
            TextColumn("[bold bright_white]{task.description}"),
            BarColumn(bar_width=28, style="bright_blue", complete_style="bright_green", finished_style="bright_green"),
            TaskProgressColumn(style="bold bright_yellow"),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            ResourceColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task("[bright_cyan]Downloading[/bright_cyan]", total=len(pending))

            def process(track: dict) -> str:
                label_rich = (
                    f"[bright_cyan]{track['artist'][:30]}[/bright_cyan]"
                    f"[dim] - [/dim]"
                    f"[bright_white]{track['title'][:40]}[/bright_white]"
                )
                label_plain = f"{track['artist'][:30]} - {track['title'][:40]}"
                if cur_jobs == 1:
                    progress.update(task, description=f"  [bright_cyan]>[/bright_cyan]  {label_plain[:52]}")

                if organize:
                    lang = detect_language(track["artist"], track["title"])
                    track_dir = os.path.join(output_dir, lang)
                    lang_tag = f"  [dim magenta]{lang}[/dim magenta]"
                else:
                    track_dir = output_dir
                    lang_tag = ""

                path = download_track(track, track_dir, quality, cookies_browser=browser)

                if path == SKIP:
                    console.print(f"  [bold yellow]o[/bold yellow]  {label_rich}{lang_tag}  [dim yellow](skipped)[/dim yellow]")
                    status = "skip"
                elif path is None:
                    console.print(f"  [bold bright_red]x[/bold bright_red]  {label_rich}{lang_tag}  [dim red](failed)[/dim red]")
                    failed_tracks.append(track)
                    status = "fail"
                else:
                    tag_file(path, track)
                    analysis = analyze_and_tag(path)
                    bpm_tag  = (f"  [dim cyan]{analysis['bpm']:.0f}bpm"
                                f" {analysis.get('camelot', '')}[/dim cyan]"
                                if analysis else "")
                    console.print(f"  [bold bright_green]v[/bold bright_green]  {label_rich}{lang_tag}{bpm_tag}")
                    status = "ok"

                progress.advance(task)
                return status

            if cur_jobs == 1:
                for track in pending:
                    r = process(track)
                    if r == "skip": skipped    += 1
                    elif r == "ok": downloaded += 1
            else:
                with ThreadPoolExecutor(max_workers=cur_jobs) as ex:
                    futures = {ex.submit(process, t): t for t in pending}
                    for future in as_completed(futures):
                        r = future.result()
                        if r == "skip": skipped    += 1
                        elif r == "ok": downloaded += 1

        if failed_tracks:
            had_failures = True

        console.print()
        border     = "bright_green" if not failed_tracks else "yellow"
        title_text = "All Done!" if attempt == 1 else f"Retry {attempt - 1} Complete!"

        summary = Table(show_header=False, box=None, padding=(0, 3))
        summary.add_column(justify="center")
        summary.add_column(justify="center")
        summary.add_column(justify="center")
        summary.add_row(
            f"[bold bright_green]Downloaded[/bold bright_green]\n[bold bright_green]{downloaded}[/bold bright_green]",
            f"[bold yellow]Skipped[/bold yellow]\n[bold yellow]{skipped}[/bold yellow]",
            f"[bold bright_red]Failed[/bold bright_red]\n[bold bright_red]{len(failed_tracks)}[/bold bright_red]",
        )

        console.print(Panel(
            Align.center(summary),
            title=f"[bold {border}]  <<  {title_text}  >>  [/bold {border}]",
            border_style=border,
            box=box.DOUBLE_EDGE,
            padding=(1, 4),
        ))
        console.print(f"  [dim]Saved to[/dim] [bright_cyan]{output_dir}[/bright_cyan]")

        if failed_tracks:
            console.print()
            confirm = _prompt_simple(
                f"♪  Retry {len(failed_tracks)} failed track{'s' if len(failed_tracks) != 1 else ''}? [Y/n]",
                default="y",
            )
            if confirm and confirm.strip().lower() not in ("n", "no"):
                pending = failed_tracks
                console.print()
                continue
        break

    if had_failures and not browser and not is_youtube_url(url):
        console.print()
        console.print(Panel(
            "YouTube is blocking downloads without browser cookies.\n"
            "Re-run with your browser to fix this:\n\n"
            "  [bold bright_cyan]python3 main.py <url> --browser chrome[/bold bright_cyan]\n"
            "  [bold bright_cyan]python3 main.py <url> --browser firefox[/bold bright_cyan]\n"
            "  [bold bright_cyan]python3 main.py <url> --browser safari[/bold bright_cyan]",
            title="[bold yellow]  Tip: Fix 403 Errors  [/bold yellow]",
            border_style="yellow",
            box=box.DOUBLE_EDGE,
        ))
    console.print()


def run_analyze(output_dir: str):
    console.print()
    directory = _prompt_simple("⚡  Directory to analyze", default=output_dir)
    if not directory:
        console.print("\n  [dim]Cancelled.[/dim]\n")
        return
    if not os.path.isdir(directory):
        console.print(f"\n  [bold red]Not a directory:[/bold red] {directory}\n")
        return

    force_str = _prompt_simple("⚡  Force re-analyze already-tagged tracks? [y/N]", default="n")
    force     = (force_str or "n").strip().lower() in ("y", "yes")

    console.print()

    with Progress(
        SpinnerColumn(spinner_name="dots2", style="bright_cyan"),
        TextColumn("[bold bright_white]{task.description}"),
        BarColumn(bar_width=28, style="bright_blue", complete_style="bright_green"),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("[bright_cyan]Analyzing...[/bright_cyan]", total=None)
        analyzed = skipped = 0
        for fpath, result in analyze_directory(directory, force=force):
            fname = os.path.basename(fpath)[:52]
            if result:
                analyzed += 1
                bpm_tag = f"[dim cyan]{result['bpm']:.0f}bpm {result.get('camelot','')}[/dim cyan]"
                console.print(f"  [bold bright_green]v[/bold bright_green]  {fname}  {bpm_tag}")
            else:
                skipped += 1
            progress.advance(task)
        progress.update(task, description="[bright_green]Done![/bright_green]")

    console.print()
    console.print(
        f"  [bold bright_green]{analyzed}[/bold bright_green] analyzed  "
        f"[dim]{skipped}[/dim] skipped (already tagged or failed)"
    )
    console.print()


def run_rekordbox(output_dir: str):
    console.print()
    directory = _prompt_simple("◉  Library directory to scan", default=output_dir)
    if not directory:
        console.print("\n  [dim]Cancelled.[/dim]\n")
        return
    if not os.path.isdir(directory):
        console.print(f"\n  [bold red]Not a directory:[/bold red] {directory}\n")
        return

    default_xml = os.path.join(os.path.expanduser("~"), "Desktop", "rekordbox.xml")
    xml_path = _prompt_simple("◉  Output XML path", default=default_xml)
    if not xml_path:
        console.print("\n  [dim]Cancelled.[/dim]\n")
        return

    console.print(f"\n  [dim]Scanning {directory}...[/dim]")
    count = export_rekordbox_xml(directory, xml_path)

    if count == 0:
        console.print("\n  [yellow]No MP3 files found.[/yellow]\n")
        return

    console.print(Panel(
        f"  Exported [bold bright_yellow]{count}[/bold bright_yellow] tracks\n"
        f"  [dim]Saved to[/dim] [bright_cyan]{xml_path}[/bright_cyan]\n\n"
        f"  [dim]Import in Rekordbox:  File → Import Library → XML[/dim]",
        title="[bold bright_green]  ◉  Rekordbox Export Complete  ◉  [/bold bright_green]",
        border_style="bright_green",
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
    ))
    console.print()


def run_dupes(output_dir: str):
    console.print()
    directory = _prompt_simple("♻  Directory to scan", default=output_dir)
    if not directory:
        console.print("\n  [dim]Cancelled.[/dim]\n")
        return
    if not os.path.isdir(directory):
        console.print(f"\n  [bold red]Not a directory:[/bold red] {directory}\n")
        return

    console.print(f"\n  [dim]Scanning for duplicates...[/dim]")
    result = find_duplicates(directory)
    tag_groups  = result["by_tags"]
    hash_groups = result["by_hash"]

    total_groups = len(tag_groups) + len(hash_groups)
    if total_groups == 0:
        console.print("\n  [bold bright_green]No duplicates found![/bold bright_green]\n")
        return

    if hash_groups:
        console.print()
        console.print(f"  [bold bright_red]{len(hash_groups)}[/bold bright_red] identical file group(s) (byte-for-byte copies):")
        for group in hash_groups:
            t = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
            t.add_column(style="dim", min_width=6)
            t.add_column(style="bright_white")
            for j, fpath in enumerate(group, 1):
                size_kb = os.path.getsize(fpath) // 1024
                label   = "[bold bright_red]COPY[/bold bright_red]" if j > 1 else "[dim]ORIG[/dim]"
                t.add_row(label, f"{fpath}  [dim]({size_kb} KB)[/dim]")
            console.print(t)

    if tag_groups:
        console.print()
        console.print(f"  [bold yellow]{len(tag_groups)}[/bold yellow] same-title group(s) (same artist + title tags):")
        for group in tag_groups[:10]:   # cap at 10 to avoid flooding
            t = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
            t.add_column(style="dim", min_width=6)
            t.add_column(style="bright_white")
            for j, fpath in enumerate(group, 1):
                size_kb = os.path.getsize(fpath) // 1024
                t.add_row(f"#{j}", f"{fpath}  [dim]({size_kb} KB)[/dim]")
            console.print(t)
        if len(tag_groups) > 10:
            console.print(f"  [dim]... and {len(tag_groups) - 10} more groups[/dim]")

    console.print()


def run_scan(output_dir: str):
    console.print()
    directory = _prompt_simple("🔍  Directory to scan", default=output_dir)
    if not directory:
        console.print("\n  [dim]Cancelled.[/dim]\n")
        return
    if not os.path.isdir(directory):
        console.print(f"\n  [bold red]Not a directory:[/bold red] {directory}\n")
        return

    console.print(f"\n  [dim]Scanning tags...[/dim]")
    issues = scan_library(directory)

    if not issues:
        console.print("\n  [bold bright_green]All tracks have complete tags![/bold bright_green]\n")
        return

    t = Table(
        show_header=True,
        header_style="bold bright_white on blue",
        box=box.HEAVY_HEAD,
        border_style="bright_blue",
        row_styles=["", "on grey11"],
        padding=(0, 1),
    )
    t.add_column("File",    style="bright_white",  max_width=46)
    t.add_column("Missing", style="bold bright_red", max_width=40)

    for item in issues[:50]:
        fname = os.path.basename(item["path"])
        t.add_row(fname[:44], ", ".join(item["missing"]))

    console.print(Panel(
        t,
        title=f"[bold bright_red]  !!  {len(issues)} tracks with missing tags  [/bold bright_red]",
        border_style="bright_red",
        box=box.DOUBLE_EDGE,
    ))
    if len(issues) > 50:
        console.print(f"  [dim]... and {len(issues) - 50} more[/dim]")
    console.print(f"\n  [dim]Tip: run [bold]\\analyze[/bold] to fill in missing BPM + Key tags.[/dim]\n")


def run_crate(output_dir: str):
    console.print()
    directory = _prompt_simple("♬  Library directory", default=output_dir)
    if not directory:
        console.print("\n  [dim]Cancelled.[/dim]\n")
        return
    if not os.path.isdir(directory):
        console.print(f"\n  [bold red]Not a directory:[/bold red] {directory}\n")
        return

    bpm_str    = _prompt_simple("♬  BPM range  (e.g. 120-130, or blank for any)")
    key_filter = _prompt_simple("♬  Key / Camelot  (e.g. 8A, Am, or blank for any)")
    energy_str = _prompt_simple("♬  Min energy  (0.0–1.0, or blank for any)")

    bpm_min = bpm_max = None
    if bpm_str:
        parts = bpm_str.strip().split("-")
        try:
            bpm_min = float(parts[0].strip())
            bpm_max = float(parts[1].strip()) if len(parts) > 1 else bpm_min + 10
        except (ValueError, IndexError):
            console.print("\n  [bold red]Invalid BPM range. Use format: 120-130[/bold red]\n")
            return

    energy_min = None
    if energy_str:
        try:
            energy_min = float(energy_str.strip())
        except ValueError:
            console.print("\n  [bold red]Invalid energy value.[/bold red]\n")
            return

    default_m3u = os.path.join(os.path.expanduser("~"), "Desktop", "dj_crate.m3u")
    m3u_path = _prompt_simple("♬  Save M3U to", default=default_m3u)
    if not m3u_path:
        console.print("\n  [dim]Cancelled.[/dim]\n")
        return

    console.print(f"\n  [dim]Filtering library...[/dim]")
    matches = build_crate(
        directory,
        bpm_min=bpm_min, bpm_max=bpm_max,
        key=key_filter or None,
        energy_min=energy_min,
        output_m3u=m3u_path,
    )

    if not matches:
        console.print("\n  [yellow]No tracks matched the filters.[/yellow]\n")
        return

    console.print(Panel(
        f"  [bold bright_yellow]{len(matches)}[/bold bright_yellow] tracks matched\n"
        f"  [dim]Saved to[/dim] [bright_cyan]{m3u_path}[/bright_cyan]\n\n"
        f"  [dim]Open in Rekordbox, VirtualDJ, or any DJ software that reads M3U.[/dim]",
        title="[bold bright_green]  ♬  Crate Built  ♬  [/bold bright_green]",
        border_style="bright_green",
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
    ))
    console.print()


def run_setcheck(output_dir: str):
    check_credentials()
    console.print()
    url = _prompt_simple("✓  Spotify playlist URL")
    if not url:
        console.print("\n  [dim]Cancelled.[/dim]\n")
        return

    console.print(f"\n  [dim]Fetching playlist from Spotify...[/dim]")
    try:
        info = get_spotify_info(url)
    except Exception as e:
        console.print(f"\n  [bold red]Error:[/bold red] {e}\n")
        return

    directory = _prompt_simple("✓  Local library directory", default=output_dir)
    if not directory:
        console.print("\n  [dim]Cancelled.[/dim]\n")
        return

    console.print(f"\n  [dim]Checking {info['total_tracks']} tracks against local library...[/dim]")
    result  = check_set(info["tracks"], directory)
    found   = result["found"]
    missing = result["missing"]

    color = "bright_green" if not missing else ("yellow" if missing else "bright_red")
    summary = Table(show_header=False, box=None, padding=(0, 4))
    summary.add_column(justify="center")
    summary.add_column(justify="center")
    summary.add_row(
        f"[bold bright_green]Have locally[/bold bright_green]\n[bold bright_green]{len(found)}[/bold bright_green]",
        f"[bold bright_red]Missing[/bold bright_red]\n[bold bright_red]{len(missing)}[/bold bright_red]",
    )
    console.print()
    console.print(Panel(
        Align.center(summary),
        title=f"[bold {color}]  ✓  {info['name']}  [/bold {color}]",
        border_style=color,
        box=box.DOUBLE_EDGE,
        padding=(1, 4),
    ))

    if missing:
        console.print()
        t = Table(
            show_header=True,
            header_style="bold bright_white on blue",
            box=box.HEAVY_HEAD,
            border_style="bright_red",
            row_styles=["", "on grey11"],
            padding=(0, 1),
        )
        t.add_column("#",      style="bold bright_yellow", width=4,  justify="right")
        t.add_column("Artist", style="bright_cyan",        max_width=28)
        t.add_column("Title",  style="bright_white",       max_width=40)
        for i, tr in enumerate(missing[:30], 1):
            t.add_row(str(i), tr["artist"][:26], tr["title"][:38])
        if len(missing) > 30:
            t.add_row("...", f"[dim]and {len(missing) - 30} more[/dim]", "")
        console.print(Panel(
            t,
            title="[bold bright_red]  !!  Missing Tracks  [/bold bright_red]",
            border_style="bright_red",
            box=box.DOUBLE_EDGE,
        ))

        console.print()
        dl_str = _prompt_simple(
            f"✓  Download all {len(missing)} missing tracks now? [y/N]", default="n"
        )
        if dl_str and dl_str.strip().lower() in ("y", "yes"):
            run(url, directory, DEFAULT_QUALITY, None, organize=False)
            return

    console.print()


def run_configure(watcher, output_dir: str):
    while True:
        config = load_watched()
        playlists = config["playlists"]

        console.print()
        color = "bright_cyan"
        t = Table(
            show_header=True,
            header_style="bold bright_white on blue",
            box=box.HEAVY_HEAD,
            border_style=color,
            row_styles=["", "on grey11"],
            padding=(0, 1),
        )
        t.add_column("#",       style="bold bright_yellow", width=4, justify="right")
        t.add_column("Name",    style="bold bright_white",  max_width=28)
        t.add_column("Folder",  style="bright_cyan",        max_width=33)
        t.add_column("Spotify", style="bright_yellow",      width=8,  justify="right")
        t.add_column("Synced",  style="bright_green",       width=8,  justify="right")
        for i, p in enumerate(playlists, 1):
            spotify_total = str(p["total_tracks"]) if p.get("total_tracks") else "[dim]?[/dim]"
            synced        = str(len(p.get("downloaded_ids", [])))
            t.add_row(str(i), p["name"][:26], p["folder"][:31], spotify_total, synced)

        wstate = "[bold bright_green]RUNNING[/bold bright_green]" if watcher.is_running() else "[bold yellow]STOPPED[/bold yellow]"
        body = t if playlists else Align.center("[dim]No playlists configured yet.[/dim]")
        console.print(Panel(
            body,
            title=f"[bold {color}]  ♬  Watched Playlists  [dim](watcher: {wstate})[/dim]  [/bold {color}]",
            border_style=color,
            box=box.DOUBLE_EDGE,
        ))
        console.print("  [dim]add · edit <#> · remove <#> · count <#> · start · stop · check · back[/dim]")
        console.print()

        resp = _prompt_simple("♬  Action")
        if not resp or resp.lower() in ("back", "b", "exit", "quit"):
            break

        parts  = resp.strip().split(None, 1)
        action = parts[0].lower()
        arg    = parts[1].strip() if len(parts) > 1 else ""

        if action == "add":
            console.print()
            url = _prompt_simple("♬  Spotify playlist URL")
            if not url:
                continue
            console.print(f"\n  [dim]Fetching playlist info...[/dim]")
            try:
                info    = get_spotify_info(url)
                pl_name = info["name"]
            except Exception as e:
                console.print(f"\n  [bold red]Error:[/bold red] {e}\n")
                continue
            folder = _prompt_simple("♬  Local folder", default=os.path.join(output_dir, pl_name))
            if not folder:
                continue
            add_playlist(url, pl_name, folder, total_tracks=info["total_tracks"],
                         track_ids=[t["id"] for t in info["tracks"] if t.get("id")])
            console.print(f"\n  [bold bright_green]Added:[/bold bright_green] [bright_cyan]{pl_name}[/bright_cyan]  →  {folder}  [dim]({info['total_tracks']} tracks)[/dim]\n")

        elif action == "edit":
            if not arg:
                arg = _prompt_simple("♬  Playlist # to edit") or ""
            try:
                idx = int(arg) - 1
                if not 0 <= idx < len(playlists):
                    raise ValueError
            except ValueError:
                console.print("\n  [bold red]Invalid number.[/bold red]\n")
                continue
            entry = playlists[idx]
            console.print()
            new_url = _prompt_simple("♬  New Spotify URL", default=entry["url"])
            if not new_url:
                console.print("\n  [dim]Cancelled.[/dim]\n")
                continue

            url_changed = new_url != entry["url"]
            new_name    = None
            reset_ids   = False

            if url_changed:
                console.print(f"\n  [dim]Fetching playlist info...[/dim]")
                try:
                    info     = get_spotify_info(new_url)
                    new_name = info["name"]
                    console.print(f"  [dim]Name:[/dim] [bright_white]{new_name}[/bright_white]")
                except Exception as e:
                    console.print(f"\n  [bold red]Error:[/bold red] {e}\n")
                    continue
                reset_str = _prompt_simple("♬  Reset sync history? [y/N]", default="n")
                reset_ids = (reset_str or "n").strip().lower() in ("y", "yes")

            new_folder = _prompt_simple("♬  Local folder", default=entry["folder"])
            if not new_folder:
                console.print("\n  [dim]Cancelled.[/dim]\n")
                continue

            update_playlist(
                entry["url"],
                new_url    = new_url    if url_changed else None,
                new_name   = new_name,
                new_folder = new_folder if new_folder != entry["folder"] else None,
                reset_ids  = reset_ids,
            )
            display_name = new_name or entry["name"]
            console.print(f"\n  [bold bright_green]Updated:[/bold bright_green] [bright_cyan]{display_name}[/bright_cyan]")
            if reset_ids:
                console.print("  [dim]Sync history cleared — all tracks will re-download on next check.[/dim]")
            console.print()

        elif action == "remove":
            if not arg:
                arg = _prompt_simple("♬  Playlist # to remove") or ""
            try:
                idx = int(arg) - 1
                if not 0 <= idx < len(playlists):
                    raise ValueError
            except ValueError:
                console.print("\n  [bold red]Invalid number.[/bold red]\n")
                continue
            entry = playlists[idx]
            if remove_playlist(entry["url"]):
                console.print(f"\n  [bold bright_green]Removed:[/bold bright_green] [bright_cyan]{entry['name']}[/bright_cyan]\n")

        elif action == "count":
            if not arg:
                arg = _prompt_simple("♬  Playlist # to count") or ""
            try:
                idx = int(arg) - 1
                if not 0 <= idx < len(playlists):
                    raise ValueError
            except ValueError:
                console.print("\n  [bold red]Invalid number.[/bold red]\n")
                continue
            entry = playlists[idx]
            console.print(f"\n  [dim]Fetching Spotify playlist...[/dim]")
            try:
                info         = get_spotify_info(entry["url"])
                spotify_count = info["total_tracks"]
            except Exception as e:
                console.print(f"\n  [bold red]Error fetching playlist:[/bold red] {e}\n")
                continue
            folder = entry["folder"]
            local_count = len([
                f for f in os.listdir(folder) if f.lower().endswith(".mp3")
            ]) if os.path.isdir(folder) else 0

            color = "bright_cyan"
            ct = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
            ct.add_column(style=f"bold {color}", min_width=18)
            ct.add_column(style="bold bright_white", justify="right", min_width=6)
            ct.add_row("Spotify tracks",  f"[bold bright_yellow]{spotify_count}[/bold bright_yellow]")
            ct.add_row("Local MP3 files", f"[bold bright_green]{local_count}[/bold bright_green]")
            if spotify_count > local_count:
                gap = spotify_count - local_count
                ct.add_row("Missing locally", f"[bold bright_red]{gap}[/bold bright_red]")
            elif local_count >= spotify_count:
                ct.add_row("Status", "[bold bright_green]Up to date[/bold bright_green]")
            console.print(Panel(
                ct,
                title=f"[bold {color}]  ♬  {entry['name']}  [/bold {color}]",
                border_style=color,
                box=box.DOUBLE_EDGE,
                padding=(0, 1),
            ))
            if not os.path.isdir(folder):
                console.print(f"  [dim yellow]Folder not found:[/dim yellow] {folder}")
            else:
                console.print(f"  [dim]Folder:[/dim] [bright_cyan]{folder}[/bright_cyan]")
            console.print()

        elif action == "start":
            if not watcher.is_running():
                watcher.start()
                console.print(
                    f"\n  [bold bright_green]Watcher started.[/bold bright_green]  "
                    f"Polling every {watcher.poll_interval // 60} min.\n"
                )
            else:
                console.print("\n  [dim]Watcher is already running.[/dim]\n")

        elif action == "stop":
            if watcher.is_running():
                watcher.stop()
                console.print("\n  [bold yellow]Watcher stopped.[/bold yellow]\n")
            else:
                console.print("\n  [dim]Watcher is not running.[/dim]\n")

        elif action == "check":
            if watcher.is_running():
                watcher.check_now()
                console.print("\n  [bright_cyan]Manual check triggered.[/bright_cyan]\n")
            else:
                console.print("\n  [yellow]Watcher not running. Use 'start' first.[/yellow]\n")

        else:
            console.print(
                f"\n  [bold red]Unknown action:[/bold red] {action}  "
                f"[dim](add / edit / remove / count / start / stop / check / back)[/dim]\n"
            )


def main():
    print_banner()

    parser = argparse.ArgumentParser(
        prog="spotidl",
        description="Download a Spotify playlist, album, or track as MP3 files via YouTube.",
    )
    parser.add_argument("url", nargs="?", default=None, help="Spotify playlist, album, or track URL (omit for interactive prompt)")
    parser.add_argument(
        "-o", "--output",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "-q", "--quality",
        default=DEFAULT_QUALITY,
        choices=["128", "192", "256", "320"],
        help=f"MP3 bitrate in kbps (default: {DEFAULT_QUALITY})",
    )
    parser.add_argument(
        "-j", "--jobs",
        type=int,
        default=None,
        metavar="N",
        help="Number of parallel downloads (default: auto — up to 4)",
    )
    parser.add_argument(
        "--browser",
        default=None,
        choices=["chrome", "firefox", "safari", "brave", "edge", "opera", "chromium"],
        help="Use cookies from this browser to bypass YouTube 403 errors",
    )
    parser.add_argument(
        "--shazam",
        action="store_true",
        help="Listen via microphone, identify the song with Shazam, then download it",
    )
    parser.add_argument(
        "--shazam-file",
        default=None,
        metavar="PATH",
        help="Identify a song from an audio file using Shazam, then download it",
    )
    parser.add_argument(
        "--listen-duration",
        type=int,
        default=10,
        metavar="SECS",
        help="How many seconds to record when using --shazam (default: 10)",
    )
    parser.add_argument(
        "--organize",
        action="store_true",
        help="Sort downloads into Language/Artist - Title.mp3 subfolders",
    )
    parser.add_argument(
        "--watch-interval",
        type=int,
        default=15,
        metavar="MINS",
        help="How often (minutes) the watcher polls watched playlists (default: 15)",
    )

    args = parser.parse_args()

    try:
        # One-shot modes: CLI URL arg or --shazam flags exit after completion
        if args.shazam or args.shazam_file:
            run_shazam(
                args.output, args.quality,
                browser=args.browser,
                duration=args.listen_duration,
                file=args.shazam_file,
                organize=args.organize,
            )
            return

        if args.url:
            run(args.url, args.output, args.quality, args.jobs, browser=args.browser, organize=args.organize)
            return

        # Interactive loop — keeps running until ESC at the main prompt
        organize = args.organize
        watcher  = PlaylistWatcher(
            quality       = args.quality,
            browser       = args.browser,
            poll_interval = args.watch_interval * 60,
            organize      = organize,
        )

        while True:
            # Drain any watcher notifications before showing the prompt
            while not watcher.notifications.empty():
                try:
                    msg = watcher.notifications.get_nowait()
                    console.print(f"\n  {msg}")
                except Exception:
                    break
            if not watcher.notifications.empty():
                console.print()

            url = get_url_interactive(organize=organize, watcher_running=watcher.is_running())
            if not url:
                watcher.stop()
                console.print("\n  [dim]Bye![/dim]\n")
                break

            if url.startswith("\\"):
                parts = url.split(None, 1)
                cmd   = parts[0].lower()
                query = parts[1].strip() if len(parts) > 1 else ""
                if cmd == "\\monitor":
                    run_monitor(console)
                    continue
                elif cmd == "\\organize":
                    organize = not organize
                    watcher.organize = organize
                    state = "[bold bright_green]ON[/bold bright_green]" if organize else "[bold yellow]OFF[/bold yellow]"
                    console.print(f"\n  Organize mode: {state}  [dim](songs sorted into Language/ subfolders)[/dim]\n")
                    continue
                elif cmd == "\\configure":
                    run_configure(watcher, args.output)
                    continue
                elif cmd == "\\analyze":
                    run_analyze(args.output)
                    continue
                elif cmd == "\\rekordbox":
                    run_rekordbox(args.output)
                    continue
                elif cmd == "\\dupes":
                    run_dupes(args.output)
                    continue
                elif cmd == "\\scan":
                    run_scan(args.output)
                    continue
                elif cmd == "\\crate":
                    run_crate(args.output)
                    continue
                elif cmd == "\\setcheck":
                    run_setcheck(args.output)
                    continue
                elif cmd == "\\shazam":
                    run_shazam(args.output, args.quality, browser=args.browser, duration=args.listen_duration, organize=organize)
                elif cmd == "\\song":
                    run_song_search(query, args.output, args.quality, browser=args.browser, organize=organize)
                elif cmd == "\\album":
                    run_album_search(query, args.output, args.quality, browser=args.browser, organize=organize)
                else:
                    console.print(f"\n  [bold red]Unknown command:[/bold red] {cmd}\n")
            else:
                run(url, args.output, args.quality, args.jobs, browser=args.browser, organize=organize)

            console.print(Rule(style="dim bright_black"))
            console.print()

    except KeyboardInterrupt:
        console.print("\n\n  [dim]Interrupted.[/dim]\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
