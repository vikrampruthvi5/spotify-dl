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

from config import DEFAULT_OUTPUT_DIR, DEFAULT_QUALITY, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from spotify_client import get_info as get_spotify_info
from youtube import get_info as get_yt_info, is_youtube_url
from downloader import download_track, SKIP
from tagger import tag_file
from recognizer import record_and_identify, identify_file
from search import search_tracks, search_albums
from language import detect_language
from monitor import ResourceColumn, run_monitor
from watcher import PlaylistWatcher, load_watched, add_playlist, remove_playlist, update_playlist

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
        console.print(f"  [bold bright_green]v[/bold bright_green]  {label_rich}")

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

    downloaded = skipped = failed = 0

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
        task = progress.add_task("[bright_cyan]Downloading[/bright_cyan]", total=len(tracks))

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
                status = "fail"
            else:
                tag_file(path, track)
                console.print(f"  [bold bright_green]v[/bold bright_green]  {label_rich}{lang_tag}")
                status = "ok"
            progress.advance(task)
            return status

        if jobs == 1:
            for tr in tracks:
                r = _process(tr)
                if r == "skip":   skipped    += 1
                elif r == "fail": failed     += 1
                else:             downloaded += 1
        else:
            with ThreadPoolExecutor(max_workers=jobs) as ex:
                futures = {ex.submit(_process, t): t for t in tracks}
                for future in as_completed(futures):
                    r = future.result()
                    if r == "skip":   skipped    += 1
                    elif r == "fail": failed     += 1
                    else:             downloaded += 1

    console.print()
    step_print(4, 4, (
        f"Done  "
        f"[bold bright_green]{downloaded}[/bold bright_green] downloaded  "
        f"[bold yellow]{skipped}[/bold yellow] skipped  "
        f"[bold bright_red]{failed}[/bold bright_red] failed"
    ))
    console.print()
    console.print(f"  [dim]Saved to[/dim] [bright_cyan]{output_dir}[/bright_cyan]")
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
        console.print(f"  [bold bright_green]v[/bold bright_green]  {label_rich}  [dim green](saved)[/dim green]")

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

    tracks = info["tracks"]
    downloaded = skipped = failed = 0

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
        task = progress.add_task("[bright_cyan]Downloading[/bright_cyan]", total=len(tracks))

        def process(track: dict) -> str:
            label_rich = (
                f"[bright_cyan]{track['artist'][:30]}[/bright_cyan]"
                f"[dim] - [/dim]"
                f"[bright_white]{track['title'][:40]}[/bright_white]"
            )
            label_plain = f"{track['artist'][:30]} - {track['title'][:40]}"
            if jobs == 1:
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
                status = "fail"
            else:
                tag_file(path, track)
                console.print(f"  [bold bright_green]v[/bold bright_green]  {label_rich}{lang_tag}")
                status = "ok"

            progress.advance(task)
            return status

        if jobs == 1:
            for track in tracks:
                r = process(track)
                if r == "skip":   skipped    += 1
                elif r == "fail": failed     += 1
                else:             downloaded += 1
        else:
            with ThreadPoolExecutor(max_workers=jobs) as ex:
                futures = {ex.submit(process, t): t for t in tracks}
                for future in as_completed(futures):
                    r = future.result()
                    if r == "skip":   skipped    += 1
                    elif r == "fail": failed     += 1
                    else:             downloaded += 1

    console.print()
    border = "bright_green" if failed == 0 else "yellow"

    summary = Table(show_header=False, box=None, padding=(0, 3))
    summary.add_column(justify="center")
    summary.add_column(justify="center")
    summary.add_column(justify="center")
    summary.add_row(
        f"[bold bright_green]Downloaded[/bold bright_green]\n[bold bright_green]{downloaded}[/bold bright_green]",
        f"[bold yellow]Skipped[/bold yellow]\n[bold yellow]{skipped}[/bold yellow]",
        f"[bold bright_red]Failed[/bold bright_red]\n[bold bright_red]{failed}[/bold bright_red]",
    )

    console.print(Panel(
        Align.center(summary),
        title=f"[bold {border}]  <<  All Done!  >>  [/bold {border}]",
        border_style=border,
        box=box.DOUBLE_EDGE,
        padding=(1, 4),
    ))
    console.print(f"  [dim]Saved to[/dim] [bright_cyan]{output_dir}[/bright_cyan]")

    if failed > 0 and not browser and not is_youtube_url(url):
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
        t.add_column("#",      style="bold bright_yellow", width=4, justify="right")
        t.add_column("Name",   style="bold bright_white",  max_width=30)
        t.add_column("Folder", style="bright_cyan",        max_width=35)
        t.add_column("Synced", style="dim",                width=8, justify="right")
        for i, p in enumerate(playlists, 1):
            t.add_row(str(i), p["name"][:28], p["folder"][:33], str(len(p.get("downloaded_ids", []))))

        wstate = "[bold bright_green]RUNNING[/bold bright_green]" if watcher.is_running() else "[bold yellow]STOPPED[/bold yellow]"
        body = t if playlists else Align.center("[dim]No playlists configured yet.[/dim]")
        console.print(Panel(
            body,
            title=f"[bold {color}]  ♬  Watched Playlists  [dim](watcher: {wstate})[/dim]  [/bold {color}]",
            border_style=color,
            box=box.DOUBLE_EDGE,
        ))
        console.print("  [dim]add · edit <#> · remove <#> · start · stop · check · back[/dim]")
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
            add_playlist(url, pl_name, folder)
            console.print(f"\n  [bold bright_green]Added:[/bold bright_green] [bright_cyan]{pl_name}[/bright_cyan]  →  {folder}\n")

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
                f"[dim](add / edit / remove / start / stop / check / back)[/dim]\n"
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
