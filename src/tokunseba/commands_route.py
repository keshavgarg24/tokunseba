"""The `tokunseba route` command group.

Prompt-driven routing: read the opening prompt, and if it is clearly the kind of turn a
cheaper or local model handles well, send it there. Everything here is off until asked for,
every rule is visible, and `route test` shows exactly what would happen to a given prompt
before anything is switched on.
"""
from __future__ import annotations

import asyncio

import click
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from . import config
from .protocols import translate
from .tier3 import routing

console = Console()
err = Console(stderr=True)

DOMAINS = ["code", "math_or_logic", "writing", "factual_lookup", "data_analysis", "chitchat"]
LEVELS = ["0 trivial", "1 easy", "2 moderate", "3 hard"]


def _chain(cfg):
    from .judge import build_chain
    return build_chain(cfg)


def _judge(cfg, text: str) -> tuple[dict, dict, str]:
    """Signals for one prompt: the gated ones, every confidence, and who answered.

    Mirrors what the proxy does per request, so what this prints is what would happen.
    """
    from .judge import router_questions
    chain = _chain(cfg)
    answers = asyncio.run(chain.ask({"request": text[:1200]}, router_questions()))
    gated, confidences = {}, {}
    for key, a in answers.items():
        confidences[key] = a.confidence
        if a.confidence >= cfg.judge.gate_threshold:
            gated[key] = a.value
    backend = "laya" if cfg.judge.enabled else "rules"
    return gated, confidences, backend


def _fmt_value(key: str, value) -> str:
    if key == "difficulty":
        try:
            return LEVELS[min(int(float(value)), 3)]
        except (TypeError, ValueError):
            return str(value)
    if key in ("needs_tools", "is_sensitive"):
        try:
            return "yes" if float(value) >= 0.5 else "no"
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def rules_table(cfg) -> Table:
    t = Table(header_style="dim", box=None)
    t.add_column("#", style="dim", justify="right")
    t.add_column("when")
    t.add_column("send to")
    for i, rule in enumerate(cfg.tier3_opts.rules, 1):
        when, _, target = routing.describe(rule).partition(" -> ")
        t.add_row(str(i), escape(when), escape(target))
    return t


def register(main: click.Group) -> None:
    @main.group("route", invoke_without_command=True)
    @click.pass_context
    def route(ctx: click.Context) -> None:
        """Route a turn to a different model based on its opening prompt.

        Off by default. Rules only ever fire on the first turn of a conversation, and only
        when the judge is confident enough, so an unsure read changes nothing.
        """
        if ctx.invoked_subcommand is None:
            ctx.invoke(route_status)

    @route.command("status")
    def route_status() -> None:
        """Show whether routing is on, which rules exist, and what judges them."""
        cfg = config.load()
        o = cfg.tier3_opts
        t = Table(header_style="dim", box=None)
        t.add_column("")
        t.add_column("")
        on = cfg.tier3 and bool(o.rules)
        t.add_row("state", "[green]active[/green]" if on
                  else "[yellow]rules exist, tier 3 is off[/yellow]" if o.rules
                  else "[dim]no rules[/dim]")
        t.add_row("judged by", "the local model (laya)" if cfg.judge.enabled
                  else "built-in rules, no model, no download")
        t.add_row("confidence gate", f"{cfg.judge.gate_threshold:g}  "
                                     "[dim]below this a signal is discarded[/dim]")
        t.add_row("applies to", "the first turn of a conversation only")
        t.add_row("effort routing", "on" if o.effort_routing else "off")
        t.add_row("static model map", f"{len(o.model_map)} entries" if o.model_map else "empty")
        console.print(t)
        if o.rules:
            console.print("\n[bold]rules[/bold] [dim]first match wins[/dim]")
            console.print(rules_table(cfg))
        else:
            console.print("\n[dim]No rules yet. Add one, for example:[/dim]")
            console.print("  tokunseba route add --domain chitchat --max-difficulty 1 "
                          "--to ollama --model llama3.1")
        console.print("\n[dim]Try a prompt against these rules without sending anything:"
                      "[/dim]\n  tokunseba route test \"what is a mutex\"")

    @route.command("add")
    @click.option("--domain", type=click.Choice(DOMAINS), default=None,
                  help="Only route turns the judge puts in this domain.")
    @click.option("--max-difficulty", type=click.FloatRange(0, 3), default=None,
                  help="Only route turns at or below this difficulty. 0 trivial, 3 hard.")
    @click.option("--needs-tools/--no-needs-tools", "needs_tools", default=None,
                  help="Only route turns that do, or do not, need files, search or "
                       "private data.")
    @click.option("--to", "upstream", default="",
                  help="Upstream to send to. Omit to keep the upstream and only change "
                       "the model.")
    @click.option("--model", default="", help="Model id to ask for instead.")
    def route_add(domain, max_difficulty, needs_tools, upstream, model) -> None:
        """Add a routing rule. Rules are tried in order and the first match wins."""
        cfg = config.load()
        if domain is None and max_difficulty is None and needs_tools is None:
            err.print("[red]A rule needs at least one condition.[/red] Otherwise it would "
                      "route every first turn.")
            raise SystemExit(2)
        if not upstream and not model:
            err.print("[red]A rule needs somewhere to send the turn:[/red] --to, --model, "
                      "or both.")
            raise SystemExit(2)
        if upstream and upstream not in cfg.upstreams:
            err.print(f"[red]No upstream named {escape(upstream)}.[/red] Configured: "
                      f"{escape(', '.join(cfg.upstreams))}")
            raise SystemExit(2)
        rule: dict = {}
        if domain is not None:
            rule["domain"] = domain
        if max_difficulty is not None:
            rule["max_difficulty"] = float(max_difficulty)
        if needs_tools is not None:
            rule["needs_tools"] = bool(needs_tools)
        if upstream:
            rule["upstream"] = upstream
        if model:
            rule["model"] = model
        cfg.tier3_opts.rules.append(rule)
        config.save(cfg)
        console.print(f"[green]Added rule {len(cfg.tier3_opts.rules)}:[/green] "
                      f"{escape(routing.describe(rule))}")
        if upstream:
            kind = cfg.upstreams[upstream].kind
            arriving = ("anthropic", "openai", "gemini", "ollama")
            translated = [p for p in arriving if p != kind and translate.can(p, kind)]
            blocked = [p for p in arriving if not routing.compatible(p, kind)]
            console.print(f"[dim]This target speaks {escape(kind)}.[/dim]", end=" ")
            if translated:
                console.print(f"[dim]A request arriving as {escape(', '.join(translated))} is "
                              "translated on the way out and its reply translated back.[/dim]",
                              end=" ")
            if blocked:
                console.print(f"[dim]A request arriving as {escape(', '.join(blocked))} is left "
                              "alone, so the rule does not fire for it.[/dim]", end="")
            console.print()
        if not cfg.tier3:
            console.print("\n[yellow]Tier 3 is off, so no rule fires yet.[/yellow] "
                          "Turn it on with: [bold]tokunseba route enable[/bold]")

    @route.command("rm")
    @click.argument("index", type=int)
    def route_rm(index: int) -> None:
        """Remove rule number INDEX, as shown by `tokunseba route`."""
        cfg = config.load()
        rules = cfg.tier3_opts.rules
        if not 1 <= index <= len(rules):
            err.print(f"[red]There is no rule {index}.[/red] "
                      f"{len(rules)} rule(s) configured.")
            raise SystemExit(2)
        gone = rules.pop(index - 1)
        config.save(cfg)
        console.print(f"[green]Removed:[/green] {escape(routing.describe(gone))}")

    @route.command("clear")
    @click.option("-y", "--yes", is_flag=True, help="Do not ask for confirmation.")
    def route_clear(yes: bool) -> None:
        """Remove every routing rule."""
        cfg = config.load()
        n = len(cfg.tier3_opts.rules)
        if not n:
            console.print("[dim]There are no rules.[/dim]")
            return
        if not yes and not click.confirm(f"Remove all {n} rule(s)?", default=False):
            console.print("[dim]Nothing changed.[/dim]")
            return
        cfg.tier3_opts.rules = []
        config.save(cfg)
        console.print(f"[green]Removed {n} rule(s).[/green]")

    @route.command("enable")
    @click.option("-y", "--yes", is_flag=True, help="Do not ask for confirmation.")
    def route_enable(yes: bool) -> None:
        """Let the rules actually change which model answers."""
        cfg = config.load()
        console.print(Panel(
            "Routing is the one thing tokunseba does that can change an answer rather than\n"
            "only its size. A matched rule sends the first turn of a conversation to a\n"
            "different model, which may reply differently from the one you asked for.\n\n"
            "It only ever fires on turn one, only when the judge clears the confidence gate,\n"
            "and never when it would mean translating between two providers' formats.\n"
            "Every routed turn is recorded and shows up in tokunseba report.",
            title="what enabling this changes", title_align="left", border_style="dim"))
        if not cfg.tier3_opts.rules:
            console.print("\n[yellow]There are no rules, so nothing would be routed.[/yellow] "
                          "Add one first with [bold]tokunseba route add[/bold].")
        if not yes and not click.confirm("\nEnable routing?", default=False):
            console.print("[dim]Nothing changed.[/dim]")
            return
        cfg.tier3 = True
        config.save(cfg)
        console.print("[green]Routing is enabled.[/green] Restart the proxy so it picks "
                      "this up: [bold]tokunseba restart[/bold]")

    @route.command("disable")
    def route_disable() -> None:
        """Stop routing. Rules are kept, they simply stop firing."""
        cfg = config.load()
        cfg.tier3 = False
        config.save(cfg)
        console.print("[green]Routing is disabled.[/green] Every request goes to the model "
                      "the client asked for.")
        console.print("Restart the proxy so it picks this up: [bold]tokunseba restart[/bold]")

    @route.command("test")
    @click.argument("prompt", nargs=-1, required=True)
    @click.option("--provider", default="anthropic",
                  type=click.Choice(["anthropic", "openai", "gemini", "ollama"]),
                  help="Pretend the prompt arrived from this kind of client.")
    def route_test(prompt: tuple[str, ...], provider: str) -> None:
        """Judge PROMPT and show where it would go. Sends nothing anywhere."""
        cfg = config.load()
        text = " ".join(prompt)
        gated, confidences, backend = _judge(cfg, text)

        t = Table(header_style="dim", box=None)
        t.add_column("signal")
        t.add_column("answer")
        t.add_column("confidence", justify="right")
        t.add_column("")
        for key in ("domain", "difficulty", "needs_tools", "is_sensitive"):
            if key not in confidences:
                continue
            conf = confidences[key]
            used = key in gated
            t.add_row(key,
                      _fmt_value(key, gated.get(key, "-")) if used else "[dim]discarded[/dim]",
                      f"{conf:.2f}",
                      "[green]above the gate[/green]" if used
                      else f"[dim]below {cfg.judge.gate_threshold:g}[/dim]")
        console.print(Panel(escape(text[:400]), title=f"judged by {backend}",
                            title_align="left", border_style="dim"))
        console.print(t)

        rule = routing.first_match(cfg.tier3_opts.rules, gated)
        if rule is None:
            console.print("\n[bold]No rule matches.[/bold] This turn would go to the model "
                          "the client asked for.")
            return
        target = cfg.upstreams.get(rule.get("upstream") or "")
        if rule.get("upstream") and target is None:
            console.print(f"\n[red]Rule matches but upstream "
                          f"{escape(rule['upstream'])} is not configured.[/red]")
            return
        if target is not None and not routing.compatible(provider, target.kind):
            console.print(f"\n[yellow]Rule matches, but a request arriving as "
                          f"{escape(provider)} cannot be sent to an upstream speaking "
                          f"{escape(target.kind)}:[/yellow] there is no translator for that "
                          "pair, so the turn would be left alone.\n[dim]A rule with --model "
                          "and no --to swaps the model within the same provider, which works "
                          "everywhere.[/dim]")
            return
        where = rule.get("upstream") or "the same upstream"
        what = rule.get("model") or "the same model"
        console.print(f"\n[bold]Matches:[/bold] {escape(routing.describe(rule))}")
        console.print(f"This turn would go to [green]{escape(where)}[/green] asking for "
                      f"[green]{escape(what)}[/green].")
        if target is not None and translate.can(provider, target.kind):
            console.print(f"[dim]It arrives as {escape(provider)}, so the request is "
                          f"translated to {escape(target.kind)} on the way out and the reply "
                          "is translated back. The client sees no difference.[/dim]")
        if not cfg.tier3:
            console.print("[dim]Routing is off, so today it would not. "
                          "Turn it on with: tokunseba route enable[/dim]")
