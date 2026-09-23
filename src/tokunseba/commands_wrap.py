"""Commands that run a tool through tokunseba with the proxy in its environment.

Kept in its own module so the command surface can grow without `cli.py` becoming a
thousand-line file. `register(main)` attaches everything to the root click group.
"""
from __future__ import annotations

import shutil
import subprocess
import time

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import config
from .service import running
from .wrap import UNSUPPORTED, available, build_env, exec_wrapped, full_env, resolve

console = Console()
err = Console(stderr=True)


def ensure_proxy(cfg, quiet: bool = False) -> bool:
    """Start the proxy if it is not already listening. Returns True when it is up."""
    if running(cfg.port):
        return True
    exe = shutil.which("tokunseba")
    if exe is None:
        err.print("[red]tokunseba is not on PATH, so the proxy cannot be started.[/red]")
        return False
    if not quiet:
        console.print(f"[dim]Starting the proxy on 127.0.0.1:{cfg.port}...[/dim]")
    subprocess.Popen([exe, "start", "--foreground"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    for _ in range(50):
        if running(cfg.port):
            return True
        time.sleep(0.2)
    err.print(f"[red]The proxy did not come up on port {cfg.port}.[/red]")
    return False


def register(main: click.Group) -> None:
    @main.command(context_settings={"ignore_unknown_options": True})
    @click.argument("tool")
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    def wrap(tool: str, args: tuple[str, ...]) -> None:
        """Run a tool with tokunseba in its environment.

        This is the reliable way in. Writing a tool's settings file can be overridden by an
        exported base URL, and several launchers export one. Wrapping sets the variables on
        the tool's own process, so nothing inherited can win, and it changes nothing on disk.

        Examples: tokunseba wrap claude   ·   tokunseba wrap codex -- --model gpt-5
        """
        cfg = config.load()
        key = tool.lower()
        if key in UNSUPPORTED:
            err.print(f"[yellow]{escape(tool)} cannot be routed.[/yellow] {UNSUPPORTED[key]}")
            raise SystemExit(2)
        target = resolve(key, cfg.port)
        if target is None:
            names = ", ".join(sorted(w.name for w, _ in available(cfg.port)))
            err.print(f"[red]Unknown tool '{escape(tool)}'.[/red] Known: {names}")
            err.print("For anything else: tokunseba wrap-any -- <command>")
            raise SystemExit(2)
        if shutil.which(target.binary) is None:
            err.print(f"[red]{escape(target.binary)} is not on PATH.[/red]")
            raise SystemExit(127)
        if not ensure_proxy(cfg):
            raise SystemExit(1)
        code = exec_wrapped(target.binary, list(args), build_env(target.env))
        raise SystemExit(code)

    @main.command("wrap-any", context_settings={"ignore_unknown_options": True})
    @click.argument("command", nargs=-1, type=click.UNPROCESSED, required=True)
    def wrap_any(command: tuple[str, ...]) -> None:
        """Run any command with every tokunseba base URL exported.

        Use it for a tool that is not in the known list, or for a whole shell:
        tokunseba wrap-any -- zsh
        """
        cfg = config.load()
        if not ensure_proxy(cfg):
            raise SystemExit(1)
        argv = list(command)
        code = exec_wrapped(argv[0], argv[1:], build_env(full_env(cfg.port)))
        if code == 127:
            err.print(f"[red]{escape(argv[0])} is not on PATH.[/red]")
        raise SystemExit(code)

    @main.command("wrappable")
    def wrappable() -> None:
        """List the tools tokunseba can run, and which are installed here."""
        cfg = config.load()
        t = Table(header_style="dim", box=None)
        t.add_column("tool")
        t.add_column("installed")
        t.add_column("command")
        t.add_column("what it is")
        for w, present in available(cfg.port):
            t.add_row(escape(w.name),
                      "[green]yes[/green]" if present else "[dim]-[/dim]",
                      f"tokunseba wrap {escape(w.name)}",
                      escape(w.note))
        console.print(t)
        for name, why in sorted(UNSUPPORTED.items()):
            console.print(f"[dim]{escape(name)}: {escape(why)}[/dim]")
        console.print("\n[dim]Anything else: tokunseba wrap-any -- <command>[/dim]")
