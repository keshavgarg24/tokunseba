"""The reporting surface: ledger queries, renderers, `tokunseba report`.

A currency figure is only correct for one kind of access and silently wrong for every other
one, so tokunseba does not print any. These tests pin what replaced it: token counts, ratios,
cache behaviour and round-trip time, which mean the same thing to everybody, and the rule
that no flag anywhere brings a currency figure back.
"""
import io
import json
import time

import pytest
from click.testing import CliRunner
from rich.console import Console

from tokunseba.cli import main
from tokunseba.ledger import Ledger, RequestRecord, TransformRow
from tokunseba.ui import terminal as T


@pytest.fixture(autouse=True)
def wide_console(monkeypatch):
    """Rich sizes to the terminal; pin it so assertions do not depend on the window."""
    monkeypatch.setenv("COLUMNS", "160")


def run(args, **kw):
    return CliRunner().invoke(main, args, **kw)


def render(renderable, width: int = 120) -> str:
    c = Console(file=io.StringIO(), width=width, no_color=True, legacy_windows=False)
    c.print(renderable)
    return c.file.getvalue()


def _request(led: Ledger, rid: str, **kw) -> None:
    """One request, seeded the way tests/test_cli.py does it."""
    base = dict(id=rid, ts=time.time(), session_id="s1", tool_id="claude-code", project="/p",
                provider="anthropic", model="claude-opus-5", stream=False, input_tokens=1000,
                cache_read=9000, cache_write=0, output_tokens=100, est_tokens_before=5000,
                est_tokens_after=2000, arm="control",
                status=200, latency_ms=100, body_path="")
    base.update(kw)
    led.record_request(RequestRecord(**base))


def _seed(home) -> Ledger:
    """Two sessions, two models, two tools, and tool results in every size bucket."""
    led = Ledger(home / "ledger.sqlite")
    led.upsert_session("s1", "claude-code", "/p", "anthropic", "claude-opus-5", "control")
    led.upsert_session("s2", "codex", "/q", "anthropic", "claude-sonnet-5", "control")
    now = time.time()
    _request(led, "req1", ts=now - 20)
    _request(led, "req2", ts=now - 10, input_tokens=500, cache_read=20_000, output_tokens=200,
             est_tokens_before=3000, est_tokens_after=1000)
    _request(led, "req3", ts=now, session_id="s2", tool_id="codex", project="/q",
             model="claude-sonnet-5", input_tokens=300, cache_read=0, cache_write=1200,
             output_tokens=50, est_tokens_before=800, est_tokens_after=800)
    for sha, kind, orig, new in (("t1", "summary:pytest", 60, 20),
                                 ("t2", "passthrough", 300, 300),
                                 ("t3", "summary:pytest", 1200, 200),
                                 ("t4", "passthrough", 4000, 4000),
                                 ("t5", "summary:ls", 12_000, 900)):
        led.put_transform(TransformRow(sha, kind, "sent instead", orig, new,
                                       f"h_{sha}" if kind != "passthrough" else "", ""))
        led.link_transform("req1", sha, "('messages',1)", orig - new)
    led.record_event("cache_drift", {"region": "system"})
    return led


HISTOGRAM = [{"bucket": "0-100", "lo": 0, "hi": 100, "count": 4, "tokens": 200,
              "compressed_count": 4, "compressed_tokens": 200,
              "passthrough_count": 0, "passthrough_tokens": 0},
             {"bucket": "8k+", "lo": 8000, "hi": None, "count": 2, "tokens": 20_000,
              "compressed_count": 1, "compressed_tokens": 12_000,
              "passthrough_count": 1, "passthrough_tokens": 8_000}]

MODELS = [{"model": "claude-opus-5", "requests": 2, "input_tokens": 30_500,
           "cache_read": 29_000, "fresh_tokens": 1_500, "tokens_saved": 5_000},
          {"model": "claude-sonnet-5", "requests": 1, "input_tokens": 1_500,
           "cache_read": 0, "fresh_tokens": 300, "tokens_saved": 0}]

CURVE = [{"turn": 1, "ts": 0.0, "context_tokens": 10_000, "cache_read": 9_000,
          "fresh_tokens": 1_000},
         {"turn": 2, "ts": 1.0, "context_tokens": 20_500, "cache_read": 20_000,
          "fresh_tokens": 500}]


# --------------------------------------------------------------------- ledger queries
def test_context_growth_orders_turns_and_splits_fresh_from_cache(home):
    rows = _seed(home).context_growth("s1")
    assert [r["turn"] for r in rows] == [1, 2]
    assert rows[0]["context_tokens"] == 10_000 and rows[0]["fresh_tokens"] == 1_000
    assert rows[1]["context_tokens"] == 20_500 and rows[1]["cache_read"] == 20_000


def test_context_growth_counts_cache_writes_as_context(home):
    rows = _seed(home).context_growth("s2")
    assert len(rows) == 1 and rows[0]["context_tokens"] == 1_500
    assert rows[0]["fresh_tokens"] == 300


def test_context_growth_on_an_unknown_or_empty_session_is_empty(home):
    assert _seed(home).context_growth("nope") == []
    assert Ledger(home / "empty.sqlite").context_growth("s1") == []


def test_hourly_totals_the_last_day(home):
    rows = _seed(home).hourly(24)
    assert rows, "three requests were recorded in this hour"
    assert sum(r["requests"] for r in rows) == 3
    assert sum(r["input_tokens"] for r in rows) == 1800   # fresh input only
    assert sum(r["cache_read"] for r in rows) == 29_000
    assert sum(r["tokens_saved"] for r in rows) == 5_000
    assert all(isinstance(r["hour"], int) for r in rows)


def test_hourly_on_an_empty_ledger_is_empty(home):
    assert Ledger(home / "empty.sqlite").hourly(24) == []


def test_tool_result_histogram_buckets_by_size(home):
    rows = _seed(home).tool_result_histogram(time.time() - 3600)
    assert [r["bucket"] for r in rows] == ["0-100", "100-500", "500-2k", "2k-8k", "8k+"]
    assert sum(r["count"] for r in rows) == 5
    assert sum(r["tokens"] for r in rows) == 60 + 300 + 1200 + 4000 + 12_000


def test_tool_result_histogram_splits_compressed_from_passthrough(home):
    rows = {r["bucket"]: r for r in _seed(home).tool_result_histogram(time.time() - 3600)}
    assert rows["2k-8k"]["passthrough_tokens"] == 4000
    assert rows["2k-8k"]["compressed_tokens"] == 0
    assert rows["8k+"]["compressed_tokens"] == 12_000
    assert rows["8k+"]["passthrough_count"] == 0


def test_tool_result_histogram_on_an_empty_ledger_is_empty(home):
    assert Ledger(home / "empty.sqlite").tool_result_histogram(0) == []


def test_model_breakdown_totals_context_and_cache_per_model(home):
    rows = {r["model"]: r for r in _seed(home).model_breakdown(time.time() - 3600)}
    assert set(rows) == {"claude-opus-5", "claude-sonnet-5"}
    opus = rows["claude-opus-5"]
    assert opus["requests"] == 2 and opus["input_tokens"] == 30_500
    assert opus["cache_read"] == 29_000 and opus["fresh_tokens"] == 1_500
    assert opus["tokens_saved"] == 5_000
    assert rows["claude-sonnet-5"]["input_tokens"] == 1_500  # cache writes count as context


def test_model_breakdown_on_an_empty_ledger_is_empty(home):
    assert Ledger(home / "empty.sqlite").model_breakdown(0) == []


def test_summary_counts_describes_the_window(home):
    c = _seed(home).summary_counts(time.time() - 3600)
    assert c == {"sessions": 2, "requests": 3, "models": 2, "projects": 2,
                 "transforms": 5, "handles": 3}


def test_summary_counts_on_an_empty_ledger_is_all_zero(home):
    c = Ledger(home / "empty.sqlite").summary_counts(0)
    assert c == {"sessions": 0, "requests": 0, "models": 0, "projects": 0,
                 "transforms": 0, "handles": 0}


def test_stats_exposes_the_plan_agnostic_numbers(home):
    s = _seed(home).stats(time.time() - 3600)
    assert s["fresh_tokens"] == 1800              # the part cache did not cover
    assert s["max_request_tokens"] == 20_500      # biggest single call
    assert s["avg_context"] == pytest.approx(32_000 / 3)
    assert s["cache_read"] == 29_000


def test_stats_carry_totals_the_tables_have_no_room_for(home):
    """The JSON view is the full record; the tables are an edit of it, not the whole thing."""
    s = _seed(home).stats(time.time() - 3600)
    assert s["total_tokens"] > 0 and s["latency_ms"] > 0


# ------------------------------------------------------------------------- renderers
def test_bar_is_proportional_and_clamped():
    assert len(T.bar(10, 10, 20)) == 20
    assert len(T.bar(5, 10, 20)) == 10
    assert len(T.bar(1, 1_000_000, 20)) == 1      # present but tiny, never invisible
    assert len(T.bar(50, 10, 20)) == 20           # never overflows the width


def test_bar_survives_zero_and_negative_input():
    assert T.bar(0, 10, 20) == ""
    assert T.bar(5, 0, 20) == ""
    assert T.bar(-5, 10, 20) == ""
    assert T.bar(5, 10, 0) == ""
    assert T.bar(None, None, 20) == ""


def test_histogram_shows_every_bucket_and_a_legend():
    out = render(T.histogram(HISTOGRAM))
    assert "0-100" in out and "8k+" in out
    assert "20.0k" in out and T.BAR in out
    assert "compressed" in out and "passed through" in out


def test_histogram_marks_the_compressed_share():
    out = render(T.histogram(HISTOGRAM))
    assert "100%" in out        # the 0-100 bucket was entirely compressed
    assert "60%" in out         # 12k of 20k in the 8k+ bucket


def test_histogram_is_explicit_when_empty():
    assert "no tool results recorded yet" in render(T.histogram([]))


def test_histogram_survives_a_single_all_zero_row():
    row = [{"bucket": "0-100", "count": 0, "tokens": 0, "compressed_tokens": 0,
            "passthrough_tokens": 0}]
    out = render(T.histogram(row))
    assert "0-100" in out and "0%" in out


def test_context_curve_fills_the_requested_width():
    for width in (1, 8, 56, 100):
        assert len(T.context_curve(CURVE, width=width)) == width
    assert set(T.context_curve(CURVE, width=8)) <= set(T.BLOCKS)


def test_context_curve_rises_with_the_context():
    out = T.context_curve(CURVE, width=2)
    assert out[1] == T.BLOCKS[-1] and out[0] != T.BLOCKS[-1]


def test_context_curve_with_a_single_turn_still_renders():
    assert len(T.context_curve([CURVE[0]], width=12)) == 12


def test_context_curve_with_all_zero_rows_does_not_divide_by_zero():
    rows = [{"turn": 1, "context_tokens": 0}, {"turn": 2, "context_tokens": None}]
    assert T.context_curve(rows, width=6) == T.BLOCKS[0] * 6


def test_context_curve_with_no_rows_says_so():
    out = T.context_curve([])
    assert "no session data yet" in out
    assert not any(b in out for b in T.BLOCKS)


def test_model_table_shows_context_cache_and_fresh():
    out = render(T.model_table(MODELS))
    assert "claude-opus-5" in out and "claude-sonnet-5" in out
    assert "30.5k" in out and "29.0k" in out and "1.5k" in out
    assert "95%" in out          # 29k of 30.5k came from cache


def test_model_table_is_explicit_when_empty():
    assert "no models recorded yet" in render(T.model_table([]))


def test_model_table_survives_an_all_zero_row():
    out = render(T.model_table([{"model": "m", "requests": 0, "input_tokens": 0,
                                 "cache_read": 0, "fresh_tokens": 0, "tokens_saved": 0}]))
    assert "m" in out and "0%" in out


def test_transform_kind_table_renders_and_is_explicit_when_empty():
    rows = [{"kind": "summary:pytest", "count": 2, "tokens_before": 1260,
             "tokens_after": 220, "saved": 1040}]
    out = render(T.transform_kind_table(rows))
    assert "summary:pytest" in out and "1.3k" in out and "1.0k" in out
    assert "nothing has been rewritten yet" in render(T.transform_kind_table([]))


def test_kv_panel_renders_its_pairs_inside_a_titled_panel():
    out = render(T.kv_panel("window", [("sessions", "2 across 2 projects"), ("requests", 3)]))
    assert "window" in out and "sessions" in out and "2 across 2 projects" in out
    assert "requests" in out and "3" in out


def test_kv_panel_with_no_pairs_still_renders():
    out = render(T.kv_panel("window", []))
    assert "window" in out and "nothing recorded yet" in out


def test_kv_panel_escapes_user_text():
    out = render(T.kv_panel("[odd]title", [("[dim", "[/bold]x")])).replace("\n", "")
    assert "[odd]title" in out and "[/bold]x" in out


def test_stat_tiles_report_size_ratios_and_time():
    s = {"tokens_saved": 31_000, "pct_saved": 0.6, "input_tokens": 120_000, "requests": 12,
         "cache_read": 90_000, "cache_hit_rate": 0.75, "fresh_tokens": 30_000,
         "avg_context": 10_000, "max_request_tokens": 45_000, "latency_ms": 24_000,
         "by_tool": [{"tool": "claude-code"}]}
    out = render(T.stat_tiles(s))
    assert "tokens saved" in out and "31.0k" in out and "60% of tool output" in out
    assert "fresh tokens" in out and "30.0k" in out
    assert "cache efficiency" in out and "75%" in out
    assert "avg context" in out and "10.0k" in out
    assert "largest request" in out and "45.0k" in out
    assert "avg round trip" in out and "2.0s" in out


def test_stat_tiles_survive_an_empty_stats_dict():
    out = render(T.stat_tiles({}))
    assert "tokens saved" in out and "fresh tokens" in out and "0" in out
    assert "$" not in out


# -------------------------------------------------------------------------- command
def test_report_renders_every_section_with_data(home, dead_port):
    _seed(home)
    r = run(["report"])
    assert r.exit_code == 0, r.output
    flat = r.output.replace("\n", " ")
    for section in ("window", "tokens saved per day", "tool results by size",
                    "transforms by kind", "by tool", "by model", "biggest savings",
                    "biggest untouched", "signals", "recent sessions", "context growth"):
        assert section in flat, section
    assert "claude-code" in flat and "claude-sonnet-5" in flat and "cache_drift" in flat


def test_report_renders_on_a_completely_empty_ledger(home, dead_port):
    r = run(["report"])
    assert r.exit_code == 0, r.output
    flat = r.output.replace("\n", " ")
    assert "no tool results recorded yet" in flat
    assert "no models recorded yet" in flat
    assert "nothing has been rewritten yet" in flat
    assert "no session data yet" in flat
    assert "no sessions yet" in flat


def test_report_json_parses_and_carries_every_block(home, dead_port):
    _seed(home)
    r = run(["report", "--json"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["summary"]["requests"] == 3
    assert data["stats"]["fresh_tokens"] == 1800
    assert len(data["sizes"]) == 5 and len(data["by_model"]) == 2
    assert data["window"]["since"] == "7d"
    assert len(data["context_growth"]) >= 1


def test_report_json_on_an_empty_ledger_still_parses(home, dead_port):
    data = json.loads(run(["report", "--json"]).output)
    assert data["summary"]["requests"] == 0 and data["context_growth"] == []


def test_report_save_writes_a_non_empty_plain_text_file(home, dead_port, tmp_path):
    _seed(home)
    out = tmp_path / "report.txt"
    r = run(["report", "--save", str(out)])
    assert r.exit_code == 0, r.output
    text = out.read_text()
    assert len(text) > 500
    assert "\x1b[" not in text            # plain text, not a terminal recording
    assert "by model" in text and "claude-opus-5" in text
    assert "$" not in text


def test_report_says_what_its_figures_are_counted_in(home, dead_port):
    _seed(home)
    flat = run(["report"]).output.replace("\n", " ")
    assert "tokens, ratios and time" in flat


def test_report_project_filter_narrows_the_request_figures(home, dead_port):
    _seed(home)
    data = json.loads(run(["report", "--project", "/q", "--json"]).output)
    assert data["stats"]["requests"] == 1
    assert data["window"]["project"] == "/q"


def test_report_survives_a_bracketed_tool_name(home, dead_port):
    led = _seed(home)
    _request(led, "r9", session_id="s9", tool_id="[odd]tool", model="[odd]model")
    flat = run(["report"]).output.replace("\n", "")
    assert "[odd]tool" in flat and "[odd]model" in flat


@pytest.mark.parametrize("args", [["stats"], ["ui"], ["top"], ["report"]])
def test_no_currency_anywhere_in_the_rendering(home, dead_port, args):
    """A currency figure is a wrong number here, not a small one. There is no flag for it."""
    _seed(home)
    r = run(args)
    assert r.exit_code == 0, r.output
    assert "$" not in r.output


def test_stats_never_print_a_currency_figure(home, dead_port):
    """Nothing in tokunseba is denominated in currency, on any plan, behind any flag."""
    _seed(home)
    assert "$" not in run(["stats"]).output
    assert "$" not in run(["report"]).output
    assert run(["stats", "--money"]).exit_code != 0        # the flag does not exist


def test_stats_json_carries_more_than_the_tables_show(home, dead_port):
    _seed(home)
    s = json.loads(run(["stats", "--json"]).output)
    assert s["total_tokens"] > 0 and "latency_ms" in s and s["fresh_tokens"] == 1800


def test_statusline_reports_tokens_cache_and_fresh_without_currency(home, dead_port,
                                                                   monkeypatch):
    import httpx

    class _Resp:
        def json(self):
            return {"tokens_saved": 5_000, "pct_saved": 0.42, "cache_hit_rate": 0.91,
                    "fresh_tokens": 1_800, "total_tokens": 42_000,
                    "events": {"cache_drift": 2}}

    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _Resp())
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: None)
    out = run(["statusline"], input="{}").output
    assert "$" not in out
    assert "saved 5.0k (42%)" in out and "cache 91%" in out and "fresh 1.8k" in out
    assert "drift 2" in out


def test_status_shows_fresh_tokens_and_one_next_action(home, dead_port):
    _seed(home)
    out = run(["status"]).output
    assert "$" not in out
    assert "fresh tokens" in out and "cache" in out
    assert "next:" in out and "tokunseba start" in out   # the proxy is not running


#: Both the figures and the vocabulary. A figure is wrong for everybody it was not measured
#: for; the vocabulary is the slope back to one, and it also frames a smaller model as the
#: budget option rather than the right tool. "smaller", "lighter" and "quicker" say the
#: actual thing and are true on any kind of access.
_CURRENCY = r"usd|dollar|\$\{?\d|per.token price|price_for|cost_usd|\bmoney\b|billing|billed"
_VOCAB = r"cheap(er|est)?\b|expensive|\bpays?\b|\bpaid\b|\bspends?\b|\bspent\b|invoice"


def test_no_source_file_reintroduces_a_currency_figure():
    """A guard, not a style rule.

    Every currency figure tokunseba could print would be correct for exactly one kind of
    access and quietly wrong for all the others, which is worse than printing nothing. This
    fails the moment a price, a rate or a dollar sign comes back into the package.
    """
    import re
    from pathlib import Path

    import tokunseba
    root = Path(tokunseba.__file__).parent
    banned = re.compile(f"{_CURRENCY}|{_VOCAB}", re.I)
    # `is_sensitive` and the rules backend deliberately match the *user's* prompt against
    # financial words so those turns are never routed to a smaller model. That is a safety
    # gate on somebody else's text, not a figure tokunseba prints, so it is exempt.
    exempt = {"questions.py", "rules.py"}
    offenders = [f"{p.name}:{i}" for p in root.rglob("*.py") if p.name not in exempt
                 for i, line in enumerate(p.read_text().splitlines(), 1) if banned.search(line)]
    assert not offenders, f"currency reintroduced at {offenders}"


def test_the_docs_do_not_reintroduce_it_either():
    """The pages that explain what tokunseba does are held to the same rule as the code.

    CHANGELOG.md is deliberately not scanned. It has to name the removed flag, module and
    columns or nobody upgrading can tell what went; a record of an absence is the opposite
    of the thing this guards against.
    """
    import re
    from pathlib import Path

    import tokunseba
    root = Path(tokunseba.__file__).parents[2]
    banned = re.compile(f"{_CURRENCY}|{_VOCAB}", re.I)
    docs = [root / n for n in ("README.md", "CONTRIBUTING.md")]
    if not all(d.exists() for d in docs):
        pytest.skip("running against an installed package, not the source tree")
    offenders = [f"{d.name}:{i}" for d in docs
                 for i, line in enumerate(d.read_text().splitlines(), 1) if banned.search(line)]
    assert not offenders, f"currency reintroduced at {offenders}"
