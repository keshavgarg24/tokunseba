"""tokunseba command line."""
from __future__ import annotations

import json
import sys
import time

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import __version__, config
from .ledger import Ledger

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
    """Cut token usage for every AI coding tool on this machine, without changing results."""


# --------------------------------------------------------------------------- setup
@main.command()
@click.option("--no-service", is_flag=True, help="Do not install the background service.")
@click.option("--no-hooks", is_flag=True, help="Do not register Claude Code hooks.")
@click.option("--with-mcp", is_flag=True,
              help="Register the MCP expand tool. Only needed for agents with no shell; "
                   "it costs one background process per session.")
def init(no_service: bool, no_hooks: bool, with_mcp: bool) -> None:
    """Point every supported tool at the proxy and start it in the background."""
    from . import service
    from .detect import registry
    cfg = config.load()
    config.save(cfg)

    console.print("[bold]Configuring tools[/bold]")
    for line in registry.apply_all(cfg, hooks=not no_hooks, mcp=with_mcp):
        console.print(f"  {escape(str(line))}")

    if not no_service:
        path, state = service.install()
        console.print(f"[bold]Service[/bold]\n  {path} ({state})")

    _print_tools(registry.detect_all())
    console.print("\nOpen a new shell so the environment block takes effect, then run: "
                  "[bold]tokunseba doctor[/bold]")


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
    if warm_judge:
        for b in app.state.proxy.judge.backends:
            if getattr(b, "name", "") == "laya" and b.available():
                console.print("Loading the local judge model, first run downloads it...")
                try:
                    b.load()
                    console.print("[green]judge ready[/green]")
                except Exception as exc:  # noqa: BLE001
                    err.print(f"[yellow]judge unavailable: {exc}[/yellow]")
    console.print(f"tokunseba listening on [bold]http://127.0.0.1:{cfg.port}[/bold]")
    uvicorn.run(app, host="127.0.0.1", port=cfg.port, log_level="warning")


@main.command()
def stop() -> None:
    """Stop the background proxy."""
    from . import service
    console.print(service.stop())


@main.command()
def status() -> None:
    """Show whether the proxy is running and what it saved today."""
    from .service import running
    cfg = config.load()
    up = running(cfg.port)
    console.print(_banner("status"))
    console.print(f"proxy: {'[green]running[/green]' if up else '[red]not running[/red]'} "
                  f"on 127.0.0.1:{cfg.port}")
    s = _ledger().stats(time.time() - 86400)
    console.print(f"today: {s['requests']} requests, {_k(s['tokens_saved'])} tokens saved, "
                  f"${s['usd_saved']:.2f} saved, ${s['usd_spent']:.2f} spent, "
                  f"cache hit {s['cache_hit_rate'] * 100:.0f}%")


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


# --------------------------------------------------------------------------- reporting
@main.command()
@click.option("--since", default="7d", help="e.g. 24h, 7d, 30d")
@click.option("--project", default=None, help="Filter to one project directory.")
@click.option("--ab", is_flag=True, help="Compare the tier 3 control and treatment arms.")
@click.option("--json", "as_json", is_flag=True)
def stats(since: str, project: str | None, ab: bool, as_json: bool) -> None:
    """Show what tokunseba saved."""
    led = _ledger()
    s = led.stats(_since(since), project)
    if as_json:
        console.print_json(json.dumps(s))
        return
    console.print(_banner(f"stats · last {since}"))
    head = Table(header_style="dim", box=None)
    head.add_column("metric")
    head.add_column("value", justify="right")
    head.add_row("requests", str(s["requests"]))
    head.add_row("input tokens", _k(s["input_tokens"]))
    head.add_row("output tokens", _k(s["output_tokens"]))
    head.add_row("tokens saved", f"{_k(s['tokens_saved'])}  ({s['pct_saved'] * 100:.0f}% of tool output)")
    head.add_row("cache hit rate", f"{s['cache_hit_rate'] * 100:.0f}%")
    head.add_row("spent", f"${s['usd_spent']:.2f}")
    head.add_row("saved", f"[green]${s['usd_saved']:.2f}[/green]")
    console.print(head)

    if s["by_tool"]:
        t = Table(title="by tool", title_justify="left", header_style="dim", box=None)
        t.add_column("tool")
        t.add_column("requests", justify="right")
        t.add_column("saved", justify="right")
        t.add_column("spent", justify="right")
        for r in s["by_tool"]:
            t.add_row(escape(r["tool"]), str(r["requests"]), _k(r["tokens_saved"]),
                      f"${r['usd']:.2f}")
        console.print(t)

    if s["events"]:
        e = Table(title="signals", title_justify="left", header_style="dim", box=None)
        e.add_column("signal")
        e.add_column("count", justify="right")
        for kind, count in s["events"].items():
            e.add_row(escape(kind), str(count))
        console.print(e)

    if ab:
        arms = led.stats_ab(_since(since))
        if not arms:
            console.print("[dim]No A/B data. Tier 3 is off, so every session is a control.[/dim]")
        else:
            a = Table(title="tier 3 arms", title_justify="left", header_style="dim", box=None)
            a.add_column("arm")
            for col in ("sessions", "requests/session", "input/session", "output/session", "$/session"):
                a.add_column(col, justify="right")
            for name, v in arms.items():
                a.add_row(name, str(v["sessions"]), str(v["requests_per_session"]),
                          _k(int(v["input_tokens_per_session"])), _k(int(v["output_tokens_per_session"])),
                          f"${v['usd_per_session']:.4f}")
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
@click.option("--days", default=30, show_default=True)
def prune(days: int) -> None:
    """Delete stored request bodies, blobs and ledger rows older than N days."""
    led = _ledger()
    rows = led.prune(days)
    from .transform.handles import HandleStore
    blobs = HandleStore(config.home() / "blobs").prune(led.live_handles())
    cutoff = time.time() - days * 86400
    bodies = 0
    bdir = config.home() / "bodies"
    if bdir.exists():
        for f in bdir.iterdir():
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
                bodies += 1
    console.print(f"removed {rows} request rows, {blobs} blobs, {bodies} stored bodies")


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
    return Group(
        _banner(f"last {since}"),
        live,
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
    from .ui.terminal import check_table, k, pct, style
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
        t = Table(title="transforms by kind", title_justify="left",
                  header_style="dim", box=None)
        t.add_column("kind", overflow="fold")
        t.add_column("count", justify="right")
        t.add_column("before", justify="right")
        t.add_column("after", justify="right")
        t.add_column("saved", justify="right")
        for r in summary:
            t.add_row(escape(str(r["kind"])), str(r["count"]), _k(r["tokens_before"]),
                      _k(r["tokens_after"]), _k(r["saved"]))
        console.print(t)

    failed = [name for name, ok, _d, essential in checks if essential and not ok]
    advisory = [name for name, ok, _d, essential in checks if not essential and not ok]
    if failed:
        console.print(f"\n[{style('bad')}]not verified[/] — failed: "
                      + escape("; ".join(failed)))
        raise SystemExit(1)
    note = ""
    if advisory:
        note = " [dim](" + escape("; ".join(advisory)) + ")[/dim]"
    console.print(f"\n[{style('good')}]verified[/] — {k(saved)} tokens saved in the last 24h"
                  f" across {applied} transforms.{note}")


# --------------------------------------------------------------------------- top
@main.command()
@click.option("--since", default="7d", help="e.g. 24h, 7d, 30d")
@click.option("--limit", default=15, show_default=True, help="Rows per table.")
def top(since: str, limit: int) -> None:
    """Show where the tokens went: the biggest savings, and what could not be helped."""
    from .ui.terminal import passthrough_table, style, transform_table
    led = _ledger()
    ts = _since(since)
    wins = led.top_transforms(ts, limit)
    misses = led.biggest_passthroughs(ts, limit)
    console.print(_banner(f"top · last {since}"))
    console.print(f"\n[{style('dim')}]biggest savings[/]")
    console.print(transform_table(wins))
    console.print(f"\n[{style('dim')}]biggest untouched blocks — "
                  "what tokunseba could not help with[/]")
    console.print(passthrough_table(misses))
    if wins:
        console.print(f"\n[dim]See one request in full with: "
                      f"tokunseba explain {escape(str(wins[0]['request_id']))}[/dim]")


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
    parts = [f"tokunseba · saved {_k(s['tokens_saved'])} tok ({s['pct_saved'] * 100:.0f}%)",
             f"cache {s['cache_hit_rate'] * 100:.0f}%",
             f"${s['usd_spent']:.2f} today"]
    if cfg.budget.daily_usd > 0:
        used = s["usd_spent"] / cfg.budget.daily_usd * 100
        parts.append(f"budget {used:.0f}%")
    drift = s["events"].get("cache_drift", 0)
    if drift:
        parts.append(f"drift {drift}")
    click.echo(" · ".join(parts))


@main.command()
@click.option("--since", default="30d", show_default=True)
@click.option("--limit", default=100, show_default=True, help="Conversations to judge.")
@click.option("--to", "target", default="claude-sonnet-5", show_default=True,
              help="The cheaper model to price against.")
def advise(since: str, limit: int, target: str) -> None:
    """Ask the local judge what your prompts looked like, and what routing them would save.

    This runs offline over conversations that already happened, so it costs nothing, adds no
    latency, and cannot change an answer. It is the honest way to find out whether routing by
    prompt is worth switching on before you switch it on.
    """

    from .advise import EASY_SCORE, collect_turns, counterfactual_cost, judge_turns
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
    t.add_column("spent", justify="right")
    t.add_column("opening prompt", overflow="ellipsis", max_width=46)
    for x in adv.turns:
        d = "-" if x.difficulty is None else f"{x.difficulty:.2f}"
        t.add_row(d, f"{x.difficulty_confidence:.2f}", escape(x.domain or "-"),
                  f"{x.domain_confidence:.2f}", f"${x.cost_usd:.3f}",
                  escape(x.prompt.replace(chr(10), " ")[:46]))
    console.print(t)

    doms = adv.confident_domains
    if doms:
        d = Table(title="domain, where the judge is confident", title_justify="left",
                  header_style="dim", box=None)
        d.add_column("domain")
        d.add_column("conversations", justify="right")
        d.add_column("spent", justify="right")
        for name, rows in sorted(doms.items(), key=lambda kv: -len(kv[1])):
            d.add_row(escape(name), str(len(rows)), f"${sum(r.cost_usd for r in rows):.3f}")
        console.print(d)
    else:
        console.print("[dim]The judge was not confident about the domain of any conversation.[/dim]")

    easy = adv.easy_turns
    console.print()
    if not easy:
        console.print("[dim]None of these scored easy, so there is nothing obvious to "
                      "route away.[/dim]")
    else:
        spent = sum(x.cost_usd for x in easy)
        alt = counterfactual_cost(easy, target, cfg.pricing_overrides)
        console.print(f"[bold]{len(easy)} of {len(adv.turns)} conversations scored "
                      f"easy[/bold] (difficulty at or below {EASY_SCORE})")
        console.print(f"  they cost      ${spent:.3f}")
        if alt is None:
            console.print(f"  [dim]no price known for {escape(target)}[/dim]")
        else:
            console.print(f"  on {escape(target)}   ${alt:.3f}")
            console.print(f"  [{style('good')}]difference    ${spent - alt:.3f}[/]")

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


SECTION_ALIASES = {"tier3": "tier3_opts", "thresholds": "thresholds", "judge": "judge",
                   "budget": "budget", "failover": "failover"}


@config_cmd.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a value, e.g. tokunseba config set tiers.tier3 true"""
    cfg = config.load()
    section, _, name = key.partition(".")
    if name and section in SECTION_ALIASES:
        target, attr = getattr(cfg, SECTION_ALIASES[section]), name
    elif name and section in ("proxy", "tiers"):
        target, attr = cfg, name
    else:
        target, attr = cfg, section
    if not hasattr(target, attr):
        err.print(f"unknown key: {key}")
        raise SystemExit(1)
    current = getattr(target, attr)
    if isinstance(current, bool):
        new = value.strip().lower() in ("1", "true", "yes", "on")
    elif isinstance(current, int):
        new = int(value)
    elif isinstance(current, float):
        new = float(value)
    elif isinstance(current, list):
        new = [v.strip() for v in value.split(",") if v.strip()]
    else:
        new = value
    setattr(target, attr, new)
    config.save(cfg)
    console.print(f"{key} = {new}")


if __name__ == "__main__":
    main()
