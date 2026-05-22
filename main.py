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

from config import DEFAULT_OUTPUT_DIR, DEFAULT_QUALITY, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from spotify_client import get_info as get_spotify_info
from youtube import get_info as get_yt_info, is_youtube_url
from downloader import download_track, SKIP
from tagger import tag_file
from recognizer import record_and_identify, identify_file

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

_URL_TOOLBAR = HTML(
    "  <b>ENTER</b>  download      <b>ESC</b>  exit  "
)


def get_url_interactive() -> str:
    kb = KeyBindings()

    @kb.add("escape")
    def _quit(event):
        event.app.exit(result=None)

    session = PromptSession(
        style=_PT_STYLE,
        key_bindings=kb,
        bottom_toolbar=_URL_TOOLBAR,
    )
    try:
        result = session.prompt(
            HTML("<ansicyan><b>  ♪  Spotify or YouTube URL  ›  </b></ansicyan>")
        )
    except (KeyboardInterrupt, EOFError):
        result = None

    return result.strip() if result else None


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


def run_shazam(output_dir: str, quality: str, browser: str = None, duration: int = 10, file: str = None):
    if file:
        step_print(1, 3, f"Identifying from file  [dim]{file}[/dim]")
        try:
            track = identify_file(file)
        except Exception as e:
            console.print(f"\n  [bold bright_red]!!  Failed:[/bold bright_red] [red]{e}[/red]\n")
            sys.exit(1)
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
                sys.exit(1)
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
        sys.exit(1)

    color = "bright_magenta"
    t = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    t.add_column(style=f"bold {color}", min_width=10)
    t.add_column(style="bright_white")
    t.add_row("♪  Title",  f"[bold]{track['title']}[/bold]")
    t.add_row("*  Artist", track["artist"])
    if track.get("album"):
        t.add_row("◉  Album", track["album"])
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
        sys.exit(0)

    console.print()
    step_print(2, 3, f"Matched  [bold bright_magenta]{track['artist']}[/bold bright_magenta]  –  [bold bright_white]{track['title']}[/bold bright_white]")
    console.print()

    step_print(3, 3, f"Downloading to [bright_cyan]{output_dir}[/bright_cyan]")
    console.print()

    label_rich = (
        f"[bright_cyan]{track['artist'][:30]}[/bright_cyan]"
        f"[dim] - [/dim]"
        f"[bright_white]{track['title'][:40]}[/bright_white]"
    )

    path = download_track(track, output_dir, quality, cookies_browser=browser)

    if path == SKIP:
        console.print(f"  [bold yellow]o[/bold yellow]  {label_rich}  [dim yellow](already exists, skipped)[/dim yellow]")
    elif path is None:
        console.print(f"  [bold bright_red]x[/bold bright_red]  {label_rich}  [dim red](download failed)[/dim red]")
    else:
        tag_file(path, track)
        console.print(f"  [bold bright_green]v[/bold bright_green]  {label_rich}  [dim green](saved)[/dim green]")

    console.print()
    console.print(f"  [dim]Saved to[/dim] [bright_cyan]{output_dir}[/bright_cyan]")
    console.print()


def run(url: str, output_dir: str, quality: str, jobs, browser: str = None):
    if is_youtube_url(url):
        step_print(1, 3, f"Fetching from YouTube  [dim]{url}[/dim]")
        try:
            info = get_yt_info(url)
        except Exception as e:
            console.print(f"\n  [bold bright_red]!!  Failed:[/bold bright_red] [red]{e}[/red]\n")
            sys.exit(1)
    else:
        check_credentials()
        step_print(1, 3, f"Connecting to Spotify  [dim]{url}[/dim]")
        try:
            info = get_spotify_info(url)
        except ValueError as e:
            console.print(f"\n  [bold bright_red]!!  Error:[/bold bright_red] [red]{e}[/red]\n")
            sys.exit(1)
        except Exception as e:
            console.print(f"\n  [bold bright_red]!!  Failed:[/bold bright_red] [red]{e}[/red]\n")
            sys.exit(1)

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

            path = download_track(track, output_dir, quality, cookies_browser=browser)

            if path == SKIP:
                console.print(f"  [bold yellow]o[/bold yellow]  {label_rich}  [dim yellow](skipped)[/dim yellow]")
                status = "skip"
            elif path is None:
                console.print(f"  [bold bright_red]x[/bold bright_red]  {label_rich}  [dim red](failed)[/dim red]")
                status = "fail"
            else:
                tag_file(path, track)
                console.print(f"  [bold bright_green]v[/bold bright_green]  {label_rich}")
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

    args = parser.parse_args()

    try:
        if args.shazam or args.shazam_file:
            run_shazam(
                args.output, args.quality,
                browser=args.browser,
                duration=args.listen_duration,
                file=args.shazam_file,
            )
            return

        url = args.url
        if not url:
            url = get_url_interactive()
            if not url:
                console.print("\n  [dim]Bye![/dim]\n")
                sys.exit(0)

        run(url, args.output, args.quality, args.jobs, browser=args.browser)
    except KeyboardInterrupt:
        console.print("\n\n  [dim]Interrupted.[/dim]\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
