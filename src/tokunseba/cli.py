"""tokunseba command line."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import __version__, config
from .ledger import DIFFICULTY_NAMES, Ledger

console = Console()
err = Console(stderr=True)


def _ledger() -> Ledger:
    return Ledger(config.home() / "ledger.sqlite")


def _since(s: str) -> float:
    units = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
    s = (s or "7d").strip()
    try:
        if s[-1] in units:
            return time.time() - float(s[:-1]) * units[s[-1]]
        return time.time() - float(s)
    except (ValueError, IndexError):
        return time.time() - 7 * 86400


def _k(v: int) -> str:
    v = v or 0
    if v >= 1_000_000:
        return f"{v / 1e6:.1f}M"
    if v >= 1000:
        return f"{v / 1e3:.1f}k"
    return str(v)


def _wordmark() -> str:
    """The compact one-line mark. Falls back to plain text until brand.py exists."""
    try:
        from .brand import WORDMARK
    except ImportError:
        return "tokunseba"
    return WORDMARK or "tokunseba"


def _banner(subtitle: str = "") -> str:
    """The shared heading for every command that prints one."""
    try:
        from .brand import banner
    except ImportError:
        tail = f"  [dim]{escape(subtitle)}[/dim]" if subtitle else ""
        return f"[bold]{_wordmark()}[/bold]{tail}"
    return banner(subtitle)


@click.group()
@click.version_option(__version__, prog_name="tokunseba")
def main() -> None:
    """One local proxy in front of every AI coding tool on this machine.

    It makes each request smaller on the way out, keeps every byte it removes retrievable
    with `tokunseba expand`, and forwards your request untouched if anything goes wrong.
    Start with `tokunseba init`, then `tokunseba doctor`.
    """


# --------------------------------------------------------------------------- setup
@main.command()
@click.option("--no-service", is_flag=True, help="Do not install the background service.")
@click.option("--no-hooks", is_flag=True, help="Do not register Claude Code hooks.")
@click.option("--with-mcp", is_flag=True,
              help="Register the MCP expand tool. Only needed for agents with no shell; "
                   "it costs one background process per session.")
@click.option("-y", "--yes", is_flag=True, help="Do not ask. For scripts and images.")
@click.option("--dry-run", is_flag=True, help="Print what it would change and stop.")
def init(no_service: bool, no_hooks: bool, with_mcp: bool, yes: bool, dry_run: bool) -> None:
    """Point every supported tool at the proxy and start it in the background."""
    from . import service
    from .detect import registry
    cfg = config.load()

    # Everything this writes, before any of it is written. init is the first command anybody
    # runs and it edits files in the home directory that the user did not create and may not
    # know exist. A setup step that explains itself and can be refused is the difference
    # between a tool you installed and a tool that installed itself.
    console.print("[bold]This will change files in your home directory.[/bold]\n")
    for line in registry.plan_all(cfg, hooks=not no_hooks, mcp=with_mcp):
        console.print(f"  {escape(line)}")
    if not no_service:
        console.print(f"  install and load the background service at {escape(str(_service_path()))}")
    console.print(
        "\n[dim]Needs: nothing but this machine. No account, no key, no network call, "
        "nothing uploaded. Each tool config is copied to "
        f"{escape(str(config.home() / 'backups'))} before it is touched and your shell "
        "profile gets one marked block, so [bold]tokunseba off[/bold] puts all of it back. "
        "Requests keep their own API keys and still go to the same provider; tokunseba only "
        "makes them smaller on the way.[/dim]")
    if dry_run:
        console.print("\n[dim]Dry run, nothing changed.[/dim]")
        return
    if not yes and not click.confirm("\nGo ahead?", default=True):
        console.print("[dim]Nothing changed.[/dim]")
        return

    config.save(cfg)
    console.print("\n[bold]Configuring tools[/bold]")
    for line in registry.apply_all(cfg, hooks=not no_hooks, mcp=with_mcp):
        console.print(f"  {escape(str(line))}")

    if not no_service:
        path, state = service.install(cfg.port)
        console.print(f"[bold]Service[/bold]\n  {escape(str(path))} ({escape(state)})")

    _print_tools(registry.detect_all())
    console.print("\nOpen a new shell so the environment block takes effect, then run: "
                  "[bold]tokunseba doctor[/bold]")


def _service_path():
    """Where the background service file goes, without importing service until asked."""
    from .service import plist_path, unit_path
    import platform
    return plist_path() if platform.system() == "Darwin" else unit_path()


def _print_tools(tools) -> None:
    t = Table(title="Tools", title_justify="left", header_style="dim")
    t.add_column("tool")
    t.add_column("installed")
    t.add_column("routed")
    t.add_column("note", overflow="fold")
    for s in tools:
        t.add_row(escape(s.name),
                  "yes" if s.installed else "-",
                  "[green]yes[/green]" if s.configured else ("[yellow]no[/yellow]" if s.installed else "-"),
                  escape(s.note or s.config_path))
    console.print(t)


@main.command()
def on() -> None:
    """Re-apply the proxy configuration to every tool."""
    from .detect import registry
    for line in registry.apply_all(config.load()):
        console.print(f"  {escape(str(line))}")
    console.print("[green]tokunseba is in the path again.[/green]")


@main.command()
def off() -> None:
    """Restore every tool's original configuration. The proxy stops being used immediately."""
    from .detect import registry
    for line in registry.restore_all():
        console.print(f"  {escape(str(line))}")
    console.print("[green]Restored. Open a new shell to clear the exported variables.[/green]")


@main.command()
@click.option("--foreground", is_flag=True, help="Run in this terminal instead of the background.")
@click.option("--warm-judge", is_flag=True, help="Load the local judge model at startup.")
def start(foreground: bool, warm_judge: bool) -> None:
    """Run the proxy."""
    import uvicorn

    from .server import build_app
    from .service import install, running
    cfg = config.load()
    if running(cfg.port):
        console.print(f"[yellow]Already listening on 127.0.0.1:{cfg.port}[/yellow]")
        return
    if not foreground:
        path, state = install()
        console.print(f"Started via {path} ({state})")
        return
    app = build_app(cfg, _ledger())
    if warm_judge and not cfg.judge.enabled:
        err.print("[yellow]--warm-judge ignored: the local judge is disabled.[/yellow] "
                  "Turn it on with: tokunseba judge enable")
    elif warm_judge:
        from .judge.laya_judge import RESIDENT_MB
        for b in app.state.proxy.judge.backends:
            if getattr(b, "name", "") == "laya" and b.available():
                console.print(f"Loading the local judge (about {RESIDENT_MB} MB of RAM), "
                              "first run downloads it...")
                try:
                    b.load()
                    console.print("[green]judge ready[/green]")
                except Exception as exc:  # noqa: BLE001
                    err.print(f"[yellow]judge unavailable: {exc}[/yellow]")
    console.print(f"tokunseba listening on [bold]http://127.0.0.1:{cfg.port}[/bold]")
    uvicorn.run(app, host="127.0.0.1", port=cfg.port, log_level="warning")


@main.command()
@click.option("-y", "--yes", is_flag=True, help="Do not ask, even if tools are routed.")
def stop(yes: bool) -> None:
    """Stop the background proxy. Tools still pointed at it will fail until it is back."""
    from . import service
    from .detect import registry
    # Stopping a proxy that tools are configured to use does not quietly fall back to the
    # provider: the base URL still points at a closed port, so the next request fails hard.
    # Better to say so here than to have somebody debug a dead tool.
    routed = [t.name for t in registry.detect_all() if t.configured]
    if routed and not yes:
        console.print(f"[yellow]{escape(', '.join(routed))} still point at "
                      f"127.0.0.1:{config.load().port}.[/yellow] [dim]Stopping the proxy "
                      f"makes them fail to connect until you start it again. To send them "
                      f"back to the provider instead, use: tokunseba off[/dim]")
        if not click.confirm("Stop anyway?", default=False):
            console.print("[dim]Still running.[/dim]")
            return
    console.print(service.stop())


@main.command()
def restart() -> None:
    """Stop the background proxy and start it again, so config changes take effect."""
    from . import service
    console.print(service.stop())
    path, state = service.install(config.load().port)
    console.print(f"Started via {escape(str(path))} ({escape(state)})")


@main.command()
def status() -> None:
    """Show whether the proxy is running and what it saved today."""
    from .service import running
    cfg = config.load()
    up = running(cfg.port)
    console.print(_banner("status"))
    _routing_warning()
    console.print(f"proxy: {'[green]running[/green]' if up else '[red]not running[/red]'} "
                  f"on 127.0.0.1:{cfg.port}")
    s = _ledger().stats(time.time() - 86400)
    console.print(f"today: {s['requests']} requests · {_k(s['tokens_saved'])} tokens saved "
                  f"({s['pct_saved'] * 100:.0f}% of tool output) · "
                  f"cache {s['cache_hit_rate'] * 100:.0f}% · "
                  f"{_k(s['fresh_tokens'])} fresh tokens (the part cache did not cover)")
    console.print(f"next: {_next_action(up, s)}")


@main.command()
def doctor() -> None:
    """Check the installation and report anything that would silently cost tokens."""
    from .detect import registry
    cfg = config.load()
    checks = registry.doctor(cfg, _ledger())
    t = Table(header_style="dim")
    t.add_column(" ")
    t.add_column("check")
    t.add_column("detail", overflow="fold")
    for c in checks:
        t.add_row("[green]ok[/green]" if c.ok else "[yellow]--[/yellow]",
                  escape(c.name), escape(c.detail))
    console.print(t)


@main.command()
def uninstall() -> None:
    """Remove the background service and restore every tool."""
    from . import service
    from .detect import registry
    for line in registry.restore_all():
        console.print(f"  {escape(str(line))}")
    console.print(escape(service.uninstall()))
    console.print(f"Data left in place at {config.home()} — delete it by hand if you want it gone.")


def _next_action(up: bool, s: dict) -> str:
    """The single most useful thing to do next, chosen from what the ledger just showed."""
    events = s.get("events") or {}
    if not up:
        return "start the proxy:  tokunseba start"
    if not s.get("requests"):
        return "use a coding tool once, then:  tokunseba verify"
    if events.get("cache_drift") or events.get("cache_miss_unexplained"):
        return "a cached prefix changed and was re-read in full:  tokunseba ui"
    if s.get("cache_hit_rate", 0.0) < 0.5:
        return "under half the context came from cache:  tokunseba report --since 24h"
    if not s.get("tokens_saved"):
        return "nothing has been rewritten yet:  tokunseba top"
    return "see the whole window:  tokunseba report"


def _routing_problem() -> str:
    """The one sentence that explains an empty report, or "" when tokunseba is in the path."""
    from .health import check
    try:
        return check(config.load(), _ledger()).problem or ""
    except Exception:  # noqa: BLE001
        return ""


def _routing_warning() -> None:
    """Print the one sentence that explains an empty report, before the empty report."""
    from .ui.terminal import style
    problem = _routing_problem()
    if problem:
        console.print(f"[{style('bad')}]not in the path[/]  {escape(problem)}\n")


# --------------------------------------------------------------------------- reporting
@main.command()
@click.option("--since", default="7d", help="e.g. 24h, 7d, 30d")
@click.option("--project", default=None, help="Filter to one project directory.")
@click.option("--ab", is_flag=True, help="Compare the tier 3 control and treatment arms.")
@click.option("--json", "as_json", is_flag=True)
def stats(since: str, project: str | None, ab: bool, as_json: bool) -> None:
    """Show what tokunseba saved.

    Everything is counted in tokens, ratios and time, because those mean the same thing on
    every kind of access. Nothing here depends on the kind of access you have.
    """
    from .ui.terminal import by_tool_table, signal_table, stat_tiles, style
    led = _ledger()
    if not as_json:
        _routing_warning()
    s = led.stats(_since(since), project)
    if as_json:  # the full record, including fields no table has room for
        console.print_json(json.dumps(s))
        return
    dim = style("dim")
    console.print(_banner(f"stats · last {since}"))
    console.print(stat_tiles(s))

    if s["by_tool"]:
        console.print(f"\n[{dim}]by tool[/]")
        console.print(by_tool_table(s["by_tool"]))

    if s["events"]:
        console.print(f"\n[{dim}]signals[/]")
        console.print(signal_table(s["events"]))

    if ab:
        arms = led.stats_ab(_since(since))
        if not arms:
            console.print("[dim]No A/B data. Tier 3 is off, so every session is a control.[/dim]")
        else:
            a = Table(title="tier 3 arms", title_justify="left", header_style="dim", box=None)
            a.add_column("arm")
            cols = ["sessions", "requests/session", "input/session", "output/session",
                    "latency/request"]
            for col in cols:
                a.add_column(col, justify="right")
            for name, v in arms.items():
                row = [escape(name), str(v["sessions"]), str(v["requests_per_session"]),
                       _k(int(v["input_tokens_per_session"])),
                       _k(int(v["output_tokens_per_session"])),
                       f"{v['latency_ms_per_request']:.0f}ms"]
                a.add_row(*row)
            console.print(a)


@main.command()
@click.argument("request_id")
def explain(request_id: str) -> None:
    """Show exactly what was changed in one request, original beside replacement."""
    led = _ledger()
    rows = led.transforms_for(request_id)
    if not rows:
        err.print(f"no transforms recorded for {request_id}")
        raise SystemExit(1)
    orig_body = config.home() / "bodies" / f"{request_id}.orig.json"
    originals: dict[str, str] = {}
    if orig_body.exists():
        try:
            from .protocols.base import sha256_text
            body = json.loads(orig_body.read_text())
            for m in body.get("messages", []):
                for b in (m.get("content") or []) if isinstance(m.get("content"), list) else []:
                    c = b.get("content") if isinstance(b, dict) else None
                    for cb in (c if isinstance(c, list) else [{"text": c}] if isinstance(c, str) else []):
                        txt = cb.get("text") if isinstance(cb, dict) else None
                        if txt:
                            originals[sha256_text(txt)] = txt
        except (ValueError, TypeError, KeyError):
            pass
    for r in rows:
        console.print(f"\n[bold]{escape(r['position'])}[/bold]  {escape(r['kind'])}  "
                      f"{r['orig_tokens']} → {r['new_tokens']} tokens"
                      + (f"  handle {r['handle']}" if r["handle"] else ""))
        base_sha = r["orig_sha"].split("@")[0]
        orig = originals.get(base_sha)
        if orig:
            console.print("[dim]original:[/dim]")
            for line in orig.splitlines()[:3]:
                console.print(f"  {escape(line[:150])}")
        console.print("[dim]sent:[/dim]")
        for line in (r["transformed"] or "").splitlines()[:3]:
            console.print(f"  {escape(line[:150])}")


@main.command()
@click.argument("handle")
def expand(handle: str) -> None:
    """Print the full original text behind a handle."""
    from .transform.handles import HandleStore
    text = HandleStore(config.home() / "blobs").get(handle)
    if text is None:
        err.print(f"unknown handle {handle}")
        raise SystemExit(1)
    click.echo(text)


@main.command()
@click.option("--days", default=None, type=int,
              help="Override the configured retention window for this run.")
def prune(days: int | None) -> None:
    """Delete history older than the retention window.

    The window itself lives in the config; see and change it with `tokunseba retention`.
    """
    from .retention import run as run_prune
    cfg = config.load()
    if days is not None:
        cfg.retention.days = days
    if cfg.retention.days <= 0:
        console.print("[dim]The window is 'forever', so there is nothing to prune. "
                      "Set one with: tokunseba retention keep 90d[/dim]")
        return
    out = run_prune(cfg, _ledger(), config.home())
    console.print(f"removed {out['rows']} request rows, {out['blobs']} blobs, "
                  f"{out['bodies']} stored bodies")


# --------------------------------------------------------------------------- dashboard
def _dashboard(led: Ledger, since: str):
    """Build the whole dashboard as one renderable, from the ledger as it stands now."""
    from rich.console import Group

    from .service import running
    from .ui.terminal import (
        by_tool_table,
        sessions_table,
        signal_table,
        sparkline,
        stat_tiles,
        style,
    )
    cfg = config.load()
    s = led.stats(_since(since))
    up = running(cfg.port)
    live = (f"[{style('good')}]proxy running[/] [{style('dim')}]on 127.0.0.1:{cfg.port}[/]" if up
            else f"[{style('dim')}]proxy not running — start it with: tokunseba start[/]")
    dim = style("dim")

    from .health import check
    try:
        problem = check(cfg, led).problem
    except Exception:  # noqa: BLE001
        problem = None
    warning = f"[{style('bad')}]not in the path[/]  {escape(problem)}\n" if problem else ""

    return Group(
        _banner(f"last {since}"),
        live,
        warning,
        "",
        stat_tiles(s),
        "",
        f"[{dim}]tokens saved per day[/]",
        f"[{style('accent')}]{sparkline(led.daily(14))}[/]",
        "",
        f"[{dim}]by tool[/]",
        by_tool_table(s["by_tool"]),
        "",
        f"[{dim}]signals[/]",
        signal_table(s["events"]),
        "",
        f"[{dim}]recent sessions[/]",
        sessions_table(led.recent_sessions(8)),
    )


@main.command()
@click.option("--watch", "-w", "watch_flag", is_flag=True,
              help="Redraw every 2 seconds until Ctrl-C.")
@click.option("--since", default="7d", help="e.g. 24h, 7d, 30d")
def ui(watch_flag: bool, since: str) -> None:
    """Show the dashboard in this terminal. No browser, ever."""
    _render_dashboard(watch_flag, since)


@main.command("watch")
@click.option("--since", default="7d", help="e.g. 24h, 7d, 30d")
def watch_cmd(since: str) -> None:
    """Live dashboard. The same as: tokunseba ui --watch"""
    _render_dashboard(True, since)


def _render_dashboard(watching: bool, since: str) -> None:
    led = _ledger()
    if not watching:
        console.print(_dashboard(led, since))
        return
    from rich.live import Live
    try:
        with Live(_dashboard(led, since), console=console, refresh_per_second=4) as live:
            while True:
                time.sleep(2)
                live.update(_dashboard(led, since))
    except KeyboardInterrupt:  # Ctrl-C is how you leave; it is not a failure
        console.print("[dim]stopped watching[/dim]")


# --------------------------------------------------------------------------- verify
@main.command()
def verify() -> None:
    """Prove tokunseba is in the path and saving tokens, with evidence rather than claims."""
    from .detect import registry
    from .service import running
    from .ui.terminal import check_table, k, pct, style, transform_kind_table
    cfg = config.load()
    led = _ledger()
    since = time.time() - 86400
    s = led.stats(since)
    summary = led.transform_summary(since)
    applied = sum(r["count"] for r in summary)
    saved = sum(r["saved"] for r in summary)
    drift = sum(s["events"].get(kind, 0) for kind in ("cache_drift", "cache_miss_unexplained"))

    console.print(_banner("verify · last 24h"))
    if s["requests"] == 0 and applied == 0:
        console.print(
            "\nNothing has been recorded yet, so there is nothing to verify.\n"
            "To generate data:\n"
            "  1. [bold]tokunseba init[/bold]    point your tools at the proxy\n"
            "  2. [bold]tokunseba start[/bold]   run the proxy in the background\n"
            "  3. open a new shell and use your coding tool once\n"
            "  4. [bold]tokunseba verify[/bold]  run this again")
        return

    routed = [t.name for t in registry.detect_all() if t.configured]
    checks = [
        ("proxy reachable", running(cfg.port), f"127.0.0.1:{cfg.port}", True),
        ("a tool is routed through it", bool(routed),
         ", ".join(routed) if routed else "no tool configured — run: tokunseba init", True),
        ("requests recorded in the last 24h", s["requests"] > 0,
         f"{s['requests']} requests across {len(s['by_tool'])} tools", True),
        ("transforms actually applied", applied > 0,
         f"{applied} transforms, {len(summary)} kinds, {k(saved)} tokens saved", True),
        ("cache is being read back", s["cache_read"] > 0,
         f"{pct(s['cache_hit_rate'])} of input tokens, {k(s['cache_read'])} from cache", False),
        ("no cache drift", drift == 0,
         "clean" if drift == 0 else
         f"{drift} drift signal{'s' if drift != 1 else ''} — see: tokunseba ui", False),
    ]
    console.print(check_table([(n, ok, detail) for n, ok, detail, _ in checks]))

    if summary:
        console.print(f"\n[{style('dim')}]transforms by kind[/]")
        console.print(transform_kind_table(summary))

    failed = [name for name, ok, _d, essential in checks if essential and not ok]
    # The detail, not the name: half these checks are named for the good state, so printing
    # the name of a failing one says the opposite of what happened. "no cache drift" as a
    # footnote reads as reassurance when it means six of them.
    advisory = [d for _n, ok, d, essential in checks if not essential and not ok]
    if failed:
        console.print(f"\n[{style('bad')}]not verified[/] — failed: "
                      + escape("; ".join(failed)))
        raise SystemExit(1)
    note = ""
    if advisory:
        note = " [dim](" + escape("; ".join(advisory)) + ")[/dim]"
    console.print(f"\n[{style('good')}]verified[/] — {k(saved)} tokens saved in the last 24h"
                  f" across {applied} transform{'s' if applied != 1 else ''}.{note}")


# --------------------------------------------------------------------------- top
@main.command()
@click.option("--since", default="7d", help="e.g. 24h, 7d, 30d")
@click.option("--limit", default=15, show_default=True, help="Rows per table.")
def top(since: str, limit: int) -> None:
    """Show where the tokens went: the biggest savings, and what could not be helped."""
    from .ui.terminal import histogram, passthrough_table, style, transform_table
    led = _ledger()
    ts = _since(since)
    wins = led.top_transforms(ts, limit)
    misses = led.biggest_passthroughs(ts, limit)
    console.print(_banner(f"top · last {since}"))
    _routing_warning()
    console.print(f"\n[{style('dim')}]tool results by size — where the compressible mass is[/]")
    console.print(histogram(led.tool_result_histogram(ts)))
    console.print(f"\n[{style('dim')}]biggest savings[/]")
    console.print(transform_table(wins))
    console.print(f"\n[{style('dim')}]biggest untouched blocks — "
                  "what tokunseba could not help with[/]")
    console.print(passthrough_table(misses))
    if wins:
        console.print(f"\n[dim]See one request in full with: "
                      f"tokunseba explain {escape(str(wins[0]['request_id']))}[/dim]")


# --------------------------------------------------------------------------- report
def _report_data(led: Ledger, since: str, project: str | None = None) -> dict:
    """Every number the report shows, fetched once so the text and the JSON cannot disagree.

    `project` filters the request-side figures. Tool results are stored per block and carry
    no project, so the size, transform and passthrough views are always machine wide.
    """
    ts = _since(since)
    sessions = led.recent_sessions(10)
    return {
        "window": {"since": since, "since_ts": ts, "project": project or ""},
        "summary": led.summary_counts(ts),
        "stats": led.stats(ts, project),
        "daily": led.daily(14),
        "hourly": led.hourly(24),
        "sizes": led.tool_result_histogram(ts),
        "transforms": led.transform_summary(ts),
        "by_model": led.model_breakdown(ts),
        "top_transforms": led.top_transforms(ts, 10),
        "passthroughs": led.biggest_passthroughs(ts, 10),
        "signals": led.signal_breakdown(ts),
        "sessions": sessions,
        "context_growth": led.context_growth(sessions[0]["id"]) if sessions else [],
    }


def _mix_note(mix: dict) -> str:
    """One line under the prompt mix, saying what it means for routing.

    The point of showing the mix at all is the decision it supports, so this names the
    easy share and the command that would act on it rather than leaving the reader to
    work out that a bar chart of difficulties is a routing proposal.
    """
    judged = int(mix.get("judged") or 0)
    if not judged:
        return ("Nothing judged in this window. The judge reads the opening prompt of each "
                "conversation; it needs no model and no key.")
    levels = mix.get("levels") or {}
    easy = int(levels.get("trivial") or 0) + int(levels.get("easy") or 0)
    unsure = int(levels.get("unsure") or 0)
    parts = [f"{judged} conversations judged", f"{judged - unsure} read confidently"]
    if mix.get("needs_tools"):
        parts.append(f"{mix['needs_tools']} reached for a file, a repo or the web")
    if mix.get("sensitive"):
        parts.append(f"{mix['sensitive']} looked sensitive")
    tail = ("" if not easy else
            f" {easy} opened trivially or easily; a rule could send those to a smaller "
            f"model: tokunseba route add --max-difficulty 1 --model MODEL")
    return " · ".join(parts) + ("." + tail if tail else ".")


def _report_group(data: dict, problem: str = ""):
    """The whole report as one renderable, so the terminal and the saved file agree.

    Every section renders on an empty ledger: the tables say so in words rather than
    disappearing, because a blank page does not tell you whether anything is wrong.
    """
    from rich.console import Group

    from .ui.terminal import (
        by_tool_table,
        context_curve,
        histogram,
        k,
        kv_panel,
        mix_table,
        model_table,
        passthrough_table,
        sessions_table,
        signal_table,
        sparkline,
        stat_tiles,
        style,
        transform_kind_table,
        transform_table,
    )
    s, counts, window = data["stats"], data["summary"], data["window"]
    dim, accent = style("dim"), style("accent")
    hours, curve = data["hourly"], data["context_growth"]
    mix = data.get("signals") or {"domains": {}, "levels": {}}

    def label(text: str) -> str:
        return f"\n[{dim}]{escape(text)}[/]"

    def line(text: str) -> str:
        return f"[{accent}]{text}[/]"

    pairs = [
        ("window", f"last {window['since']}"),
        ("project", window["project"] or "every project on this machine"),
        ("sessions", f"{counts['sessions']} across {counts['projects']} projects"),
        ("requests", f"{counts['requests']} on {counts['models']} models"),
        ("tool results", f"{counts['transforms']} seen, {counts['handles']} kept behind handles"),
        ("counted in", "tokens, ratios and time — true on any kind of access"),
    ]
    fresh = sum(int(h.get("input_tokens") or 0) for h in hours)
    cached = sum(int(h.get("cache_read") or 0) for h in hours)
    requests = sum(int(h.get("requests") or 0) for h in hours)

    return Group(
        _banner(f"report · last {window['since']}"),
        (f"[{style('bad')}]not in the path[/]  {escape(problem)}" if problem else ""),
        "",
        kv_panel("window", pairs),
        "",
        stat_tiles(s),
        label("tokens saved per day, last 14 days"),
        line(sparkline(data["daily"])),
        label("tokens saved per hour, last 24 hours"),
        line(sparkline(hours)),
        f"[{dim}]{requests} requests · {k(fresh)} fresh · {k(cached)} from cache[/]",
        label("tool results by size — where the compressible mass is"),
        histogram(data["sizes"]),
        label("transforms by kind"),
        transform_kind_table(data["transforms"]),
        label("by tool"),
        by_tool_table(s["by_tool"]),
        label("by model"),
        model_table(data["by_model"]),
        label("biggest savings"),
        transform_table(data["top_transforms"]),
        label("biggest untouched blocks — what tokunseba could not help with"),
        passthrough_table(data["passthroughs"]),
        label("signals"),
        signal_table(s["events"]),
        label("what you asked about — the opening prompt of each conversation"),
        mix_table(mix["domains"], "domain"),
        label("how hard those prompts were"),
        mix_table(mix["levels"], "difficulty", order=list(DIFFICULTY_NAMES)),
        f"[{dim}]{escape(_mix_note(mix))}[/]",
        label("recent sessions"),
        sessions_table(data["sessions"]),
        label(f"context growth in the newest session, {len(curve)} turns"),
        line(context_curve(curve)),
    )


@main.command()
@click.option("--since", default="7d", show_default=True, help="e.g. 24h, 7d, 30d")
@click.option("--project", default=None,
              help="Filter the request figures to one project directory.")
@click.option("--json", "as_json", is_flag=True, help="Print the same numbers as JSON.")
@click.option("--save", "save_path", type=click.Path(dir_okay=False, writable=True),
              default=None, help="Also write the plain text rendering to PATH.")
def report(since: str, project: str | None, as_json: bool,
           save_path: str | None) -> None:
    """The whole picture in one page: context, cache, and where the tokens went.

    Counted in tokens, ratios and time, which is what every kind of access has in common.
    """
    led = _ledger()
    data = _report_data(led, since, project)
    if as_json:
        console.print_json(json.dumps(data, default=str))
        return
    group = _report_group(data, problem=_routing_problem())
    console.print(group)
    if save_path:
        out = Path(save_path)
        with out.open("w", encoding="utf-8") as fh:
            Console(file=fh, width=100, no_color=True,
                    legacy_windows=False).print(group)
        console.print(f"\n[dim]written to {escape(str(out))}[/dim]")


@main.command()
def statusline() -> None:
    """One status line for a coding tool. Reads the tool's JSON on stdin."""
    import httpx
    cfg = config.load()
    cwd = ""
    try:
        data = json.loads(sys.stdin.read() or "{}")
        cwd = data.get("cwd") or (data.get("workspace") or {}).get("current_dir") or ""
        sid = data.get("session_id") or ""
        if sid:
            httpx.post(f"http://127.0.0.1:{cfg.port}/_tokunseba/api/session",
                       json={"session_id": sid, "tool": "claude-code", "cwd": cwd}, timeout=0.3)
    except Exception:  # noqa: BLE001 - a status line must never break the host tool
        pass
    try:
        params = {"since": "1d"}
        if cwd:
            params["project"] = cwd
        s = httpx.get(f"http://127.0.0.1:{cfg.port}/_tokunseba/api/stats",
                      params=params, timeout=0.3).json()
    except Exception:  # noqa: BLE001
        click.echo("tokunseba · offline")
        return
    parts = [f"tokunseba · saved {_k(s['tokens_saved'])} ({s['pct_saved'] * 100:.0f}%)",
             f"cache {s['cache_hit_rate'] * 100:.0f}%",
             f"fresh {_k(s.get('fresh_tokens', 0))}"]
    if cfg.budget.daily_tokens > 0:  # only when somebody has asked for a ceiling
        used = s.get("total_tokens", 0) / cfg.budget.daily_tokens * 100
        parts.append(f"budget {used:.0f}%")
    drift = s["events"].get("cache_drift", 0)
    if drift:
        parts.append(f"drift {drift}")
    click.echo(" · ".join(parts))


@main.command()
@click.option("--since", default="7d", show_default=True)
@click.option("--limit", default=500, show_default=True,
              help="Most recent requests to replay.")
@click.option("--tier", "tiers", multiple=True, type=click.Choice(["1", "2"]),
              help="Replay as though only these tiers were on. Repeatable.")
@click.option("--set", "overrides", multiple=True, metavar="KEY=VALUE",
              help="Override one setting for the replay only, e.g. "
                   "thresholds.truncate_tokens=3000. Repeatable.")
@click.option("--verbose", is_flag=True, help="List the requests that would change.")
def replay(since: str, limit: int, tiers: tuple[str, ...], overrides: tuple[str, ...],
           verbose: bool) -> None:
    """Re-run recorded traffic under a different configuration, and report the difference.

    Nothing is sent anywhere and nothing of yours is written: the replay works from the
    request bodies already on disk, and its ledger and blob store live in a temporary
    directory that is deleted when it finishes. It is the way to find out what a setting
    would do to your own work before committing to it.

    Tier 3 is not replayed. It decides which model answers, and no offline pass can know
    what a different model would have said. Use `tokunseba advise` for that question.
    """
    from . import replay as replay_mod
    from .ui.terminal import k, style

    cfg = config.load()
    if tiers:
        cfg.lossless = "1" in tiers
        cfg.reach_preserving = "2" in tiers
    for item in overrides:
        key, sep, value = item.partition("=")
        if not sep:
            err.print(f"--set wants KEY=VALUE, got: {item}")
            raise SystemExit(1)
        try:
            config.apply_override(cfg, key.strip(), value)
        except (KeyError, ValueError):
            err.print(f"unknown or unusable key: {key.strip()}")
            raise SystemExit(1) from None
    cfg.tier3 = False   # an offline pass cannot know what another model would have replied

    led = _ledger()
    console.print(_banner("replay"))
    rows = led.requests_in_order(_since(since), limit)
    if not rows:
        console.print(f"[dim]No requests recorded in the last {escape(since)}.[/dim]")
        return
    res = replay_mod.run(cfg, rows, config.home() / "bodies")
    if not res.turns:
        console.print("[dim]None of those requests kept a body, so there is nothing to "
                      "replay. Request bodies must be stored (proxy.store_bodies) and are "
                      "pruned on their own schedule (tokunseba retention show).[/dim]")
        return

    tier_line = ("tier " + " and ".join(sorted(tiers))) if tiers else "the current tiers"
    console.print(f"[dim]{res.replayed} requests replayed under {escape(tier_line)}"
                  + (", " + escape(", ".join(overrides)) if overrides else "") + ".[/dim]")
    if res.no_body or res.unreadable:
        console.print(f"[dim]{res.no_body} had no stored body and {res.unreadable} could "
                      f"not be read; both are left out of every figure below.[/dim]")

    t = Table(box=None, header_style="dim", pad_edge=False)
    t.add_column("")
    t.add_column("tokens removed", justify="right")
    t.add_row("as it ran", k(res.was_saved))
    t.add_row("as configured here", k(res.would_save))
    tone = style("good") if res.change > 0 else style("warn") if res.change < 0 else "dim"
    t.add_row("difference", f"[{tone}]{'+' if res.change > 0 else ''}{k(res.change)}[/]")
    console.print(t)

    if res.by_kind:
        b = Table(box=None, header_style="dim", pad_edge=False)
        b.add_column("transform")
        b.add_column("blocks", justify="right")
        for kind, count in res.by_kind.most_common():
            b.add_row(escape(str(kind)), k(count))
        console.print("")
        console.print(b)

    changed = res.changed
    console.print("")
    if not changed:
        console.print("[dim]Not one request would come out different. Whatever you changed "
                      "does not reach this traffic.[/dim]")
        return
    console.print(f"[dim]{len(changed)} of {res.replayed} requests would come out "
                  f"different.[/dim]")
    if not verbose:
        console.print("[dim]Re-run with --verbose to see which, or "
                      "tokunseba explain <request-id> for one of them.[/dim]")
        return
    d = Table(box=None, header_style="dim", pad_edge=False)
    d.add_column("request")
    d.add_column("model", overflow="fold")
    d.add_column("was", justify="right")
    d.add_column("would be", justify="right")
    d.add_column("change", justify="right")
    for turn in res.biggest(20):
        tone = style("good") if turn.change > 0 else style("warn")
        d.add_row(escape(turn.request_id), escape(turn.model or "-"),
                  k(turn.was_saved), k(turn.would_save),
                  f"[{tone}]{'+' if turn.change > 0 else ''}{k(turn.change)}[/]")
    console.print(d)


def _context_of(turn) -> int:
    """Everything one turn made the model read, cache included."""
    return int(turn.input_tokens + turn.cache_read + turn.cache_write)


@main.command()
@click.option("--since", default="30d", show_default=True)
@click.option("--limit", default=100, show_default=True, help="Conversations to judge.")
@click.option("--to", "target", default="claude-sonnet-5", show_default=True,
              help="The smaller model to name as the destination.")
def advise(since: str, limit: int, target: str) -> None:
    """Ask the local judge what your prompts looked like, and what routing them would save.

    This runs offline over conversations that already happened, so it costs nothing, adds no
    latency, and cannot change an answer. It is the honest way to find out whether routing by
    prompt is worth switching on before you switch it on.
    """

    from .advise import EASY_SCORE, collect_turns, judge_turns, movable_share
    from .judge import build_chain
    from .ui.terminal import style

    cfg = config.load()
    led = _ledger()
    console.print(_banner("routing advice"))
    turns = collect_turns(led, config.home() / "bodies", _since(since), limit)
    if not turns:
        console.print("[dim]No conversations recorded yet. Use a tool through the proxy, then "
                      "run this again. Request bodies must be stored (proxy.store_bodies).[/dim]")
        return

    console.print(f"[dim]Judging {len(turns)} conversations with the local model. "
                  f"The first call loads it, which takes a minute.[/dim]")
    adv = judge_turns(turns, build_chain(cfg, led), cfg.judge.gate_threshold)
    if adv.note:
        console.print(f"[{style('warn')}]{escape(adv.note)}[/]")
    if not adv.judged:
        return

    t = Table(title="what the judge saw", title_justify="left", header_style="dim", box=None)
    t.add_column("difficulty", justify="right")
    t.add_column("conf", justify="right")
    t.add_column("domain")
    t.add_column("conf", justify="right")
    t.add_column("context", justify="right")
    t.add_column("opening prompt", overflow="ellipsis", max_width=46)
    for x in adv.turns:
        d = "-" if x.difficulty is None else f"{x.difficulty:.2f}"
        t.add_row(d, f"{x.difficulty_confidence:.2f}", escape(x.domain or "-"),
                  f"{x.domain_confidence:.2f}", _k(_context_of(x)),
                  escape(x.prompt.replace(chr(10), " ")[:46]))
    console.print(t)

    doms = adv.confident_domains
    if doms:
        d = Table(title="domain, where the judge is confident", title_justify="left",
                  header_style="dim", box=None)
        d.add_column("domain")
        d.add_column("conversations", justify="right")
        d.add_column("context", justify="right")
        for name, rows in sorted(doms.items(), key=lambda kv: -len(kv[1])):
            d.add_row(escape(name), str(len(rows)),
                      _k(sum(_context_of(r) for r in rows)))
        console.print(d)
    else:
        console.print("[dim]The judge was not confident about the domain of any conversation.[/dim]")

    easy = adv.easy_turns
    console.print()
    if not easy:
        console.print("[dim]None of these scored easy, so there is nothing obvious to "
                      "route away.[/dim]")
    else:
        share = movable_share(adv.turns, easy)
        console.print(f"[bold]{len(easy)} of {len(adv.turns)} conversations scored "
                      f"easy[/bold] (difficulty at or below {EASY_SCORE})")
        # The share matters more than the count. Ten trivial one-liners are not the same
        # prize as one easy conversation that dragged 200k of context behind it, and a
        # reader who sees only "10 of 11 were easy" will reach the wrong conclusion.
        console.print(f"  context read   {_k(share['context'])} tokens  "
                      f"[dim]{share['context_share'] * 100:.0f}% of the window[/dim]")
        console.print(f"  answers        {_k(share['output'])} tokens  "
                      f"[dim]{share['output_share'] * 100:.0f}% of the window[/dim]")
        console.print(f"  [{style('good')}]all of that could have run on "
                      f"{escape(target)}[/]")

    console.print()
    console.print("[dim]How to read this. Measured on this machine, the local judge names the "
                  "domain well and confidently, but its difficulty confidence stays low even "
                  "when the ranking is right. So domain is a usable routing signal and "
                  "difficulty is only a hint. Treat the number above as an upper bound on what "
                  "automatic routing could save, not a promise.[/dim]")


# --------------------------------------------------------------------------- wrappers
@main.command(context_settings={"ignore_unknown_options": True})
@click.argument("cmd", nargs=-1, type=click.UNPROCESSED, required=True)
def run(cmd: tuple[str, ...]) -> None:
    """Run a shell command and print its output already compressed.

    Use it as: tokunseba run -- pytest -q
    """
    from .hooks.run import run_command
    from .tokens.estimator import Estimator
    from .transform.handles import HandleStore
    cfg = config.load()
    text, code = run_command(list(cmd), cfg, HandleStore(config.home() / "blobs"), Estimator(None))
    click.echo(text)
    raise SystemExit(code)


@main.command()
@click.argument("which", default="claude-code")
def hook(which: str) -> None:
    """Hook entry point. Reads the host tool's JSON event on stdin."""
    from .hooks.claude_code_hook import main as hook_main
    raise SystemExit(hook_main([which]))


@main.command()
def mcp() -> None:
    """Run the MCP server exposing the expand tool, for agents without a shell."""
    from .hooks.mcp_server import main as mcp_main
    raise SystemExit(mcp_main())


# --------------------------------------------------------------------------- config
@main.group("config")
def config_cmd() -> None:
    """Read and write the configuration file."""


@config_cmd.command("show")
@click.option("--path-only", is_flag=True)
def config_show(path_only: bool) -> None:
    """Print the configuration file."""
    p = config.default_path()
    if path_only:
        click.echo(str(p))
        return
    config.save(config.load(), p)
    console.print(f"[dim]{p}[/dim]")
    click.echo(p.read_text())


@config_cmd.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a value, e.g. tokunseba config set tiers.tier3 true"""
    cfg = config.load()
    try:
        _, new = config.apply_override(cfg, key, value)
    except KeyError:
        err.print(f"unknown key: {key}")
        raise SystemExit(1) from None
    config.save(cfg)
    console.print(f"{key} = {new}")


from .commands_apps import register as _register_apps  # noqa: E402
from .commands_judge import register as _register_judge  # noqa: E402
from .commands_retention import register as _register_retention  # noqa: E402
from .commands_models import register as _register_models  # noqa: E402
from .commands_route import register as _register_route  # noqa: E402
from .commands_tier import register as _register_tier  # noqa: E402
from .commands_wrap import register as _register_wrap  # noqa: E402

_register_wrap(main)
_register_apps(main)
_register_judge(main)
_register_retention(main)
_register_models(main)
_register_route(main)
_register_tier(main)


if __name__ == "__main__":
    main()
