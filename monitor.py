import time
import psutil
from rich.progress import ProgressColumn
from rich.text import Text

# Prime the rolling cpu_percent counter so first render isn't 0.0
psutil.cpu_percent(interval=None)


def _cpu_temp():
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            readings = [t.current for bucket in temps.values() for t in bucket]
            return max(readings) if readings else None
    except Exception:
        pass
    return None


def _bar(pct, style, width=20):
    filled = int(width * min(pct, 100) / 100)
    return f"[{style}]{'█' * filled}{'░' * (width - filled)}[/{style}]"


class ResourceColumn(ProgressColumn):
    """Live CPU % / RAM % column shown inside Rich progress bars."""

    def render(self, task):
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent

        cpu_style = "bright_red" if cpu > 80 else "yellow" if cpu > 60 else "bright_green"
        ram_style = "bright_red" if ram > 85 else "yellow" if ram > 65 else "bright_green"

        text = Text(no_wrap=True)
        text.append("CPU ", style="dim")
        text.append(f"{cpu:4.0f}%", style=f"bold {cpu_style}")
        text.append("  RAM ", style="dim")
        text.append(f"{ram:4.0f}%", style=f"bold {ram_style}")

        temp = _cpu_temp()
        if temp is not None:
            temp_style = "bright_red" if temp > 85 else "yellow" if temp > 70 else "bright_green"
            text.append("  ", style="dim")
            text.append(f"{temp:.0f}°C", style=f"bold {temp_style}")

        return text


def run_monitor(console):
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich import box as rbox

    console.print("\n  [dim]Monitoring resources — Ctrl+C to return to menu.[/dim]\n")

    def _snapshot():
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        ram = mem.percent
        ram_used  = mem.used  / (1024 ** 3)
        ram_total = mem.total / (1024 ** 3)
        temp = _cpu_temp()

        cpu_style  = "bold bright_red" if cpu > 80  else "bold yellow" if cpu > 60  else "bold bright_green"
        ram_style  = "bold bright_red" if ram > 85  else "bold yellow" if ram > 65  else "bold bright_green"

        t = Table(show_header=False, box=rbox.SIMPLE, padding=(0, 2), expand=False)
        t.add_column(style="dim",           min_width=10)
        t.add_column(                       min_width=22)
        t.add_column(                       min_width=22)

        t.add_row(
            "CPU",
            f"[{cpu_style}]{cpu:5.1f}%[/{cpu_style}]",
            _bar(cpu, cpu_style),
        )
        t.add_row(
            "RAM",
            f"[{ram_style}]{ram:5.1f}%[/{ram_style}]  [dim]({ram_used:.1f} / {ram_total:.1f} GB)[/dim]",
            _bar(ram, ram_style),
        )
        if temp is not None:
            temp_style = "bold bright_red" if temp > 85 else "bold yellow" if temp > 70 else "bold bright_green"
            t.add_row(
                "Temp",
                f"[{temp_style}]{temp:.1f}°C[/{temp_style}]",
                _bar(min(temp, 100), temp_style),
            )

        return Panel(
            t,
            title="[bold bright_cyan]  ⬡  System Resources  ⬡  [/bold bright_cyan]",
            border_style="bright_cyan",
            box=rbox.DOUBLE_EDGE,
            padding=(1, 2),
        )

    try:
        with Live(_snapshot(), console=console, refresh_per_second=2) as live:
            while True:
                time.sleep(0.5)
                live.update(_snapshot())
    except KeyboardInterrupt:
        console.print("\n  [dim]Monitoring stopped.[/dim]\n")
