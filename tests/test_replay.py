"""Offline what-if over traffic that already happened.

The two things these tests care about are whether the answer is honest and whether asking
for it is free. Honest means a conversation is walked in order, so the prefix each decision
rests on is the real one, and a request with no stored body is left out of the arithmetic
rather than counted as zero. Free means a replay writes nothing of yours: no handle, no
event, no learned ratio, no frozen replacement.
"""
import json
import time

import pytest
from click.testing import CliRunner

from tokunseba import config, replay
from tokunseba.cli import main
from tokunseba.ledger import Ledger, RequestRecord


@pytest.fixture(autouse=True)
def wide_console(monkeypatch):
    monkeypatch.setenv("COLUMNS", "160")


def run(args, **kw):
    return CliRunner().invoke(main, args, **kw)


def _big(lines: int = 400) -> str:
    return "\n".join(f"line {i} of output that is long enough to be worth removing"
                     for i in range(lines))


def _turn(text: str, previous: list[dict] | None = None) -> dict:
    """An Anthropic body whose last message carries `text` as a tool result."""
    messages = list(previous or [])
    messages.append({"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": f"t{len(messages)}", "content": text}]})
    return {"model": "claude-opus-5", "max_tokens": 100, "messages": messages}


def _seed(home, bodies: list[tuple[str, dict]], **row) -> Ledger:
    led = Ledger(home / "ledger.sqlite")
    d = home / "bodies"
    d.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for i, (rid, body) in enumerate(bodies):
        (d / f"{rid}.orig.json").write_text(json.dumps(body))
        base = dict(id=rid, ts=now - 100 + i, session_id="s1", tool_id="claude-code",
                    project="/p", provider="anthropic", model="claude-opus-5", stream=False,
                    input_tokens=1000, cache_read=0, cache_write=0, output_tokens=10,
                    est_tokens_before=0, est_tokens_after=0, arm="control", status=200,
                    latency_ms=10, body_path="")
        base.update(row)
        base["id"] = rid
        base["ts"] = now - 100 + i
        led.record_request(RequestRecord(**base))
    return led


# --- the module ---------------------------------------------------------------------

def test_a_recorded_request_is_replayed_and_reports_what_would_be_removed(home):
    led = _seed(home, [("r1", _turn(_big()))])
    cfg = config.load()
    res = replay.run(cfg, led.requests_in_order(0), home / "bodies")
    assert res.replayed == 1
    assert res.would_save > 0
    assert res.by_kind, "a large tool result should have matched some transform"


def test_a_request_with_no_stored_body_is_left_out_rather_than_counted_as_zero(home):
    led = _seed(home, [("r1", _turn(_big()))])
    (home / "bodies" / "r1.orig.json").unlink()
    res = replay.run(config.load(), led.requests_in_order(0), home / "bodies")
    assert (res.considered, res.replayed, res.no_body) == (1, 0, 1)
    assert res.would_save == 0


def test_a_body_that_cannot_be_read_does_not_fail_the_whole_replay(home):
    led = _seed(home, [("r1", _turn(_big())), ("r2", _turn(_big()))])
    (home / "bodies" / "r1.orig.json").write_text("{not json")
    res = replay.run(config.load(), led.requests_in_order(0), home / "bodies")
    assert res.unreadable == 1 and res.replayed == 1


def test_a_conversation_is_walked_as_one_thread(home):
    """Two turns of a conversation have to land in the same session.

    Every decision in the pipeline rests on how much of a request is new, and that is
    measured against the previous turn. A replay that treated each row as an unrelated
    request would judge settled history as though it had just arrived.
    """
    first = _turn(_big())
    second = _turn(_big(600), previous=first["messages"])
    led = _seed(home, [("r1", first), ("r2", second)])
    res = replay.run(config.load(), led.requests_in_order(0), home / "bodies")
    assert len(res.turns) == 2
    assert res.turns[0].session_id == res.turns[1].session_id


def test_the_rows_arrive_oldest_first_even_when_the_window_is_clipped(home):
    """`--limit` has to take the most recent traffic and then put it back in order."""
    bodies = [(f"r{i}", _turn(_big(20 + i))) for i in range(5)]
    led = _seed(home, bodies)
    assert [r["id"] for r in led.requests_in_order(0)] == ["r0", "r1", "r2", "r3", "r4"]
    assert [r["id"] for r in led.requests_in_order(0, limit=2)] == ["r3", "r4"]


def test_replaying_writes_nothing_into_the_real_home(home):
    led = _seed(home, [("r1", _turn(_big()))])
    before = sorted(p.name for p in home.iterdir())
    events_before = len(led.events())
    replay.run(config.load(), led.requests_in_order(0), home / "bodies")
    assert sorted(p.name for p in home.iterdir()) == before
    assert len(Ledger(home / "ledger.sqlite").events()) == events_before
    assert not (home / "blobs").exists()


def test_the_difference_is_against_what_actually_ran(home):
    led = _seed(home, [("r1", _turn(_big()))], est_tokens_before=9000, est_tokens_after=8999)
    res = replay.run(config.load(), led.requests_in_order(0), home / "bodies")
    turn = res.turns[0]
    assert turn.was_saved == 1
    assert turn.change == turn.would_save - 1
    assert res.changed == [turn]


def test_turning_a_tier_off_removes_less(home):
    led = _seed(home, [("r1", _turn(_big()))])
    rows = led.requests_in_order(0)
    on = replay.run(config.load(), rows, home / "bodies")
    off = config.load()
    off.lossless = False
    assert replay.run(off, rows, home / "bodies").would_save == 0
    assert on.would_save > 0


# --- the command --------------------------------------------------------------------

def test_replay_reports_the_difference(home, dead_port):
    _seed(home, [("r1", _turn(_big()))])
    r = run(["replay", "--since", "30d"])
    assert r.exit_code == 0
    out = " ".join(r.output.split())
    assert "1 requests replayed" in out
    assert "as it ran" in out and "as configured here" in out and "difference" in out


def test_replay_says_so_when_there_is_nothing_recorded(home, dead_port):
    Ledger(home / "ledger.sqlite")
    r = run(["replay"])
    assert r.exit_code == 0 and "No requests recorded" in r.output


def test_replay_names_the_requests_that_would_change(home, dead_port):
    _seed(home, [("r1", _turn(_big()))], est_tokens_before=1, est_tokens_after=1)
    out = " ".join(run(["replay", "--since", "30d", "--verbose"]).output.split())
    assert "would come out different" in out and "r1" in out


def test_replay_rejects_a_malformed_override(home, dead_port):
    _seed(home, [("r1", _turn(_big()))])
    assert run(["replay", "--set", "nonsense"]).exit_code == 1
    assert run(["replay", "--set", "thresholds.not_a_key=3"]).exit_code == 1


def test_an_override_changes_the_replay_but_never_the_saved_config(home, dead_port):
    _seed(home, [("r1", _turn(_big()))])
    r = run(["replay", "--since", "30d", "--set", "thresholds.truncate_lines=10"])
    assert r.exit_code == 0
    assert "truncate_lines=10" in " ".join(r.output.split())
    assert config.load().thresholds.truncate_lines == 300


def test_replay_never_reaches_tier_three(home, dead_port, monkeypatch):
    """Tier 3 decides which model answers, which no offline pass can stand in for."""
    cfg = config.load()
    cfg.tier3 = True
    config.save(cfg)
    _seed(home, [("r1", _turn(_big()))])
    seen = {}

    real = replay.run
    monkeypatch.setattr(replay, "run", lambda c, rows, d: seen.setdefault("tier3", c.tier3)
                        or real(c, rows, d))
    run(["replay", "--since", "30d"])
    assert seen["tier3"] is False


def test_an_unchanged_config_explains_why_the_two_rows_still_differ(home, dead_port):
    """The honest failure mode of replay, said out loud.

    With no --tier and no --set the two rows look like they should match, and they usually
    do not: a turn whose earlier identical copy fell outside the window cannot be deduped
    against anything here, so it gets summarised instead and removes less. Reading that as
    "my configuration got worse" is the obvious wrong conclusion, so the output names it.
    """
    _seed(home, [("r1", _turn(_big()))], est_tokens_before=1, est_tokens_after=1)
    note = "this is the window rather than the configuration"
    assert note in " ".join(run(["replay", "--since", "30d"]).output.split())
    assert note not in " ".join(
        run(["replay", "--since", "30d", "--tier", "1", "--tier", "2"]).output.split())
