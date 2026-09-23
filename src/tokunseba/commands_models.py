"""The `tokunseba models` command group.

One question this answers that nothing else did: what can a routing rule actually send a
turn to on this machine. That is the intersection of the upstreams configured here, the
protocols they speak, and whether they answer at all, so all three are shown together.
"""
from __future__ import annotations

import time

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import config
from .config import DEFAULT_UPSTREAMS, Upstream
from .tier3.routing import COMPATIBLE

console = Console()
err = Console(stderr=True)

KINDS = sorted({u.kind for u in DEFAULT_UPSTREAMS.values()})

# A few endpoints people reach for often enough that guessing the protocol for them beats
# making them read the table. Matched on the hostname, never on the name they choose.
KNOWN_HOSTS = {
    "api.deepseek.com": "openai",
    "api.groq.com": "openai",
    "api.mistral.ai": "openai",
    "api.together.xyz": "openai",
    "openrouter.ai": "openai",
    "api.x.ai": "openai",
    "api.anthropic.com": "anthropic",
    "api.openai.com": "openai",
    "generativelanguage.googleapis.com": "gemini",
}

PROBE_TIMEOUT = 2.5


def guess_kind(base_url: str) -> str:
    """The protocol an endpoint most likely speaks, or openai as the common default."""
    from urllib.parse import urlparse
    host = (urlparse(base_url).hostname or "").lower()
    if host in KNOWN_HOSTS:
        return KNOWN_HOSTS[host]
    if host in ("127.0.0.1", "localhost", "::1"):
        return "ollama"
    return "openai"


def reachable(base_url: str) -> tuple[bool, str]:
    """Whether something answers at this address.

    Any HTTP status counts as reachable, 401 included: an authentication error proves the
    endpoint is there, which is the only thing this is asking. No key is ever sent.
    """
    import httpx
    try:
        r = httpx.get(base_url, timeout=PROBE_TIMEOUT, follow_redirects=True)
        return True, f"HTTP {r.status_code}"
    except httpx.TimeoutException:
        return False, f"no answer in {PROBE_TIMEOUT:.0f}s"
    except Exception as exc:  # noqa: BLE001 - the shape of the failure is the useful part
        return False, type(exc).__name__


def _reaches(kind: str) -> str:
    """Which arriving protocols may be rerouted to an upstream speaking `kind`."""
    inbound = sorted(a for a, allowed in COMPATIBLE.items() if kind in allowed)
    return ", ".join(inbound) or "-"


def upstream_table(cfg, checked: dict[str, tuple[bool, str]] | None = None) -> Table:
    t = Table(header_style="dim", box=None)
    t.add_column("name")
    t.add_column("protocol")
    t.add_column("endpoint", overflow="fold")
    t.add_column("reachable from")
    if checked is not None:
        t.add_column("answering")
    for name, up in sorted(cfg.upstreams.items()):
        row = [escape(name), escape(up.kind), f"[dim]{escape(up.base_url)}[/dim]",
               f"[dim]{escape(_reaches(up.kind))}[/dim]"]
        if checked is not None:
            ok, detail = checked.get(name, (False, "-"))
            row.append(f"[green]yes[/green] [dim]{escape(detail)}[/dim]" if ok
                       else f"[yellow]no[/yellow] [dim]{escape(detail)}[/dim]")
        t.add_row(*row)
    return t


def seen_table(rows: list[dict]) -> Table:
    from .ui.terminal import k, when
    if not rows:
        return Table.grid()
    t = Table(header_style="dim", box=None)
    t.add_column("model", overflow="fold")
    t.add_column("through")
    t.add_column("requests", justify="right")
    t.add_column("input tokens", justify="right")
    t.add_column("last used")
    for r in rows:
        t.add_row(escape(str(r["model"])), f"[dim]{escape(str(r['provider']))}[/dim]",
                  k(r["requests"]), k(r["input_tokens"]),
                  f"[dim]{when(r['last_seen'])}[/dim]")
    return t


def register(main: click.Group) -> None:
    @main.group("models", invoke_without_command=True)
    @click.pass_context
    def models(ctx: click.Context) -> None:
        """List the model endpoints tokunseba can reach, and what you actually used."""
        if ctx.invoked_subcommand is None:
            ctx.invoke(models_list)

    @models.command("list")
    @click.option("--check", is_flag=True,
                  help="Also ask each endpoint whether it answers. Sends no key and no prompt.")
    @click.option("--since", default="7d", show_default=True,
                  help="How far back to look for models you actually used.")
    def models_list(check: bool, since: str) -> None:
        """Show every configured upstream and every model seen going through them."""
        from .cli import _ledger, _since
        cfg = config.load()
        checked = None
        if check:
            console.print("[dim]probing endpoints...[/dim]")
            checked = {name: reachable(up.base_url) for name, up in cfg.upstreams.items()}
        console.print(upstream_table(cfg, checked))
        rows = _ledger().models_seen(_since(since))
        if rows:
            console.print(f"\n[dim]models you used in the last {escape(since)}[/dim]")
            console.print(seen_table(rows))
        else:
            console.print(f"\n[dim]No requests recorded in the last {escape(since)}. "
                          "Start the proxy with: tokunseba init[/dim]")
        console.print("\n[dim]\"reachable from\" is which client protocol may be rerouted "
                      "here. tokunseba rewrites the request body, it does not translate "
                      "between provider formats, so a rule that would need translation is "
                      "refused rather than attempted.[/dim]")
        console.print("[dim]Add an endpoint: tokunseba models add NAME URL"
                      "   Send work to it: tokunseba route add --to NAME --model MODEL[/dim]")

    @models.command("add")
    @click.argument("name")
    @click.argument("base_url")
    @click.option("--kind", type=click.Choice(KINDS), default=None,
                  help="Which protocol it speaks. Guessed from the URL when omitted.")
    @click.option("--check/--no-check", default=True, show_default=True,
                  help="Probe the endpoint before saving it.")
    def models_add(name: str, base_url: str, kind: str | None, check: bool) -> None:
        """Add a model endpoint, such as a DeepSeek key or a second ollama host.

        Only the address is stored. Keys stay wherever your client already keeps them and
        are forwarded from the request, so nothing secret is written to disk here.
        """
        cfg = config.load()
        if not base_url.startswith(("http://", "https://")):
            base_url = "https://" + base_url
        base_url = base_url.rstrip("/")
        guessed = kind or guess_kind(base_url)
        if check:
            ok, detail = reachable(base_url)
            if not ok:
                err.print(f"[yellow]Nothing answered at {escape(base_url)}[/yellow] "
                          f"({escape(detail)}).")
                err.print("[dim]Saving it anyway is fine if it is not running yet; "
                          "re-run with --no-check.[/dim]")
                raise SystemExit(2)
            console.print(f"[green]{escape(base_url)} answered[/green] [dim]{escape(detail)}[/dim]")
        existed = name in cfg.upstreams
        cfg.upstreams[name] = Upstream(base_url=base_url, kind=guessed)
        config.save(cfg)
        console.print(f"[green]{'Updated' if existed else 'Added'} {escape(name)}[/green] "
                      f"[dim]{escape(guessed)} at {escape(base_url)}[/dim]")
        if kind is None:
            console.print("[dim]Protocol guessed from the URL. Override with "
                          "--kind if that is wrong.[/dim]")
        console.print(f"[dim]Point a client at it: {escape(cfg.base(name))}[/dim]")
        console.print("Restart the proxy so it picks this up: [bold]tokunseba restart[/bold]")

    @models.command("rm")
    @click.argument("name")
    def models_rm(name: str) -> None:
        """Remove a model endpoint."""
        cfg = config.load()
        if name not in cfg.upstreams:
            err.print(f"No upstream named {escape(name)}. See: tokunseba models")
            raise SystemExit(2)
        using = [routing_rule for routing_rule in cfg.tier3_opts.rules
                 if routing_rule.get("upstream") == name]
        cfg.upstreams.pop(name)
        config.save(cfg)
        console.print(f"[green]Removed {escape(name)}.[/green]")
        if using:
            console.print(f"[yellow]{len(using)} routing rule"
                          f"{'s' if len(using) != 1 else ''} still point"
                          f"{'' if len(using) != 1 else 's'} at it and will be refused "
                          "until you fix them: tokunseba route[/yellow]")
        if name in DEFAULT_UPSTREAMS:
            console.print("[dim]This was one of the built-in endpoints. It comes back "
                          "the next time defaults are written; remove the line from "
                          "the config file to keep it gone.[/dim]")

    @models.command("check")
    def models_check() -> None:
        """Ask every configured endpoint whether it answers. No key, no prompt, no cost."""
        cfg = config.load()
        t0 = time.time()
        checked = {name: reachable(up.base_url) for name, up in cfg.upstreams.items()}
        console.print(upstream_table(cfg, checked))
        up = sum(1 for ok, _ in checked.values() if ok)
        console.print(f"\n[dim]{up} of {len(checked)} answered in "
                      f"{time.time() - t0:.1f}s. A 401 counts as answering: it proves the "
                      "endpoint is there, and tokunseba sent no key to find out.[/dim]")
