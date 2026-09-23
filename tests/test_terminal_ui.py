"""The dashboard lives in the terminal now, so the terminal is what gets tested."""
import io
import re
import time
from pathlib import Path

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
    """Render to a string exactly the way the real console would."""
    c = Console(file=io.StringIO(), width=width, no_color=True, legacy_windows=False)
    c.print(renderable)
    return c.file.getvalue()


STATS = {
    "requests": 12, "input_tokens": 120_000, "output_tokens": 4_300,
    "tokens_saved": 31_000, "total_tokens": 124_300, "latency_ms": 24_000,
    "cache_read": 90_000, "cache_hit_rate": 0.75, "pct_saved": 0.6,
    "fresh_tokens": 30_000, "avg_context": 10_000, "max_request_tokens": 45_000,
    "events": {"cache_drift": 2, "secret_redacted": 1, "unknown_signal": 5},
    "by_tool": [{"tool": "claude-code", "requests": 10, "tokens_saved": 30_000, "tokens": 110_000},
                {"tool": "codex", "requests": 2, "tokens_saved": 1_000, "tokens": 14_300}],
}

DAILY = [{"day": 0, "tokens_saved": 100, "tokens": 900, "cache_read": 400, "requests": 1},
         {"day": 86400, "tokens_saved": 5_000, "tokens": 40_000, "cache_read": 9_000, "requests": 4},
         {"day": 172800, "tokens_saved": 900, "tokens": 7_000, "cache_read": 800, "requests": 2}]

SESSIONS = [{"id": "s1", "last_seen": time.time(), "tool": "claude-code",
             "project": "/Users/x/code/tokunseba", "model": "claude-opus-5", "arm": "control",
             "requests": 10, "tokens_saved": 30_000, "tokens": 110_000}]


def _seed(home, *, drift: bool = False, transforms: bool = True) -> Ledger:
    """Seeded the same way tests/test_cli.py does it."""
    led = Ledger(home / "ledger.sqlite")
    led.upsert_session("s1", "claude-code", "/p", "anthropic", "claude-opus-5", "control")
    led.record_request(RequestRecord(
        id="req1", ts=time.time(), session_id="s1", tool_id="claude-code",
        project="/p", provider="anthropic", model="claude-opus-5", stream=False,
        input_tokens=1000, cache_read=9000, cache_write=0, output_tokens=100,
        est_tokens_before=5000, est_tokens_after=2000, arm="control", status=200, latency_ms=100, body_path=""))
    if transforms:
        led.put_transform(TransformRow("abc", "summary:pytest", "short version", 900, 40, "h_x", ""))
        led.link_transform("req1", "abc", "('messages',2)", 860)
        led.put_transform(TransformRow("def", "passthrough", "left alone", 4200, 4200, "", ""))
        led.link_transform("req1", "def", "('system',0)", 0)
    if drift:
        led.record_event("cache_drift", {"region": "system"})
    return led


# --------------------------------------------------------------------------- sparkline
def test_sparkline_with_no_data_says_so():
    out = T.sparkline([])
    assert "no data yet" in out
    assert not any(b in out for b in T.BLOCKS)


def test_sparkline_with_a_single_day_still_fills_the_width():
    out = T.sparkline([{"tokens_saved": 500}], width=20)
    assert len(out) == 20
    assert set(out) <= set(T.BLOCKS)


def test_sparkline_with_all_zero_data_does_not_divide_by_zero():
    out = T.sparkline([{"tokens_saved": 0}] * 5, width=12)
    assert out == T.BLOCKS[0] * 12


def test_sparkline_scales_the_peak_to_the_tallest_block():
    out = T.sparkline(DAILY, width=3)
    assert len(out) == 3
    assert out[1] == T.BLOCKS[-1]          # the 5k day is the peak
    assert out[0] != T.BLOCKS[-1]


def test_sparkline_honours_the_requested_width():
    for width in (1, 8, 48, 111):
        assert len(T.sparkline(DAILY, width=width)) == width


def test_sparkline_handles_missing_and_negative_values():
    out = T.sparkline([{"tokens_saved": None}, {}, {"tokens_saved": -5}], width=6)
    assert out == T.BLOCKS[0] * 6


# --------------------------------------------------------------------------- tables
def test_stat_tiles_show_the_headline_numbers():
    """Tokens, ratios and cache behaviour: the numbers that are true on any billing plan."""
    out = render(T.stat_tiles(STATS))
    assert "tokens saved" in out and "31.0k" in out
    assert "60% of tool output" in out
    assert "context sent" in out and "120.0k" in out
    assert "cache efficiency" in out and "75%" in out
    assert "fresh tokens" in out and "30.0k" in out
    assert "avg context" in out and "largest request" in out and "45.0k" in out
    assert "$" not in out


def test_stat_tiles_show_the_average_round_trip():
    """Latency belongs next to size: a smaller request that takes longer is not a win."""
    out = render(T.stat_tiles(STATS))
    assert "avg round trip" in out and "2.0s" in out          # 24s over 12 requests


def test_stat_tiles_hide_the_round_trip_when_nothing_was_recorded():
    assert "avg round trip" not in render(T.stat_tiles({"latency_ms": 0, "requests": 0}))


def test_ms_reads_in_whatever_unit_is_useful():
    assert T.ms(0) == "0ms" and T.ms(940) == "940ms"
    assert T.ms(2_400) == "2.4s" and T.ms(90_000) == "1.5m"


def test_stat_tiles_survive_an_empty_stats_dict():
    out = render(T.stat_tiles({}))
    assert "tokens saved" in out and "0" in out


def test_by_tool_table_draws_a_proportional_bar():
    out = render(T.by_tool_table(STATS["by_tool"]))
    assert "claude-code" in out and "codex" in out
    assert T.BAR in out
    bars = [len(re.findall(T.BAR, line)) for line in out.splitlines() if T.BAR in line]
    assert bars[0] > bars[1]  # the tool that saved more gets the longer bar


def test_by_tool_table_is_explicit_when_empty():
    assert "nothing recorded yet" in render(T.by_tool_table([]))


def test_signal_table_explains_every_signal_it_shows():
    out = render(T.signal_table(STATS["events"]))
    assert "cache_drift" in out
    assert "re-read it in full" in out                   # the ported explanation
    assert "secret_redacted" in out and "replaced before" in out
    assert "no explanation recorded" in out              # unknown_signal is still honest


def test_signal_table_is_explicit_when_empty():
    assert "no signals yet" in render(T.signal_table({}))


def test_sessions_table_shortens_the_project_path():
    out = render(T.sessions_table(SESSIONS))
    assert "code/tokunseba" in out and "/Users/x/" not in out
    assert "claude-opus-5" in out and "30.0k" in out


def test_sessions_table_is_explicit_when_empty():
    assert "no sessions yet" in render(T.sessions_table([]))


def test_transform_and_passthrough_tables_render_both_ways():
    wins = [{"kind": "summary:pytest", "saved": 860, "handle": "h_x",
             "orig_tokens": 900, "new_tokens": 40, "request_id": "req1",
             "position": "('messages',2)"}]
    misses = [{"orig_sha": "deadbeefcafe1234", "orig_tokens": 4200, "created": 1790082785.0}]
    out = render(T.transform_table(wins))
    assert "summary:pytest" in out and "860" in out and "h_x" in out
    out = render(T.passthrough_table(misses))
    assert "4.2k" in out and "deadbeefcafe1234" in out


def test_passthrough_table_survives_a_missing_timestamp():
    """These rows come straight from the transform table, so tolerate an absent created."""
    out = render(T.passthrough_table([{"orig_sha": "abc", "orig_tokens": 10}]))
    assert "abc" in out
    assert "no transforms recorded yet" in render(T.transform_table([]))
    assert "nothing was passed through untouched" in render(T.passthrough_table([]))


def test_check_table_marks_pass_and_fail():
    out = render(T.check_table([("proxy reachable", True, "127.0.0.1:8899"),
                                ("transforms applied", False, "none")]))
    assert "pass" in out and "fail" in out and "127.0.0.1:8899" in out


def test_short_project_keeps_the_last_two_segments():
    assert T.short_project("/a/b/c/d") == "c/d"
    assert T.short_project("") == "-"
    assert T.short_project("/only") == "only"


@pytest.mark.parametrize("name", ["[odd]tool", "[/bold]x", "[dim"])
def test_a_bracketed_name_survives_rendering(name):
    """Rich would eat [odd] as markup; every user string has to be escaped."""
    rows = [{"tool": name, "requests": 1, "tokens_saved": 10, "tokens": 100}]
    assert name in render(T.by_tool_table(rows)).replace("\n", "")
    sess = [{"last_seen": time.time(), "tool": name, "project": "/a/b",
             "model": name, "requests": 1, "tokens_saved": 1, "tokens": 10}]
    assert name in render(T.sessions_table(sess)).replace("\n", "")


# --------------------------------------------------------------------------- commands
def test_ui_renders_without_a_proxy_running(home, dead_port):
    _seed(home)
    r = run(["ui"])
    assert r.exit_code == 0, r.output
    flat = r.output.replace("\n", " ")
    assert "proxy not running" in flat
    assert "claude-code" in flat and "recent sessions" in flat


def test_ui_renders_on_a_completely_empty_ledger(dead_port):
    r = run(["ui"])
    assert r.exit_code == 0, r.output
    assert "no data yet" in r.output and "nothing recorded yet" in r.output


def test_ui_has_a_watch_flag_and_a_watch_alias():
    help_text = run(["ui", "--help"]).output
    assert "--watch" in help_text and "-w" in help_text
    assert run(["watch", "--help"]).exit_code == 0


def test_ui_survives_a_bracketed_tool_name(home):
    led = _seed(home)
    led.record_request(RequestRecord(
        id="r2", ts=time.time(), session_id="s2", tool_id="[odd]tool", project="/p",
        provider="anthropic", model="m", stream=False, input_tokens=1, cache_read=0,
        cache_write=0, output_tokens=1, est_tokens_before=1, est_tokens_after=1,
        arm="", status=200, latency_ms=1,
        body_path=""))
    assert "[odd]tool" in run(["ui"]).output.replace("\n", "")


def _healthy(monkeypatch):
    from tokunseba import service
    from tokunseba.detect import registry
    monkeypatch.setattr(service, "running", lambda _port: True)
    monkeypatch.setattr(registry, "detect_all", lambda: [
        registry.ToolStatus("claude-code", True, True, "/tmp/settings.json", "")])


def test_verify_passes_on_a_healthy_ledger(home, monkeypatch):
    _healthy(monkeypatch)
    _seed(home)
    r = run(["verify"])
    assert r.exit_code == 0, r.output
    flat = r.output.replace("\n", " ")
    assert "verified" in flat and "not verified" not in flat
    assert "pass" in flat and "summary:pytest" in flat


def test_an_advisory_failure_is_footnoted_by_what_happened_not_by_its_name(home, monkeypatch):
    """Checks are named for the good state, so the name of a failing one is a lie.

    "no cache drift" printed as the reason verify was less than clean reads as a
    reassurance that there was none, which is the opposite of what it means.
    """
    from tokunseba.ledger import Ledger
    _healthy(monkeypatch)
    _seed(home)
    led = Ledger(home / "ledger.sqlite")
    for i in range(6):
        led.record_event("cache_drift", {"region": "system"}, session_id="s", request_id=f"r{i}")
    led.close()
    out = " ".join(run(["verify"]).output.split())
    assert "6 drift signals" in out
    assert "(no cache drift)" not in out


def test_verify_fails_when_nothing_is_being_transformed(home, monkeypatch):
    _healthy(monkeypatch)
    _seed(home, transforms=False)
    r = run(["verify"])
    assert r.exit_code == 1
    flat = r.output.replace("\n", " ")
    assert "not verified" in flat and "transforms actually applied" in flat


def test_verify_fails_when_the_proxy_is_unreachable(home, dead_port):
    _seed(home)
    r = run(["verify"])
    assert r.exit_code == 1
    assert "proxy reachable" in r.output.replace("\n", " ")


def test_verify_reports_cache_drift_without_failing(home, monkeypatch):
    _healthy(monkeypatch)
    _seed(home, drift=True)
    r = run(["verify"])
    assert r.exit_code == 0, r.output
    assert "drift" in r.output.replace("\n", " ")


def test_verify_on_an_empty_ledger_gives_guidance(dead_port):
    r = run(["verify"])
    assert r.exit_code == 0, r.output
    flat = r.output.replace("\n", " ")
    assert "Nothing has been recorded yet" in flat
    assert "tokunseba init" in flat and "tokunseba start" in flat
    assert "fail" not in flat


def test_top_renders_with_data(home):
    _seed(home)
    r = run(["top"])
    assert r.exit_code == 0, r.output
    flat = r.output.replace("\n", " ")
    assert "summary:pytest" in flat and "biggest savings" in flat
    assert "could not help with" in flat and "4.2k" in flat


def test_top_renders_without_data(dead_port):
    r = run(["top"])
    assert r.exit_code == 0, r.output
    assert "no transforms recorded yet" in r.output
    assert "nothing was passed through untouched" in r.output


# --------------------------------------------------------------------------- parity
def test_every_emitted_signal_is_explained_in_the_terminal():
    """A signal nobody can interpret is noise, in the terminal as much as the old page."""
    src = Path("src/tokunseba")
    emitted = set()
    for f in src.rglob("*.py"):
        emitted |= set(re.findall(r'record_event\(\s*"([a-z_]+)"', f.read_text()))
    missing = sorted(emitted - set(T.EVENT_HELP))
    assert not missing, f"signals with no terminal explanation: {missing}"


def test_every_signal_the_code_emits_is_explained():
    """The terminal is now the only place a signal gets explained, so it must cover them all."""
    import re
    from pathlib import Path
    src = Path("src/tokunseba")
    emitted = set()
    for f in src.rglob("*.py"):
        emitted |= set(re.findall(r'record_event\(\s*"([a-z_]+)"', f.read_text()))
    from tokunseba.ui.terminal import EVENT_HELP
    missing = sorted(emitted - set(EVENT_HELP))
    assert not missing, f"signals with no explanation: {missing}"


