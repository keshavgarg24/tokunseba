"""The `tokunseba apps` command group: routing for applications the Dock starts.

Separate from `tokunseba on` because it is a different kind of change. `on` edits files that
belong to your tools and to tokunseba. This edits the login session every application on the
machine inherits, so it asks first and prints the exact commands it would run.
"""
from __future__ import annotations

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import config
from .detect import guiapps

console = Console()
err = Console(stderr=True)

WHY = (
    "A terminal reads your shell profile every time it opens, so `tokunseba init` is enough "
    "for anything you start by typing. An application you start from the Dock, Spotlight or "
    "a desktop menu never reads that file, so it never learns the proxy exists and goes "
    "straight to the provider instead. Nothing fails; the report just stays empty."
)


def _table(port: int) -> Table:
    want = guiapps.values(port)
    have = guiapps.current()
    dim = "dim"
    t = Table(box=None, header_style=dim, pad_edge=False)
    t.add_column(" ")
    t.add_column("variable")
    t.add_column("what a Dock-launched app sees", overflow="fold")
    for name in guiapps.VARS:
        got = have.get(name) or ""
        ok = got == want[name]
        t.add_row("[green]ok[/green]" if ok else "[yellow]--[/yellow]", escape(name),
                  escape(got) if got else f"[{dim}]not set, so the provider default[/{dim}]")
    return t


def register(main: click.Group) -> None:
    @main.group("apps", invoke_without_command=True)
    @click.pass_context
    def apps(ctx: click.Context) -> None:
        """Route applications started from the Dock, not just from a terminal."""
        if ctx.invoked_subcommand is None:
            ctx.invoke(apps_status)

    @apps.command("status")
    def apps_status() -> None:
        """Show what an application launched from the Dock would actually connect to."""
        port = config.load().port
        if not guiapps.supported():
            console.print(f"[dim]{escape(WHY)}[/dim]\n")
            console.print("[yellow]This platform has no per-session environment tokunseba "
                          "can set for you.[/yellow] Run these once, then sign out and "
                          "back in:\n")
            for line in guiapps.manual(port):
                console.print(f"  {escape(line)}")
            return
        console.print(_table(port))
        if guiapps.configured(port):
            console.print("\n[green]GUI applications route through tokunseba.[/green] "
                          "[dim]Ones already open keep the environment they started with; "
                          "quit and reopen them.[/dim]")
            console.print("[dim]tokunseba apps off    take it back out[/dim]")
        else:
            console.print(f"\n[dim]{escape(WHY)}[/dim]")
            console.print("\n[bold]tokunseba apps on[/bold] [dim]fixes this. It prints "
                          "what it will change before changing anything.[/dim]")

    @apps.command("on")
    @click.option("-y", "--yes", is_flag=True, help="Do not ask for confirmation.")
    def apps_on(yes: bool) -> None:
        """Make Dock-launched applications route through the proxy, after saying how."""
        port = config.load().port
        if not guiapps.supported():
            ctx = click.get_current_context()
            ctx.invoke(apps_status)
            raise SystemExit(2)
        if guiapps.configured(port):
            console.print("[dim]GUI applications already route through tokunseba.[/dim]")
            return
        console.print(f"[dim]{escape(WHY)}[/dim]\n")
        console.print("[bold]This will change your login session, not just this project."
                      "[/bold]\n")
        for line in guiapps.plan(port):
            console.print(f"  {escape(line)}")
        console.print(
            "\n[dim]Every application you open afterwards inherits these four variables, "
            "not only AI tools. A program that reads none of them is unaffected. "
            "tokunseba apps off removes them.[/dim]")
        if not yes and not click.confirm("\nApply this?", default=False):
            console.print("[dim]Nothing changed.[/dim]")
            return
        for line in guiapps.apply(port):
            console.print(f"  {escape(line)}")
        console.print("\n[green]Done.[/green] [dim]Quit and reopen any application you want "
                      "routed: a running one keeps the environment it started with.[/dim]")
        console.print("[dim]Then check it worked:  tokunseba verify[/dim]")

    @apps.command("off")
    def apps_off() -> None:
        """Stop routing Dock-launched applications. Terminals are not affected."""
        port = config.load().port
        if not guiapps.supported():
            console.print("[dim]Nothing to remove on this platform.[/dim]")
            return
        for line in guiapps.restore(port):
            console.print(f"  {escape(line)}")
        console.print("[green]GUI applications go straight to the provider again.[/green] "
                      "[dim]Quit and reopen them to pick this up. Terminals still route "
                      "through tokunseba; use tokunseba off for those.[/dim]")
