import time

from tokunseba.ledger import Ledger, RequestRecord, TransformRow


def _rec(**kw):
    base = dict(id="r1", ts=time.time(), session_id="s1", tool_id="claude-code", project="/p",
                provider="anthropic", model="claude-opus-5", stream=True, input_tokens=1000,
                cache_read=5000, cache_write=0, output_tokens=200, est_tokens_before=7000,
                est_tokens_after=6000, arm="control",
                status=200, latency_ms=800, body_path="")
    base.update(kw)
    return RequestRecord(**base)


def test_request_and_stats(home):
    led = Ledger(home / "ledger.sqlite")
    led.upsert_session("s1", "claude-code", "/p", "anthropic", "claude-opus-5", "control")
    led.record_request(_rec())
    led.record_event("cache_drift", {"region": "system"}, session_id="s1", request_id="r1")
    s = led.stats(since_ts=0)
    assert s["requests"] == 1
    assert s["tokens_saved"] == 1000
    assert s["total_tokens"] == 6200        # everything read and written, cache included
    assert s["latency_ms"] == 800
    assert s["events"]["cache_drift"] == 1
    assert s["by_tool"][0]["tool"] == "claude-code"
    assert 0 < s["cache_hit_rate"] < 1


def test_transform_roundtrip(home):
    led = Ledger(home / "ledger.sqlite")
    row = TransformRow(orig_sha="abc", kind="canonical", transformed="x",
                       orig_tokens=10, new_tokens=5, handle="", ref_sha="")
    led.put_transform(row)
    assert led.get_transform("abc").new_tokens == 5
    assert led.get_transform("zzz") is None


def test_transform_is_frozen(home):
    led = Ledger(home / "ledger.sqlite")
    led.put_transform(TransformRow("abc", "canonical", "first", 10, 5, "", ""))
    led.put_transform(TransformRow("abc", "summary", "second", 10, 2, "", ""))
    assert led.get_transform("abc").transformed == "first"


def test_project_filter_and_token_totals(home):
    led = Ledger(home / "ledger.sqlite")
    led.record_request(_rec(id="a", project="/one"))
    led.record_request(_rec(id="b", project="/two"))
    assert led.stats(0, project="/one")["requests"] == 1
    assert led.tokens_since(0) == 12400
    assert led.tokens_since(0, "/one") == 6200


def test_tokens_since_counts_cache_reads(home):
    """A loop that re-reads the same prefix has still made the provider serve those tokens."""
    led = Ledger(home / "ledger.sqlite")
    led.record_request(_rec(id="a", input_tokens=0, cache_read=100_000, output_tokens=0))
    assert led.tokens_since(0) == 100_000


def test_sessions_and_arms(home):
    led = Ledger(home / "ledger.sqlite")
    led.upsert_session("s1", "claude-code", "/p", "anthropic", "claude-opus-5", "treatment")
    led.upsert_session("s1", "claude-code", "", "anthropic", "claude-opus-5", "treatment")
    assert led.session_arm("s1") == "treatment"
    assert led.recent_sessions()[0]["project"] == "/p"
    led.record_request(_rec(arm="treatment"))
    led.record_request(_rec(id="r2", session_id="s2", arm="control"))
    ab = led.stats_ab(0)
    assert ab["treatment"]["sessions"] == 1 and ab["control"]["requests"] == 1


def test_tool_sessions_and_cwd(home):
    led = Ledger(home / "ledger.sqlite")
    led.register_tool_session("abc-123", "claude-code", "/work/proj")
    assert led.cwd_for_session("abc-123") == "/work/proj"
    assert led.recent_cwd("claude-code") == "/work/proj"
    assert led.recent_cwd("codex") == ""


def test_kv_and_events_and_daily(home):
    led = Ledger(home / "ledger.sqlite")
    led.kv_set("ratio/anthropic/x", 0.31)
    assert led.kv_get("ratio/anthropic/x") == 0.31
    assert led.kv_get("missing", 7) == 7
    led.record_event("cache_injected", {"n": 3})
    assert led.events(kind="cache_injected")[0]["payload"]["n"] == 3
    led.record_request(_rec())
    assert led.daily(14)[0]["requests"] == 1


def test_linked_transforms_and_prune(home):
    led = Ledger(home / "ledger.sqlite")
    led.put_transform(TransformRow("s", "summary:pytest", "short", 100, 10, "h_abc", ""))
    led.link_transform("r1", "s", "('messages',0)", 90)
    t = led.transforms_for("r1")
    assert t[0]["kind"] == "summary:pytest" and t[0]["handle"] == "h_abc"
    assert led.live_handles() == {"h_abc"}
    led.record_request(_rec(ts=time.time() - 40 * 86400))
    assert led.prune(30) == 1
    assert led.stats(0)["requests"] == 0
