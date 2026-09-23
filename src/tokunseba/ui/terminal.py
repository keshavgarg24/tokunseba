"""Terminal rendering for the dashboard.

Pure functions: they take dicts that somebody else already fetched and return rich
renderables. No I/O, no ledger, no network, so every one of them is unit testable.
"""
from __future__ import annotations

import time

from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

BLOCKS = "▁▂▃▄▅▆▇█"
BAR = "█"

# Styles. brand.py owns the real palette; these are the fallbacks so this module keeps
# working on its own.
FALLBACK_COLORS = {"accent": "cyan", "dim": "dim", "good": "green",
                   "warn": "yellow", "bad": "red"}

# The canonical explanation of every signal. There is no web page; the terminal is the only
# place these are described, so a test asserts every emitted signal appears here.
EVENT_HELP: dict[str, str] = {
    "cache_drift": "a cached prefix changed, so the next request paid full price",
    "cache_miss_unexplained": "a cached request read nothing back",
    "cache_injected": "tokunseba added cache breakpoints a client had omitted",
    "secret_detected": "a credential was seen in an outbound request",
    "injection_suspected": "a tool result looked like it was addressing the assistant",
    "ref_dangling": "a stored reference lost its target and the full text was sent",
    "context_overflow_risk": "a local model was close to silently truncating the prompt",
    "ttl_advice": "this session is slow-paced enough to benefit from the 1 hour cache",
    "route_signal": "domain and difficulty read from the opening prompt",
    "injection_corroborated": "the local judge was asked whether it agreed with a regex hit",
    "secret_redacted": "a credential was replaced before the request left this machine",
    "record_error": "a response was delivered but its usage could not be recorded",
    "budget_exceeded": "today's spend passed the configured daily budget",
    "judge_error": "the local judge failed or timed out; the conservative path was taken",
    "effort_set": "an easy turn was sent at low effort",
    "model_routed": "an easy first turn was sent to a cheaper model",
    "local_routed": "an easy first turn was sent to a local model",
    "rule_routed": "a first turn matched a routing rule and went to the model it named",
    "route_refused": "a routing rule matched but its target could not be used, so the "
                     "turn was left alone",
    "failover_used": "the upstream failed and the same model was retried elsewhere",
    "passthrough_after_error": "a bug in tokunseba was hit, so the request was forwarded "
                               "exactly as the tool sent it",
    "upstream_error": "the upstream could not be reached and the request returned 502",
    "pruned": "history past the retention window was deleted from this machine",
}

EVENT_TONE: dict[str, str] = {
    "cache_drift": "bad", "cache_miss_unexplained": "bad", "secret_detected": "warn",
    "injection_suspected": "warn", "budget_exceeded": "warn", "ref_dangling": "warn",
    "upstream_error": "bad", "judge_error": "warn", "context_overflow_risk": "warn",
    "cache_injected": "good", "failover_used": "warn", "ttl_advice": "warn",
    "effort_set": "good", "model_routed": "good", "local_routed": "good",
    "rule_routed": "good", "route_refused": "warn",
    "route_signal": "", "injection_corroborated": "warn", "secret_redacted": "good",
    "record_error": "bad", "passthrough_after_error": "bad", "pruned": "good",
}


def style(name: str) -> str:
    """Resolve a semantic style name against the brand palette, with a safe fallback."""
    try:
        from ..brand import COLORS
    except ImportError:
        return FALLBACK_COLORS.get(name, name)
    value = COLORS.get(name) if isinstance(COLORS, dict) else None
    return value or FALLBACK_COLORS.get(name, name)


def tone_style(kind: str) -> str:
    tone = EVENT_TONE.get(kind, "")
    return style(tone) if tone else style("accent")


# --------------------------------------------------------------------------- formatting
def k(v) -> str:
    """Compact token count, matching the CLI elsewhere."""
    v = int(v or 0)
    if v >= 1_000_000:
        return f"{v / 1e6:.1f}M"
    if v >= 1000:
        return f"{v / 1e3:.1f}k"
    return str(v)


def usd(v) -> str:
    """Currency, only ever reached behind an explicit --money flag."""
    return f"${float(v or 0):.2f}"


def bar(value, maximum, width: int = 20) -> str:
    """A proportional block bar. Never wider than `width`, never negative, never a crash."""
    width = max(0, int(width))
    value = max(0.0, float(value or 0))
    maximum = float(maximum or 0)
    if width == 0 or maximum <= 0 or value <= 0:
        return ""
    return BAR * max(1, min(width, round(value / maximum * width)))


def _block_line(values, width: int) -> str:
    """Bucket `values` into exactly `width` unicode blocks, scaled to the peak."""
    values = [max(0, int(v or 0)) for v in values]
    width = max(1, int(width))
    n = len(values)
    if n == 0:
        return BLOCKS[0] * width
    buckets: list[int] = []
    for i in range(width):
        lo = i * n // width
        hi = max(lo + 1, (i + 1) * n // width)
        chunk = values[lo:hi] or [values[min(lo, n - 1)]]
        buckets.append(max(chunk))
    top = max(buckets)
    if top <= 0:  # all-zero data must never divide by zero
        return BLOCKS[0] * width
    return "".join(BLOCKS[0] if v <= 0 else BLOCKS[max(1, round(v / top * (len(BLOCKS) - 1)))]
                   for v in buckets)


def pct(v) -> str:
    return f"{float(v or 0) * 100:.0f}%"


def when(ts) -> str:
    try:
        return time.strftime("%b %d %H:%M", time.localtime(float(ts or 0)))
    except (ValueError, OSError):
        return "-"


def short_project(path: str) -> str:
    """The last two segments, which is all that ever tells projects apart."""
    parts = [p for p in str(path or "").split("/") if p]
    return "/".join(parts[-2:]) if parts else "-"


def _empty_table(message: str) -> Table:
    t = Table(box=None, show_header=False, pad_edge=False)
    t.add_column(" ")
    t.add_row(f"[{style('dim')}]{escape(message)}[/]")
    return t


# --------------------------------------------------------------------------- renderables
def stat_tiles(stats: dict, money: bool = False, per_row: int = 3) -> Table:
    """The numbers that answer 'is this worth it' on any billing plan.

    Money is deliberately absent unless `money` is passed: per-token prices are wrong for
    anyone on a subscription, while tokens, ratios and cache behaviour are true for everyone.
    Tiles wrap onto further rows so the block stays narrow enough for a 100 column report.
    """
    s = stats or {}
    accent, dim, good, warn = style("accent"), style("dim"), style("good"), style("warn")
    tiles = [
        ("tokens saved", k(s.get("tokens_saved")), f"{pct(s.get('pct_saved'))} of tool output", good),
        ("context sent", k(s.get("input_tokens")),
         f"{k(s.get('requests'))} requests / {len(s.get('by_tool') or [])} tools", accent),
        ("cache efficiency", pct(s.get("cache_hit_rate")),
         f"{k(s.get('cache_read'))} read from cache", accent),
        ("fresh tokens", k(s.get("fresh_tokens")), "not served from cache", warn),
        ("avg context", k(round(float(s.get("avg_context") or 0))), "per request", accent),
        ("largest request", k(s.get("max_request_tokens")), "biggest single call", accent),
    ]
    if money:
        tiles += [("money saved", usd(s.get("usd_saved")), "versus no tokunseba", good),
                  ("spent", usd(s.get("usd_spent")), "pay-per-token only", accent)]
    per_row = max(1, int(per_row))
    t = Table(box=None, show_header=False, pad_edge=False, padding=(0, 3, 0, 0))
    for _ in range(min(per_row, len(tiles))):
        t.add_column(no_wrap=True)
    cells = [f"[{dim}]{label}[/]\n[bold {colour}]{value}[/]\n[{dim}]{sub}[/]"
             for label, value, sub, colour in tiles]
    for i in range(0, len(cells), per_row):
        chunk = cells[i:i + per_row]
        if i:
            t.add_row(*[""] * len(t.columns))
        t.add_row(*(chunk + [""] * (len(t.columns) - len(chunk))))
    return t


def sparkline(daily: list[dict], width: int = 48, key: str = "tokens_saved") -> str:
    """Tokens saved per bucket as unicode blocks, always exactly `width` characters."""
    rows = list(daily or [])
    width = max(1, int(width))
    if not rows:
        return f"[{style('dim')}]no data yet[/]"
    return _block_line([r.get(key) for r in rows], width)


def by_tool_table(rows: list[dict]) -> Table:
    """Which tool the savings actually came from."""
    rows = list(rows or [])
    if not rows:
        return _empty_table("nothing recorded yet")
    t = Table(box=None, header_style=style("dim"), pad_edge=False)
    t.add_column("tool", overflow="fold")
    t.add_column("requests", justify="right")
    t.add_column("tokens saved", justify="right")
    t.add_column("", no_wrap=True)
    top = max([int(r.get("tokens_saved") or 0) for r in rows] + [1])
    for r in rows:
        saved = int(r.get("tokens_saved") or 0)
        t.add_row(escape(str(r.get("tool") or "-")),
                  k(r.get("requests")),
                  k(saved),
                  f"[{style('accent')}]{bar(saved, top, 20)}[/]")
    return t


def signal_table(events: dict[str, int]) -> Table:
    """Every signal with the plain-English meaning, so nothing is unexplained noise."""
    items = sorted((events or {}).items(), key=lambda kv: kv[1], reverse=True)
    if not items:
        return _empty_table("no signals yet")
    t = Table(box=None, header_style=style("dim"), pad_edge=False)
    t.add_column("signal", overflow="fold")
    t.add_column("count", justify="right")
    t.add_column("what it means", overflow="fold")
    for kind, count in items:
        t.add_row(f"[{tone_style(kind)}]{escape(str(kind))}[/]",
                  k(count),
                  f"[{style('dim')}]{escape(EVENT_HELP.get(kind, 'no explanation recorded'))}[/]")
    return t


def sessions_table(rows: list[dict]) -> Table:
    """Recent sessions, most recent first."""
    rows = list(rows or [])
    if not rows:
        return _empty_table("no sessions yet")
    t = Table(box=None, header_style=style("dim"), pad_edge=False)
    t.add_column("when", no_wrap=True)
    t.add_column("tool", overflow="fold")
    t.add_column("project", overflow="fold")
    t.add_column("model", overflow="fold")
    t.add_column("reqs", justify="right")
    t.add_column("saved", justify="right")
    for r in rows:
        t.add_row(f"[{style('dim')}]{when(r.get('last_seen'))}[/]",
                  escape(str(r.get("tool") or "-")),
                  escape(short_project(r.get("project") or "")),
                  f"[{style('dim')}]{escape(str(r.get('model') or '-'))}[/]",
                  k(r.get("requests")),
                  k(r.get("tokens_saved")))
    return t


def transform_table(rows: list[dict]) -> Table:
    """Top transforms: what was rewritten and what it bought."""
    rows = list(rows or [])
    if not rows:
        return _empty_table("no transforms recorded yet")
    t = Table(box=None, header_style=style("dim"), pad_edge=False)
    t.add_column("kind", overflow="fold")
    t.add_column("saved", justify="right")
    t.add_column("before", justify="right")
    t.add_column("after", justify="right")
    t.add_column("handle", overflow="fold")
    for r in rows:
        handle = str(r.get("handle") or "")
        t.add_row(escape(str(r.get("kind") or "-")),
                  f"[{style('good')}]{k(r.get('saved'))}[/]",
                  k(r.get("orig_tokens")),
                  k(r.get("new_tokens")),
                  f"[{style('dim')}]{escape(handle) if handle else '-'}[/]")
    return t


def passthrough_table(rows: list[dict]) -> Table:
    """The honest view: blocks tokunseba looked at and could not shrink."""
    rows = list(rows or [])
    if not rows:
        return _empty_table("nothing was passed through untouched")
    import datetime
    t = Table(box=None, header_style=style("dim"), pad_edge=False)
    t.add_column("tokens", justify="right")
    t.add_column("first seen")
    t.add_column("content", overflow="fold")
    for r in rows:
        ts = r.get("created")
        when = (datetime.datetime.fromtimestamp(ts).strftime("%b %d %H:%M")
                if isinstance(ts, (int, float)) and ts else "-")
        t.add_row(f"[{style('warn')}]{k(r.get('orig_tokens'))}[/]",
                  f"[{style('dim')}]{when}[/]",
                  f"[{style('dim')}]{escape(str(r.get('orig_sha') or '-'))[:16]}[/]")
    return t


def histogram(rows: list[dict], width: int = 40) -> Table:
    """Tool-result blocks by size bucket: where the compressible mass actually is.

    Each bar is split: the part that was compressed, then the part forwarded untouched.
    A fat 8k+ bar that is mostly untouched is the single most actionable thing here.
    """
    rows = list(rows or [])
    if not rows:
        return _empty_table("no tool results recorded yet")
    good, warn, dim, accent = style("good"), style("warn"), style("dim"), style("accent")
    top = max([int(r.get("tokens") or 0) for r in rows] + [1])
    t = Table(box=None, header_style=dim, pad_edge=False)
    t.add_column("size", no_wrap=True)
    t.add_column("blocks", justify="right")
    t.add_column("tokens", justify="right")
    t.add_column("", no_wrap=True)
    t.add_column("compressed", justify="right")
    for r in rows:
        compressed = max(0, int(r.get("compressed_tokens") or 0))
        total = max(0, int(r.get("tokens") or 0))
        drawn = len(bar(total, top, width))
        filled = min(drawn, round(compressed / total * drawn)) if total > 0 else 0
        t.add_row(escape(str(r.get("bucket") or "-")),
                  k(r.get("count")),
                  k(total),
                  f"[{good}]{BAR * filled}[/][{warn}]{BAR * (drawn - filled)}[/]",
                  f"[{accent}]{pct(compressed / total if total else 0)}[/]")
    t.add_row("", "", "",
              f"[{good}]{BAR}[/][{dim}] compressed  [/][{warn}]{BAR}[/][{dim}] "
              f"passed through[/]", "")
    return t


def mix_table(counts: dict, heading: str, order: list[str] | None = None,
              width: int = 24) -> Table:
    """What the opening prompts of this window looked like, as a share of the whole.

    `order` fixes the row order where the categories have a natural one, as difficulty
    does; without it the biggest share leads. "unsure" is always last and always shown,
    because a large unsure share is the honest reason a routing rule is not firing.
    """
    counts = {str(kk): int(vv or 0) for kk, vv in (counts or {}).items() if int(vv or 0) > 0}
    if not counts:
        return _empty_table("no prompts judged yet")
    dim, accent = style("dim"), style("accent")
    if order:
        keys = [kk for kk in order if kk in counts]
        keys += sorted((kk for kk in counts if kk not in order),
                       key=lambda kk: -counts[kk])
    else:
        keys = sorted(counts, key=lambda kk: (kk == "unsure", -counts[kk]))
    total = sum(counts.values()) or 1
    top = max(counts.values())
    t = Table(box=None, header_style=dim, pad_edge=False)
    t.add_column(heading, overflow="fold")
    t.add_column("turns", justify="right")
    t.add_column("", no_wrap=True)
    t.add_column("share", justify="right")
    for name in keys:
        n = counts[name]
        colour = dim if name == "unsure" else accent
        t.add_row(f"[{colour}]{escape(name)}[/]", k(n),
                  f"[{colour}]{bar(n, top, width)}[/]",
                  f"[{dim}]{pct(n / total)}[/]")
    return t


def context_curve(rows: list[dict], width: int = 56) -> str:
    """How the context grew across one session's turns, as a unicode block line."""
    rows = list(rows or [])
    if not rows:
        return f"[{style('dim')}]no session data yet[/]"
    return _block_line([r.get("context_tokens") for r in rows], width)


def model_table(rows: list[dict]) -> Table:
    """Per model: context read, how much came from cache, how much was never sent."""
    rows = list(rows or [])
    if not rows:
        return _empty_table("no models recorded yet")
    dim = style("dim")
    t = Table(box=None, header_style=dim, pad_edge=False)
    t.add_column("model", overflow="fold")
    t.add_column("requests", justify="right")
    t.add_column("context", justify="right")
    t.add_column("from cache", justify="right")
    t.add_column("fresh", justify="right")
    t.add_column("saved", justify="right")
    t.add_column("", no_wrap=True)
    top = max([int(r.get("input_tokens") or 0) for r in rows] + [1])
    for r in rows:
        context = int(r.get("input_tokens") or 0)
        cached = int(r.get("cache_read") or 0)
        t.add_row(escape(str(r.get("model") or "-")),
                  k(r.get("requests")),
                  k(context),
                  f"{k(cached)} [{dim}]{pct(cached / context if context else 0)}[/]",
                  f"[{style('warn')}]{k(r.get('fresh_tokens'))}[/]",
                  f"[{style('good')}]{k(r.get('tokens_saved'))}[/]",
                  f"[{style('accent')}]{bar(context, top, 16)}[/]")
    return t


def transform_kind_table(rows: list[dict]) -> Table:
    """What was rewritten, grouped by the kind of rewrite."""
    rows = list(rows or [])
    if not rows:
        return _empty_table("nothing has been rewritten yet")
    t = Table(box=None, header_style=style("dim"), pad_edge=False)
    t.add_column("kind", overflow="fold")
    t.add_column("count", justify="right")
    t.add_column("before", justify="right")
    t.add_column("after", justify="right")
    t.add_column("saved", justify="right")
    for r in rows:
        t.add_row(escape(str(r.get("kind") or "-")),
                  k(r.get("count")),
                  k(r.get("tokens_before")),
                  k(r.get("tokens_after")),
                  f"[{style('good')}]{k(r.get('saved'))}[/]")
    return t


def kv_panel(title: str, pairs) -> Panel:
    """A small bordered panel of label/value lines, for the shape of a window."""
    dim = style("dim")
    t = Table(box=None, show_header=False, pad_edge=False, padding=(0, 2, 0, 0))
    t.add_column(no_wrap=True)
    t.add_column(overflow="fold")
    items = list(pairs or [])
    if not items:
        t.add_row(f"[{dim}]nothing recorded yet[/]", "")
    for label, value in items:
        t.add_row(f"[{dim}]{escape(str(label))}[/]", escape(str(value)))
    return Panel(t, title=escape(str(title)), title_align="left",
                 border_style=dim, padding=(0, 1))


def check_table(checks: list[tuple[str, bool, str]]) -> Table:
    """Pass/fail evidence table used by `tokunseba verify`."""
    t = Table(box=None, header_style=style("dim"), pad_edge=False)
    t.add_column(" ", no_wrap=True)
    t.add_column("check", overflow="fold")
    t.add_column("evidence", overflow="fold")
    for name, ok, detail in checks:
        mark = f"[{style('good')}]pass[/]" if ok else f"[{style('bad')}]fail[/]"
        t.add_row(mark, escape(str(name)), f"[{style('dim')}]{escape(str(detail))}[/]")
    return t
