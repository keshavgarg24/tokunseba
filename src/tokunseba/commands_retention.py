"""The `tokunseba retention` command group.

Reports can only reach as far back as history is kept, so how long to keep it is a decision
the user should be able to see and change in one command rather than discover in a config
file. The default keeps 90 days.
"""
from __future__ import annotations

import time
from pathlib import Path

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import config

console = Console()
err = Console(stderr=True)

UNITS = {"h": 1 / 24, "d": 1.0, "w": 7.0, "m": 30.0, "y": 365.0}
FOREVER = {"forever", "always", "all", "never", "0"}


def parse_days(text: str) -> int:
    """Turn 12h, 30d, 6w, 6m, 2y or forever into whole days. 0 means keep everything."""
    s = text.strip().lower()
    if not s:
        raise click.BadParameter("give a window: 24h, 30d, 6w, 6m, 1y, or forever.")
    if s in FOREVER:
        return 0
    unit = s[-1]
    if unit in UNITS:
        s, mult = s[:-1], UNITS[unit]
    else:
        mult = 1.0
    try:
        n = float(s)
    except ValueError:
        raise click.BadParameter(
            f"cannot read '{text}'. Use 24h, 30d, 6w, 6m, 1y, or forever.") from None
    if n < 0:
        raise click.BadParameter("a retention window cannot be negative.")
    return max(1, round(n * mult)) if n else 0


def humanise(days: int) -> str:
    if days <= 0:
        return "forever"
    if days % 365 == 0:
        return f"{days // 365} year{'s' if days > 365 else ''}"
    if days % 30 == 0:
        return f"{days // 30} month{'s' if days > 30 else ''}"
    if days % 7 == 0:
        return f"{days // 7} week{'s' if days > 7 else ''}"
    return f"{days} day{'s' if days != 1 else ''}"


def _dir_mb(path: Path) -> float:
    total = 0
    if path.exists():
        for f in path.rglob("*"):
            try:
                if f.is_file():
                    total += f.stat().st_size
            except OSError:
                continue
    return total / (1024 * 1024)


def _oldest_day(led) -> str:
    rows = led.daily(3650)
    return rows[0]["day"] if rows else ""


def register(main: click.Group) -> None:
    @main.group("retention", invoke_without_command=True)
    @click.pass_context
    def retention(ctx: click.Context) -> None:
        """Choose how long tokunseba keeps history, and prune what is past it."""
        if ctx.invoked_subcommand is None:
            ctx.invoke(retention_show)

    @retention.command("show")
    def retention_show() -> None:
        """Show the current window, and how much is actually stored."""
        from .ledger import Ledger
        cfg = config.load()
        home = config.home()
        led = Ledger(home / "ledger.sqlite")
        t = Table(header_style="dim", box=None)
        t.add_column("")
        t.add_column("")
        t.add_row("keep history for", f"[bold]{humanise(cfg.retention.days)}[/bold]")
        t.add_row("keep request bodies for",
                  humanise(cfg.retention.keep_bodies_days or cfg.retention.days))
        t.add_row("prune automatically",
                  "[green]yes, once a day[/green]" if cfg.retention.auto_prune
                  else "[yellow]no, only when you run tokunseba retention prune[/yellow]")
        oldest = _oldest_day(led)
        t.add_row("oldest day on record", escape(oldest) if oldest else "[dim]nothing yet[/dim]")
        db = (home / "ledger.sqlite")
        t.add_row("on disk", f"ledger {db.stat().st_size / 1e6:.1f} MB"
                             f" · bodies {_dir_mb(home / 'bodies'):.1f} MB"
                             f" · blobs {_dir_mb(home / 'blobs'):.1f} MB"
                  if db.exists() else "[dim]nothing yet[/dim]")
        led.close()
        console.print(t)
        console.print("\n[dim]Reports can only reach as far back as this window. "
                      "Change it with: tokunseba retention keep 1y[/dim]")

    @retention.command("keep")
    @click.argument("window")
    @click.option("--bodies", default=None,
                  help="A shorter window for stored request bodies, which are the bulkiest "
                       "part. Defaults to 14d.")
    def retention_keep(window: str, bodies: str | None) -> None:
        """Keep history for WINDOW: 24h, 30d, 6w, 6m, 1y, or forever.

        Examples: tokunseba retention keep 1y   ·   tokunseba retention keep forever
        """
        cfg = config.load()
        days = parse_days(window)
        if bodies is not None:
            bdays = parse_days(bodies)
            if days and bdays > days:
                err.print(f"[yellow]Bodies cannot outlive the history they belong to. "
                          f"Clamping to {humanise(days)}.[/yellow]")
                bdays = days
            cfg.retention.keep_bodies_days = bdays
        cfg.retention.days = days
        config.save(cfg)
        console.print(f"Keeping history for [bold]{humanise(days)}[/bold]"
                      f", bodies for {humanise(cfg.retention.keep_bodies_days or days)}.")
        if days == 0:
            console.print("[dim]Nothing will ever be pruned. The ledger grows without "
                          "bound, which is fine but worth knowing.[/dim]")

    @retention.command("auto")
    @click.argument("state", type=click.Choice(["on", "off"]))
    def retention_auto(state: str) -> None:
        """Turn the once-a-day automatic prune on or off."""
        cfg = config.load()
        cfg.retention.auto_prune = state == "on"
        config.save(cfg)
        console.print(f"Automatic pruning is [bold]{state}[/bold].")

    @retention.command("prune")
    @click.option("--keep", default=None,
                  help="Prune to this window just this once, without changing the setting.")
    def retention_prune(keep: str | None) -> None:
        """Delete everything older than the window, now."""
        from .ledger import Ledger
        from .retention import run
        cfg = config.load()
        if keep is not None:
            cfg.retention.days = parse_days(keep)
        if cfg.retention.days <= 0:
            console.print("[dim]The window is 'forever', so there is nothing to prune. "
                          "Set one with: tokunseba retention keep 90d[/dim]")
            return
        led = Ledger(config.home() / "ledger.sqlite")
        t0 = time.time()
        out = run(cfg, led, config.home())
        led.close()
        console.print(f"Removed {out['rows']} request rows, {out['blobs']} blobs and "
                      f"{out['bodies']} stored bodies in {time.time() - t0:.1f}s.")
