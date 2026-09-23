"""History is kept for as long as the user asked, and no longer."""
import time

from tokunseba import config
from tokunseba.ledger import Ledger, RequestRecord, TransformRow
from tokunseba.retention import due, maybe_run, run
from tokunseba.transform.handles import HandleStore


def _rec(led, ident, age_days=0.0):
    led.record_request(RequestRecord(
        id=ident, ts=time.time() - age_days * 86400, session_id="s", tool_id="claude-code",
        project="/p", provider="anthropic", model="m", stream=False, input_tokens=10,
        cache_read=0, cache_write=0, output_tokens=1, est_tokens_before=10,
        est_tokens_after=5, arm="", status=200,
        latency_ms=1, body_path=""))


def test_old_rows_go_and_recent_rows_stay(home):
    cfg = config.load()
    cfg.retention.days = 30
    led = Ledger(home / "l.sqlite")
    _rec(led, "new", 1)
    _rec(led, "old", 400)
    out = run(cfg, led, home)
    assert out["rows"] == 1 and not out["skipped"]
    assert led.stats(0)["requests"] == 1


def test_zero_days_keeps_everything(home):
    cfg = config.load()
    cfg.retention.days = 0
    led = Ledger(home / "l.sqlite")
    _rec(led, "old", 9999)
    out = run(cfg, led, home)
    assert out["skipped"] and out["rows"] == 0
    assert led.stats(0)["requests"] == 1


def test_bodies_expire_on_their_own_shorter_clock(home):
    cfg = config.load()
    cfg.retention.days = 90
    cfg.retention.keep_bodies_days = 7
    led = Ledger(home / "l.sqlite")
    bodies = home / "bodies"
    bodies.mkdir(parents=True, exist_ok=True)
    old, new = bodies / "a.orig.json", bodies / "b.orig.json"
    old.write_text("{}")
    new.write_text("{}")
    stale = time.time() - 30 * 86400
    import os
    os.utime(old, (stale, stale))
    out = run(cfg, led, home)
    assert out["bodies"] == 1
    assert new.exists() and not old.exists()


def test_orphaned_blobs_are_collected(home):
    cfg = config.load()
    cfg.retention.days = 30
    led = Ledger(home / "l.sqlite")
    store = HandleStore(home / "blobs")
    keep = store.put("still referenced")
    store.put("nothing points here")
    led.put_transform(TransformRow("sha", "truncate", "short", 100, 10, keep, ""))
    out = run(cfg, led, home)
    assert out["blobs"] == 1
    assert store.get(keep) == "still referenced"


def test_due_is_true_first_time_then_false(home):
    led = Ledger(home / "l.sqlite")
    assert due(led) is True
    led.kv_set("last_prune", time.time())
    assert due(led) is False
    led.kv_set("last_prune", time.time() - 2 * 86400)
    assert due(led) is True


def test_due_survives_a_corrupt_stamp(home):
    led = Ledger(home / "l.sqlite")
    led.kv_set("last_prune", "not a number")
    assert due(led) is True


def test_maybe_run_respects_the_auto_prune_switch(home):
    cfg = config.load()
    cfg.retention.auto_prune = False
    led = Ledger(home / "l.sqlite")
    _rec(led, "old", 400)
    assert maybe_run(cfg, led, home) is None
    assert led.stats(0)["requests"] == 1


def test_maybe_run_only_fires_once_a_day(home):
    cfg = config.load()
    cfg.retention.days = 30
    led = Ledger(home / "l.sqlite")
    _rec(led, "old", 400)
    assert maybe_run(cfg, led, home) is not None
    assert maybe_run(cfg, led, home) is None


def test_housekeeping_never_raises_out(home, monkeypatch):
    """A failure here must not stop the proxy from starting."""
    import tokunseba.retention as r
    cfg = config.load()
    led = Ledger(home / "l.sqlite")
    monkeypatch.setattr(r, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    assert maybe_run(cfg, led, home) is None


def test_retention_is_configurable_and_persists(home):
    cfg = config.load()
    cfg.retention.days = 180
    cfg.retention.keep_bodies_days = 3
    cfg.retention.auto_prune = False
    config.save(cfg)
    again = config.load().retention
    assert again.days == 180 and again.keep_bodies_days == 3 and again.auto_prune is False
