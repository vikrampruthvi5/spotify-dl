#!/usr/bin/env python3
"""Generates SVG screenshots for the README using Rich's console recording."""
import os, sys, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

import pyfiglet
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.rule import Rule
from rich.align import Align
from rich import box

W = 96  # console width
os.makedirs("screenshots", exist_ok=True)

_BANNER_COLORS = [
    "bold bright_cyan", "bold bright_magenta", "bold bright_yellow",
    "bold bright_green", "bold cyan", "bold magenta",
]


def c() -> Console:
    return Console(record=True, width=W)


def save(con: Console, name: str, title: str = "SpotiDL"):
    path = f"screenshots/{name}.svg"
    con.save_svg(path, title=title)
    print(f"  ✓  {path}")


# ── 1. Banner + prompt ────────────────────────────────────────────────────────
def ss_banner():
    con = c()
    lines = [l for l in pyfiglet.figlet_format("SpotiDL", font="slant").split("\n") if l.strip()]
    con.print()
    for i, line in enumerate(lines):
        col = _BANNER_COLORS[i % len(_BANNER_COLORS)]
        con.print(f"[{col}]{line}[/{col}]")
    con.print()
    con.print(Align.center(
        "[bold bright_white on blue]  ♪  Download Spotify Music as MP3s via YouTube  ♪  [/bold bright_white on blue]"
    ))
    con.print()
    con.print(Rule(style="bright_blue"))
    con.print()
    con.print("  [bold bright_cyan]♪  URL or \\command  ›[/bold bright_cyan]  ", end="")
    con.print()
    save(con, "01_banner", "SpotiDL")


# ── 2. \ commands autocomplete ────────────────────────────────────────────────
def ss_commands():
    con = c()
    con.print()
    con.print("  [bold bright_cyan]♪  URL or \\command  ›[/bold bright_cyan]  [bold]\\[/bold]")
    con.print()

    t = Table(show_header=False, box=box.ROUNDED, border_style="bright_blue",
              padding=(0, 2), show_edge=True)
    t.add_column(style="bold bright_cyan",  min_width=14)
    t.add_column(style="dim bright_white",  min_width=40)
    t.add_row("\\shazam",   "Listen via mic & identify song")
    t.add_row("\\song",     "Search track by title")
    t.add_row("\\album",    "Browse album & download tracks")
    t.add_row("\\organize", "Toggle Language/ subfolder sorting")
    t.add_row("\\monitor",  "Live CPU / RAM / temperature display")

    con.print(Panel(t, title="[bold bright_blue]  Commands  [/bold bright_blue]",
                    border_style="bright_blue", box=box.DOUBLE_EDGE, padding=(0, 1)))
    con.print()
    save(con, "02_commands", "SpotiDL — Commands")


# ── 3. Song search results ────────────────────────────────────────────────────
def ss_song_search():
    con = c()
    con.print()
    con.print("  [bold bright_black][[/bold bright_black][bold bright_cyan]1[/bold bright_cyan]"
              "[bold bright_black]/[/bold bright_black][bold bright_cyan]3[/bold bright_cyan]"
              "[bold bright_black]][/bold bright_black]  "
              "[bright_white]Searching Spotify  [dim]Shape of You[/dim][/bright_white]")
    con.print()

    t = Table(show_header=True, header_style="bold bright_white on blue",
              box=box.HEAVY_HEAD, border_style="bright_blue",
              row_styles=["", "on grey11"], padding=(0, 1))
    t.add_column("#",      style="bold bright_yellow", width=4,  justify="right")
    t.add_column("Artist", style="bright_cyan",        max_width=28)
    t.add_column("Title",  style="bold bright_white",  max_width=36)
    t.add_column("Album",  style="dim",                max_width=24)
    t.add_column("Time",   style="dim",                width=6,  justify="right")

    for row in [
        ("1", "Ed Sheeran",         "Shape of You",             "÷ (Deluxe)",            "3:53"),
        ("2", "Ed Sheeran",         "Shape of You",             "POP:AM",                "3:53"),
        ("3", "Brennan Lynch",      "Shape of You",             "Shape of You",          "2:46"),
        ("4", "Taylor Swift",       "Dress",                    "reputation",            "3:50"),
        ("5", "The Chainsmokers",   "Don't Let Me Down",        "Collage",               "3:28"),
        ("6", "Post Malone",        "Congratulations",          "Stoney",                "3:38"),
    ]:
        t.add_row(*row)

    con.print(Panel(t, title="[bold bright_blue]  ♬  Search Results  ♬  [/bold bright_blue]",
                    border_style="bright_blue", box=box.DOUBLE_EDGE))
    con.print()
    con.print("  [bold bright_cyan]♪  Pick a track (1–6)  ›[/bold bright_cyan]  ", end="")
    con.print()
    save(con, "03_song_search", "SpotiDL — \\song")


# ── 4. Album browser ──────────────────────────────────────────────────────────
def ss_album():
    con = c()
    con.print()
    con.print("  [bold bright_black][[/bold bright_black][bold bright_cyan]2[/bold bright_cyan]"
              "[bold bright_black]/[/bold bright_black][bold bright_cyan]4[/bold bright_cyan]"
              "[bold bright_black]][/bold bright_black]  "
              "[bright_white]Fetching tracks for  [bold bright_magenta]÷ (Divide)[/bold bright_magenta][/bright_white]")

    color = "bright_magenta"
    info_t = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    info_t.add_column(style=f"bold {color}", min_width=10)
    info_t.add_column(style="bright_white")
    info_t.add_row("◉  Album",  "[bold]÷ (Divide)[/bold]")
    info_t.add_row("*  Artist", "Ed Sheeran")
    info_t.add_row("#  Tracks", "[bold bright_yellow]16[/bold bright_yellow]")
    con.print()
    con.print(Panel(info_t, title=f"[bold {color}]  ◉  ÷ (Divide)  ◉  [/bold {color}]",
                    border_style=color, box=box.DOUBLE_EDGE, padding=(1, 2)))

    t = Table(show_header=True, header_style="bold bright_white on blue",
              box=box.HEAVY_HEAD, border_style="bright_blue",
              row_styles=["", "on grey11"], padding=(0, 1))
    t.add_column("#",      style="bold bright_yellow", width=4, justify="right")
    t.add_column("Artist", style="bright_cyan",        max_width=30)
    t.add_column("Title",  style="bright_white",       max_width=40)
    t.add_column("Album",  style="dim",                max_width=25)

    for row in [
        ("1",   "Ed Sheeran", "Eraser",             "÷ (Divide)"),
        ("2",   "Ed Sheeran", "Castle on the Hill",  "÷ (Divide)"),
        ("3",   "Ed Sheeran", "Dive",                "÷ (Divide)"),
        ("4",   "Ed Sheeran", "Shape of You",        "÷ (Divide)"),
        ("5",   "Ed Sheeran", "Perfect",             "÷ (Divide)"),
        ("6",   "Ed Sheeran", "Galway Girl",         "÷ (Divide)"),
        ("7",   "Ed Sheeran", "Happier",             "÷ (Divide)"),
        ("8",   "Ed Sheeran", "New Man",             "÷ (Divide)"),
        ("...", "[dim]and 8 more[/dim]", "", ""),
    ]:
        t.add_row(*row)

    con.print(Panel(t, title="[bold bright_blue]  ♬  Track List  ♬  [/bold bright_blue]",
                    border_style="bright_blue", box=box.DOUBLE_EDGE))
    con.print()
    con.print("  [bold bright_cyan]◉  Tracks to download  (all / 1 / 2-5 / 1,3,5)  ›[/bold bright_cyan]  [bold]all[/bold]")
    con.print()
    save(con, "04_album", "SpotiDL — \\album")


# ── 5. Download in progress ───────────────────────────────────────────────────
def ss_download():
    con = c()
    con.print()
    con.print("  [bold bright_black][[/bold bright_black][bold bright_cyan]3[/bold bright_cyan]"
              "[bold bright_black]/[/bold bright_black][bold bright_cyan]3[/bold bright_cyan]"
              "[bold bright_black]][/bold bright_black]  "
              "[bright_white]Downloading with [bold bright_magenta]4[/bold bright_magenta] workers[/bright_white]")
    con.print()

    for icon, label, extra in [
        ("[bold bright_green]✓[/bold bright_green]",
         "[bright_cyan]Ed Sheeran[/bright_cyan][dim] - [/dim][bright_white]Eraser[/bright_white]", ""),
        ("[bold bright_green]✓[/bold bright_green]",
         "[bright_cyan]Ed Sheeran[/bright_cyan][dim] - [/dim][bright_white]Castle on the Hill[/bright_white]", ""),
        ("[bold bright_green]✓[/bold bright_green]",
         "[bright_cyan]Ed Sheeran[/bright_cyan][dim] - [/dim][bright_white]Dive[/bright_white]", ""),
        ("[bold yellow]○[/bold yellow]",
         "[bright_cyan]Ed Sheeran[/bright_cyan][dim] - [/dim][bright_white]Shape of You[/bright_white]",
         "  [dim yellow](skipped)[/dim yellow]"),
        ("[bold bright_green]✓[/bold bright_green]",
         "[bright_cyan]Ed Sheeran[/bright_cyan][dim] - [/dim][bright_white]Perfect[/bright_white]", ""),
    ]:
        con.print(f"  {icon}  {label}{extra}")

    con.print()
    con.print(
        "  [bright_cyan]⠸[/bright_cyan]  "
        "[bold bright_white]  ›  Ed Sheeran - Galway Girl[/bold bright_white]"
        "  [bright_blue]━━━━━━━━━━━━━━━━━[/bright_blue][dim]━━━━━━━━[/dim]"
        "  [bold bright_yellow]67%[/bold bright_yellow]"
        "  [white]8/12[/white]"
        "  [white]0:00:34[/white]"
        "  [dim]CPU [/dim][bold bright_green]38%[/bold bright_green]"
        "  [dim]RAM [/dim][bold bright_green]51%[/bold bright_green]"
    )
    con.print()
    save(con, "05_download", "SpotiDL — Downloading")


# ── 6. Shazam match panel ─────────────────────────────────────────────────────
def ss_shazam():
    con = c()
    con.print()
    con.print("  [bold bright_black][[/bold bright_black][bold bright_cyan]1[/bold bright_cyan]"
              "[bold bright_black]/[/bold bright_black][bold bright_cyan]3[/bold bright_cyan]"
              "[bold bright_black]][/bold bright_black]  "
              "[bright_white]Audio recorded and sent to Shazam[/bright_white]")
    con.print()

    color = "bright_magenta"
    t = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    t.add_column(style=f"bold {color}", min_width=14)
    t.add_column(style="bright_white")
    t.add_row("♪  Title",      "[bold]As It Was[/bold]")
    t.add_row("*  Artist",     "Harry Styles")
    t.add_row("◉  Album",      "Harry's House")
    t.add_row("🌐  Language",  "[bold bright_magenta]English[/bold bright_magenta]")

    con.print(Panel(t, title=f"[bold {color}]  ♫  Shazam Match  ♫  [/bold {color}]",
                    border_style=color, box=box.DOUBLE_EDGE, padding=(1, 2)))
    con.print()
    con.print("  [bold bright_cyan]♪  Download this track? [Y/n]  ›[/bold bright_cyan]  [bold]y[/bold]")
    con.print()
    save(con, "06_shazam", "SpotiDL — \\shazam")


# ── 7. Live resource monitor ──────────────────────────────────────────────────
def ss_monitor():
    con = c()
    con.print()
    con.print("  [dim]Monitoring resources — Ctrl+C to return to menu.[/dim]")
    con.print()

    def bar(pct, style, width=22):
        filled = int(width * min(pct, 100) / 100)
        return f"[{style}]{'█' * filled}{'░' * (width - filled)}[/{style}]"

    t = Table(show_header=False, box=box.SIMPLE, padding=(0, 2), expand=False)
    t.add_column(style="dim",  min_width=10)
    t.add_column(              min_width=28)
    t.add_column(              min_width=24)

    t.add_row("CPU",  "[bold bright_green] 34.2%[/bold bright_green]",
              bar(34.2, "bold bright_green"))
    t.add_row("RAM",  "[bold bright_green] 51.8%[/bold bright_green]  [dim](8.3 / 16.0 GB)[/dim]",
              bar(51.8, "bold bright_green"))
    t.add_row("Temp", "[bold yellow] 71.0°C[/bold yellow]",
              bar(71, "bold yellow"))

    con.print(Panel(t, title="[bold bright_cyan]  ⬡  System Resources  ⬡  [/bold bright_cyan]",
                    border_style="bright_cyan", box=box.DOUBLE_EDGE, padding=(1, 2)))
    con.print()
    save(con, "07_monitor", "SpotiDL — \\monitor")


# ── 8. Completion summary ─────────────────────────────────────────────────────
def ss_done():
    con = c()
    con.print()

    summary = Table(show_header=False, box=None, padding=(0, 4))
    summary.add_column(justify="center")
    summary.add_column(justify="center")
    summary.add_column(justify="center")
    summary.add_row(
        "[bold bright_green]Downloaded[/bold bright_green]\n[bold bright_green]14[/bold bright_green]",
        "[bold yellow]Skipped[/bold yellow]\n[bold yellow]2[/bold yellow]",
        "[bold bright_red]Failed[/bold bright_red]\n[bold bright_red]0[/bold bright_red]",
    )

    con.print(Panel(Align.center(summary),
                    title="[bold bright_green]  <<  All Done!  >>  [/bold bright_green]",
                    border_style="bright_green", box=box.DOUBLE_EDGE, padding=(1, 4)))
    con.print("  [dim]Saved to[/dim] [bright_cyan]~/Downloads/SpotiDL[/bright_cyan]")
    con.print()
    con.print(Rule(style="dim bright_black"))
    con.print()
    con.print("  [bold bright_cyan]♪  URL or \\command  ›[/bold bright_cyan]  ", end="")
    con.print()
    save(con, "08_done", "SpotiDL — Done")


if __name__ == "__main__":
    print("\nGenerating screenshots...\n")
    ss_banner()
    ss_commands()
    ss_song_search()
    ss_album()
    ss_download()
    ss_shazam()
    ss_monitor()
    ss_done()
    print("\nAll done!\n")
