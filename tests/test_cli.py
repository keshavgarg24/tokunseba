import json

from click.testing import CliRunner

from tokunseba import config
from tokunseba.cli import main
from tokunseba.ledger import Ledger, RequestRecord, TransformRow


def run(args, **kw):
    return CliRunner().invoke(main, args, **kw)


def test_version_and_help():
    assert "0.1.0" in run(["--version"]).output
    assert "Cut token usage" in run(["--help"]).output


def test_config_show_and_set(home):
    assert run(["config", "show"]).exit_code == 0
    r = run(["config", "set", "judge.gate_threshold", "0.9"])
    assert r.exit_code == 0 and "0.9" in r.output
    assert config.load().judge.gate_threshold == 0.9


def test_config_set_bool_int_and_list(home):
    run(["config", "set", "tiers.tier3", "true"])
    run(["config", "set", "proxy.port", "7999"])
    run(["config", "set", "judge.backends", "rules,laya"])
    cfg = config.load()
    assert cfg.tier3 is True and cfg.port == 7999
    assert cfg.judge.backends == ["rules", "laya"]


def test_config_set_tier3_section(home):
    run(["config", "set", "tier3.effort_routing", "yes"])
    assert config.load().tier3_opts.effort_routing is True


def test_config_set_rejects_unknown_key(home):
    r = run(["config", "set", "nope.nothing", "1"])
    assert r.exit_code == 1 and "unknown key" in r.output


def _seed(home):
    led = Ledger(home / "ledger.sqlite")
    led.upsert_session("s1", "claude-code", "/p", "anthropic", "claude-opus-5", "control")
    led.record_request(RequestRecord(
        id="req1", ts=__import__("time").time(), session_id="s1", tool_id="claude-code",
        project="/p", provider="anthropic", model="claude-opus-5", stream=False,
        input_tokens=1000, cache_read=9000, cache_write=0, output_tokens=100,
        est_tokens_before=5000, est_tokens_after=2000, cost_usd=0.02,
        counterfactual_usd=0.05, arm="control", status=200, latency_ms=100, body_path=""))
    led.record_event("cache_drift", {"region": "system"})
    return led


def test_stats_renders(home):
    _seed(home)
    out = run(["stats", "--since", "7d"]).output
    assert "tokens saved" in out and "3.0k" in out and "claude-code" in out
    assert "cache_drift" in out


def test_stats_json(home):
    _seed(home)
    r = run(["stats", "--json"])
    assert json.loads(r.output)["requests"] == 1


def test_stats_ab_renders_arms(home):
    _seed(home)
    out = run(["stats", "--ab"]).output
    assert "tier 3 arms" in out and "control" in out


def test_stats_ab_note_when_no_arms(home):
    Ledger(home / "ledger.sqlite")
    assert "every session is a control" in run(["stats", "--ab"]).output


def test_status_reports_not_running(dead_port):
    out = run(["status"]).output
    assert "not running" in out


def test_expand_roundtrip(home):
    from tokunseba.transform.handles import HandleStore
    h = HandleStore(config.home() / "blobs").put("the whole original output\nline two")
    r = run(["expand", h])
    assert r.exit_code == 0 and "line two" in r.output
    assert run(["expand", "h_missing"]).exit_code == 1


def test_explain_shows_transforms(home):
    led = _seed(home)
    led.put_transform(TransformRow("abc", "summary:pytest", "short version", 900, 40, "h_x", ""))
    led.link_transform("req1", "abc", "('messages',2)", 860)
    out = run(["explain", "req1"]).output
    assert "summary:pytest" in out and "900" in out and "h_x" in out
    assert run(["explain", "nope"]).exit_code == 1


def test_prune_reports_counts(home):
    _seed(home)
    assert "request rows" in run(["prune", "--days", "0"]).output


def test_statusline_offline_is_graceful(dead_port):
    r = run(["statusline"], input="{}")
    assert r.exit_code == 0 and "offline" in r.output


def test_ui_renders_in_the_terminal_without_a_proxy(dead_port):
    """There is no browser any more: the dashboard must still render from the ledger."""
    r = run(["ui"])
    assert r.exit_code == 0
    assert "proxy not running" in r.output.replace("\n", " ")


def test_init_and_off_do_not_touch_real_files(home, tmp_path, monkeypatch):
    """init must never reach outside the sandbox in a test, and off must reverse it."""
    from tokunseba.detect import claude_code, codex, envfile, registry
    monkeypatch.setattr(registry.shutil, "which", lambda _n: None)
    monkeypatch.setattr(claude_code, "SETTINGS", tmp_path / "s.json")
    monkeypatch.setattr(codex, "CONFIG", tmp_path / "c.toml")
    monkeypatch.setattr(envfile, "PROFILE_OVERRIDE", tmp_path / "profile")
    r = run(["init", "--no-service"])
    assert r.exit_code == 0, r.output
    assert "Tools" in r.output
    assert (tmp_path / "s.json").exists() and (tmp_path / "profile").exists()
    assert "tokunseba" in (tmp_path / "profile").read_text()
    r2 = run(["off"])
    assert r2.exit_code == 0
    assert "tokunseba" not in (tmp_path / "profile").read_text()


def test_doctor_runs_and_reports(home, tmp_path, monkeypatch):
    from tokunseba.detect import claude_code, codex, envfile, registry
    monkeypatch.setattr(registry.shutil, "which", lambda _n: None)
    monkeypatch.setattr(claude_code, "SETTINGS", tmp_path / "s.json")
    monkeypatch.setattr(codex, "CONFIG", tmp_path / "c.toml")
    monkeypatch.setattr(envfile, "PROFILE_OVERRIDE", tmp_path / "profile")
    out = run(["doctor"]).output
    assert "proxy reachable" in out and "laya installed" in out


def test_run_wrapper_compresses(home):
    r = run(["run", "--", "python", "-c",
             "print('\\n'.join('line %d' % i for i in range(600)))"])
    assert r.exit_code == 0
    assert "tokunseba expand h_" in r.output
    assert len(r.output.splitlines()) < 400


def test_run_wrapper_propagates_exit_code(home):
    assert run(["run", "--", "python", "-c", "import sys; sys.exit(3)"]).exit_code == 3


def test_doctor_does_not_eat_bracketed_hints(home, tmp_path, monkeypatch):
    """Rich treats [laya] as markup; the install hint must survive rendering."""
    from tokunseba.detect import claude_code, codex, envfile, registry
    monkeypatch.setattr(registry.shutil, "which", lambda _n: None)
    monkeypatch.setattr(claude_code, "SETTINGS", tmp_path / "s.json")
    monkeypatch.setattr(codex, "CONFIG", tmp_path / "c.toml")
    monkeypatch.setattr(envfile, "PROFILE_OVERRIDE", tmp_path / "profile")
    monkeypatch.setattr(registry, "_have", lambda _m: False)
    out = run(["doctor"]).output.replace("\n", "").replace(" ", "")
    assert "tokunseba[laya]" in out and "tokunseba[mcp]" in out


def test_stats_survives_a_bracketed_tool_name(home):
    led = _seed(home)
    led.record_request(RequestRecord(
        id="r2", ts=__import__("time").time(), session_id="s2", tool_id="[odd]tool",
        project="/p", provider="anthropic", model="m", stream=False, input_tokens=1,
        cache_read=0, cache_write=0, output_tokens=1, est_tokens_before=1,
        est_tokens_after=1, cost_usd=0.0, counterfactual_usd=0.0, arm="", status=200,
        latency_ms=1, body_path=""))
    assert "[odd]tool" in run(["stats"]).output.replace("\n", "")
