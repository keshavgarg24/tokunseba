"""The `tokunseba tier` command group.

tokunseba is four layers, and which of them are on decides both how much it saves and how
much it is allowed to change. That was only ever visible as three booleans in a TOML file,
which is not a fair way to present a decision about whether a tool may rewrite your
prompts. This prints the decision in words and takes it one tier at a time.
"""
from __future__ import annotations

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import config

console = Console()
err = Console(stderr=True)


class Tier:
    """One layer: what it does, what it may change, and which config flag holds it."""

    def __init__(self, n: int, name: str, flag: str | None, does: str, changes: str,
                 detail: str):
        self.n, self.name, self.flag = n, name, flag
        self.does, self.changes, self.detail = does, changes, detail

    def on(self, cfg) -> bool:
        return True if self.flag is None else bool(getattr(cfg, self.flag))


TIERS: list[Tier] = [
    Tier(
        0, "observe", None,
        "Counts tokens, records what the cache did, writes the ledger.",
        "Nothing. Every byte is forwarded exactly as the client sent it.",
        "This is what makes the reports possible and it cannot be switched off while the "
        "proxy is running, because a proxy that records nothing is a proxy you cannot "
        "check. It costs a few hundred microseconds per request and some disk. If you "
        "want none of it, stop the proxy: tokunseba off",
    ),
    Tier(
        1, "reversible", "lossless",
        "Canonicalises tool results, replaces a repeated result with a pointer to the "
        "first one, and replaces a re-read file with the diff since you last saw it.",
        "Tool results only. Never your prompts, never the assistant's replies, never "
        "system instructions.",
        "Every replacement carries a handle, and tokunseba expand HANDLE returns the "
        "original text byte for byte. The assistant can call the same thing through the "
        "MCP server, so nothing is unrecoverable. This is where most of the saving comes "
        "from and it is the last thing you should turn off.",
    ),
    Tier(
        2, "reach-preserving", "reach_preserving",
        "Summarises long program output down to its structure, and replaces lock files, "
        "minified bundles and binaries with a one-line description.",
        "The shape of a long tool result. The assistant sees a summary and a handle "
        "rather than ten thousand lines.",
        "Reach-preserving means the full text stays one call away rather than gone. The "
        "risk it carries is real but bounded: if the answer depended on line 4000 of a "
        "log, the assistant has to ask for it instead of already having it. Turn this "
        "off if you work with output where every line matters and you would rather pay "
        "for all of it. Tier 1 keeps working without it.",
    ),
    Tier(
        3, "opt-in", "tier3",
        "Can send a turn to a different model, redact credentials before they leave the "
        "machine, and label tool results that look like prompt injection.",
        "Which model answers, and the text of a request. This is the only tier that can "
        "change the answer you get.",
        "Off by default and gated twice over: a change only happens when the judge is "
        "confident, and every session is randomly assigned to a control or treatment arm "
        "so the reports can show you what the treatment actually did. Nothing here is on "
        "merely because the tier is on; see tokunseba route and tokunseba config show.",
    ),
]

BY_N = {t.n: t for t in TIERS}


def tier_table(cfg) -> Table:
    t = Table(header_style="dim", box=None)
    t.add_column("", justify="right", style="dim")
    t.add_column("tier")
    t.add_column("state")
    t.add_column("what it may change", overflow="fold")
    for tier in TIERS:
        on = tier.on(cfg)
        if tier.flag is None:
            state = "[dim]always on[/dim]"
        elif on:
            state = "[green]on[/green]"
        else:
            state = "[yellow]off[/yellow]"
        t.add_row(str(tier.n), escape(tier.name), state, f"[dim]{escape(tier.changes)}[/dim]")
    return t


def _resolve(which: str) -> Tier:
    """Accept a number or a name, because both are what people type."""
    key = which.strip().lower()
    if key.isdigit() and int(key) in BY_N:
        return BY_N[int(key)]
    for tier in TIERS:
        if tier.name == key:
            return tier
    err.print(f"No tier called {escape(which)}. Try: 0, 1, 2, 3, or "
              + ", ".join(t.name for t in TIERS))
    raise SystemExit(2)


def register(main: click.Group) -> None:
    @main.group("tier", invoke_without_command=True)
    @click.pass_context
    def tier(ctx: click.Context) -> None:
        """Show and change how much tokunseba is allowed to do."""
        if ctx.invoked_subcommand is None:
            ctx.invoke(tier_status)

    @tier.command("status")
    def tier_status() -> None:
        """Show which tiers are on and what each one is permitted to change."""
        cfg = config.load()
        console.print(tier_table(cfg))
        if not cfg.lossless:
            console.print("\n[yellow]Tier 1 is off, so nothing is being transformed at "
                          "all and tier 2 cannot run either.[/yellow]")
        console.print("\n[dim]tokunseba tier explain 2    what a tier does, in full[/dim]")
        console.print("[dim]tokunseba tier disable 2    turn one off[/dim]")

    @tier.command("explain")
    @click.argument("which")
    def tier_explain(which: str) -> None:
        """Say in full what one tier does, what it changes, and what that costs."""
        cfg = config.load()
        tier = _resolve(which)
        state = ("always on" if tier.flag is None
                 else "on" if tier.on(cfg) else "off")
        console.print(f"[bold]tier {tier.n}: {escape(tier.name)}[/bold] [dim]({state})[/dim]\n")
        for heading, text in (("does", tier.does), ("changes", tier.changes),
                              ("in practice", tier.detail)):
            console.print(f"[dim]{heading}[/dim]")
            console.print(f"  {escape(text)}\n")

    @tier.command("enable")
    @click.argument("which")
    @click.option("-y", "--yes", is_flag=True, help="Do not ask for confirmation.")
    def tier_enable(which: str, yes: bool) -> None:
        """Turn a tier on, after saying what it will be allowed to change."""
        _set(which, True, yes)

    @tier.command("disable")
    @click.argument("which")
    @click.option("-y", "--yes", is_flag=True, help="Do not ask for confirmation.")
    def tier_disable(which: str, yes: bool) -> None:
        """Turn a tier off. Tokens go up; nothing else about your setup changes."""
        _set(which, False, yes)


def _set(which: str, on: bool, yes: bool) -> None:
    cfg = config.load()
    tier = _resolve(which)
    if tier.flag is None:
        err.print("Tier 0 only observes and cannot be turned off while the proxy runs. "
                  "To stop everything: tokunseba off")
        raise SystemExit(2)
    if tier.on(cfg) == on:
        console.print(f"[dim]Tier {tier.n} ({escape(tier.name)}) is already "
                      f"{'on' if on else 'off'}.[/dim]")
        return
    console.print(f"[bold]tier {tier.n}: {escape(tier.name)}[/bold]")
    console.print(f"[dim]{escape(tier.does)}[/dim]")
    console.print(f"[dim]It may change: {escape(tier.changes)}[/dim]")
    if on and tier.n == 3:
        console.print("\n[yellow]This is the only tier that can change which model answers "
                      "you.[/yellow] [dim]Turning it on enables nothing by itself: each "
                      "behaviour is separate, and tokunseba route shows what would "
                      "fire.[/dim]")
    if not on and tier.n == 1:
        console.print("\n[yellow]Tier 2 runs inside tier 1, so this turns both off and "
                      "tokunseba will save almost nothing.[/yellow]")
    if not yes and not click.confirm(
            f"\n{'Enable' if on else 'Disable'} tier {tier.n}?", default=on):
        console.print("[dim]Nothing changed.[/dim]")
        return
    setattr(cfg, tier.flag, on)
    config.save(cfg)
    console.print(f"[green]Tier {tier.n} is {'on' if on else 'off'}.[/green]")
    console.print("Restart the proxy so it picks this up: [bold]tokunseba restart[/bold]")
