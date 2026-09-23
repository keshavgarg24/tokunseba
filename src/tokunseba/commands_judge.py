"""The `tokunseba judge` command group.

The local judge is the one part of tokunseba with a real footprint, so it gets its own
explicit lifecycle: nothing is downloaded, imported or held in memory until somebody asks
for it by name, and one command gives all of it back.
"""
from __future__ import annotations

import time

import click
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from . import config
from .judge.laya_judge import (DOWNLOAD_MB, RESIDENT_MB, installed,
                               weights_cached)

console = Console()
err = Console(stderr=True)

EXTRA_HINT = 'uv tool install "tokunseba[laya]"'

WHAT_IT_BUYS = (
    "It reads the opening prompt of a conversation and labels the domain, the output type "
    "and the difficulty. Those labels sharpen the summariser, and if you turn tier 3 on they "
    "are what decides whether a turn is easy enough to route to a cheaper or local model."
)


# One definition of "is the extra here", shared with the backend so a status command and
# the judge chain can never disagree about it.
_installed = installed


def _cached_repo(model_id: str):
    """The huggingface_hub cache entry for this checkpoint, or None.

    Going through scan_cache_dir rather than measuring the directory is not fussiness. Hub
    keeps large files in a shared content-addressed store and links to them, so the model
    directory itself is a few megabytes while the weights are several hundred somewhere
    else. Walking the directory would under-report the size by two orders of magnitude and
    deleting it would leave the weights behind.
    """
    try:
        from huggingface_hub import scan_cache_dir
    except ImportError:
        return None
    try:
        for repo in scan_cache_dir().repos:
            if repo.repo_id == model_id:
                return repo
    except Exception:  # noqa: BLE001 - a corrupt cache must not break a status command
        return None
    return None


def _disk_mb(model_id: str) -> int | None:
    repo = _cached_repo(model_id)
    return None if repo is None else repo.size_on_disk // (1024 * 1024)


def cost_notice() -> Panel:
    """The disclosure shown before anything is downloaded or enabled."""
    from rich.console import Group
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold", no_wrap=True)
    grid.add_column(overflow="fold")
    grid.add_row("One-time download", f"about {DOWNLOAD_MB} MB, kept under "
                                      "~/.cache/huggingface")
    grid.add_row("Memory while loaded", f"about {RESIDENT_MB} MB of RAM, held for as long as "
                                        "the proxy runs")
    grid.add_row("Where it runs", "entirely on this machine, on CPU or Apple Silicon. No key, "
                                  "no account, and no network call after the download")
    grid.add_row("Licence", "Apache 2.0")
    tail = (f"\n{WHAT_IT_BUYS}\n\n"
            "[dim]Tiers 0 to 2, the caching, dedup and summarising that do most of the "
            "saving, need none of this. On a machine with 8 GB of RAM this is a noticeable "
            "share of it. Turn it off at any time with: tokunseba judge disable[/dim]")
    return Panel(Group(grid, tail), title="the local judge", title_align="left",
                 border_style="dim")


def register(main: click.Group) -> None:
    @main.group("judge", invoke_without_command=True)
    @click.pass_context
    def judge(ctx: click.Context) -> None:
        """Manage the optional local judge model.

        Off by default. It costs an ~800 MB download and ~2.2 GB of RAM while loaded, and
        nothing outside tier 3 depends on it.
        """
        if ctx.invoked_subcommand is None:
            ctx.invoke(judge_status)

    @judge.command("status")
    def judge_status() -> None:
        """Show whether the judge is on, what it costs here, and what it is used for."""
        cfg = config.load()
        installed = _installed()
        size = _disk_mb(cfg.judge.laya_model)
        t = Table(header_style="dim", box=None)
        t.add_column("")
        t.add_column("")
        on = cfg.judge.enabled
        t.add_row("state", "[green]enabled[/green]" if on else "[dim]disabled (default)[/dim]")
        t.add_row("model", escape(cfg.judge.laya_model))
        t.add_row("extra installed",
                  "[green]yes[/green]" if installed
                  else f"[yellow]no - {escape(EXTRA_HINT)}[/yellow]")
        if size is not None:
            t.add_row("weights", f"[green]on disk[/green] ({size} MB)")
        else:
            t.add_row("weights", "[yellow]not downloaded - tokunseba judge install[/yellow]")
        t.add_row("memory when loaded", f"about {RESIDENT_MB} MB")
        t.add_row("device", escape(cfg.judge.laya_device))
        t.add_row("loads at startup", "yes" if (on and cfg.judge.warm) else
                  "no, on first use" if on else "-")
        t.add_row("in the request path", "yes (adds latency)" if cfg.judge.inline
                  else "no, it runs after the response and only feeds reports")
        t.add_row("gate", str(cfg.judge.gate_threshold))
        console.print(t)
        if not on:
            console.print(f"\n[dim]{WHAT_IT_BUYS}[/dim]")
            console.print("\nTurn it on with: [bold]tokunseba judge enable[/bold]")
            return
        console.print(
            "\n[dim]Measured on real prompts: domain classification is strong and confident, "
            "difficulty is ordered correctly but its confidence stays below the gate, so it "
            "informs reports and never silently changes a model or an answer. "
            "See it on your own history with: tokunseba advise[/dim]")

    @judge.command("enable")
    @click.option("--warm", is_flag=True,
                  help="Load the weights when the proxy starts instead of on first use. "
                       "Costs the memory from startup; saves a one-time pause later.")
    @click.option("--device", default=None,
                  help="Force a device: cpu, mps, cuda. Default picks the best available.")
    @click.option("--download/--no-download", default=True, show_default=True,
                  help="Fetch the weights now if they are missing.")
    @click.option("-y", "--yes", is_flag=True, help="Do not ask for confirmation.")
    def judge_enable(warm: bool, device: str | None, download: bool, yes: bool) -> None:
        """Turn the local judge on, after saying plainly what that costs."""
        cfg = config.load()
        console.print(cost_notice())
        if not _installed():
            err.print("\n[yellow]The laya extra is not installed here.[/yellow] Install it with:")
            err.print(f"  {escape(EXTRA_HINT)}")
            err.print("\nThen run [bold]tokunseba judge enable[/bold] again.")
            raise SystemExit(2)
        have = weights_cached(cfg.judge.laya_model)
        if not yes:
            ask = ("Enable the judge?" if have else
                   f"Enable the judge and download about {DOWNLOAD_MB} MB now?")
            if not click.confirm(f"\n{ask}", default=False):
                console.print("[dim]Nothing changed.[/dim]")
                return
        cfg.judge.enabled = True
        cfg.judge.warm = warm
        if device:
            cfg.judge.laya_device = device
        config.save(cfg)
        console.print("[green]The judge is enabled.[/green]")
        if not have and download:
            _download(cfg)
        elif not have:
            console.print("[dim]Weights are not on disk yet. They download on first use, or "
                          "now with: tokunseba judge install[/dim]")
        console.print("Restart the proxy so it picks this up: [bold]tokunseba restart[/bold]")

    @judge.command("disable")
    @click.option("--purge", is_flag=True,
                  help="Also delete the downloaded weights from disk.")
    def judge_disable(purge: bool) -> None:
        """Turn the local judge off. The memory comes back when the proxy restarts."""
        cfg = config.load()
        cfg.judge.enabled = False
        cfg.judge.warm = False
        cfg.judge.inline = False
        config.save(cfg)
        console.print("[green]The judge is disabled.[/green] Nothing will import torch or "
                      "hold the weights once the proxy restarts.")
        if purge:
            _purge(cfg)
        else:
            size = _disk_mb(cfg.judge.laya_model)
            if size is not None:
                console.print(f"[dim]The {size} MB of weights are still on disk. "
                              "Remove them with: tokunseba judge remove[/dim]")
        console.print("Restart the proxy so it picks this up: [bold]tokunseba restart[/bold]")

    @judge.command("install")
    @click.option("--force", is_flag=True, help="Download again even if already cached.")
    def judge_install(force: bool) -> None:
        """Download the judge weights so nothing has to wait for them later."""
        cfg = config.load()
        if not _installed():
            err.print("The laya extra is not installed. Install it with:")
            err.print(f"  {escape(EXTRA_HINT)}")
            raise SystemExit(2)
        if weights_cached(cfg.judge.laya_model) and not force:
            size = _disk_mb(cfg.judge.laya_model)
            console.print("[green]Already downloaded[/green]"
                          f"{f' ({size} MB)' if size is not None else ''}.")
            return
        _download(cfg)

    @judge.command("remove")
    @click.option("-y", "--yes", is_flag=True, help="Do not ask for confirmation.")
    def judge_remove(yes: bool) -> None:
        """Delete the downloaded weights and free the disk space."""
        cfg = config.load()
        repo = _cached_repo(cfg.judge.laya_model)
        if repo is None:
            console.print("[dim]Nothing to remove; the weights are not on disk.[/dim]")
            return
        mb = repo.size_on_disk // (1024 * 1024)
        if not yes and not click.confirm(
                f"Delete {mb} MB at {repo.repo_path}?", default=False):
            console.print("[dim]Nothing changed.[/dim]")
            return
        _purge(cfg)


def _download(cfg) -> None:
    from .judge.laya_judge import LayaJudge
    console.print(f"Downloading the judge weights (about {DOWNLOAD_MB} MB). This runs once.")
    t0 = time.time()
    j = LayaJudge(cfg.judge.laya_model, cfg.judge.laya_device)
    try:
        j.load()
    except Exception as exc:  # noqa: BLE001 - the message is what the user needs, not a trace
        err.print(f"[red]Download failed:[/red] {escape(str(exc)[:200])}")
        raise SystemExit(1) from None
    finally:
        j.unload()
    console.print(f"[green]Ready in {time.time() - t0:.0f}s.[/green] Try it with: "
                  "tokunseba advise")


def _purge(cfg) -> None:
    """Delete the checkpoint through the hub's own cache API.

    Its delete strategy knows about the shared blob store, so it frees the weights
    themselves rather than only the directory of symlinks that points at them.
    """
    repo = _cached_repo(cfg.judge.laya_model)
    if repo is None:
        return
    freed = repo.size_on_disk // (1024 * 1024)
    try:
        from huggingface_hub import scan_cache_dir
        strategy = scan_cache_dir().delete_revisions(
            *[rev.commit_hash for rev in repo.revisions])
        strategy.execute()
    except Exception as exc:  # noqa: BLE001 - report it, do not leave a half-deleted cache
        err.print(f"[red]Could not remove the weights:[/red] {escape(str(exc)[:200])}")
        raise SystemExit(1) from None
    console.print(f"[green]Removed {freed} MB.[/green]")
