"""The `tokunseba models` group.

Nothing here is allowed to touch the network unless a test asks for it: the probe is the
one part that does I/O and it is always either stubbed or pointed at a closed local port.
"""
from __future__ import annotations

import time

import pytest
from click.testing import CliRunner

from tokunseba import config
from tokunseba.cli import main
from tokunseba.commands_models import guess_kind, reachable, seen_table, upstream_table
from tokunseba.ledger import Ledger


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKUNSEBA_HOME", str(tmp_path))
    return tmp_path


def run(*args):
    return CliRunner().invoke(main, ["models", *args])


def flat(text: str) -> str:
    """Rich wraps to the terminal width, so compare on collapsed whitespace."""
    return " ".join(text.split())


# ------------------------------------------------------------------ protocol guessing
@pytest.mark.parametrize("url,kind", [
    ("https://api.deepseek.com", "openai"),
    ("https://api.anthropic.com", "anthropic"),
    ("https://generativelanguage.googleapis.com", "gemini"),
    ("http://127.0.0.1:11434", "ollama"),
    ("http://localhost:1234", "ollama"),
    ("https://example.invalid/v1", "openai"),
])
def test_the_protocol_is_guessed_from_the_host(url, kind):
    assert guess_kind(url) == kind


def test_a_guess_is_never_taken_from_the_name_the_user_chose(home):
    """Naming an endpoint "anthropic" must not make tokunseba speak anthropic to it."""
    run("add", "anthropic-clone", "https://api.deepseek.com", "--no-check")
    assert config.load().upstreams["anthropic-clone"].kind == "openai"


# ------------------------------------------------------------------ the probe
def test_a_closed_port_is_reported_as_unreachable():
    ok, detail = reachable("http://127.0.0.1:9")
    assert ok is False
    assert detail


def test_any_http_answer_counts_as_reachable(monkeypatch):
    """A 401 proves the endpoint exists, which is the only question being asked."""
    class Fake:
        status_code = 401
    monkeypatch.setattr("httpx.get", lambda *a, **k: Fake())
    assert reachable("https://example.invalid") == (True, "HTTP 401")


# ------------------------------------------------------------------ add and remove
def test_add_stores_the_endpoint_and_nothing_secret(home):
    res = run("add", "deepseek", "https://api.deepseek.com", "--no-check")
    assert res.exit_code == 0
    up = config.load().upstreams["deepseek"]
    assert up.base_url == "https://api.deepseek.com"
    assert up.kind == "openai"
    assert "api" not in (home / "config.toml").read_text().lower().split("key")[0][-4:]


def test_add_normalises_a_bare_host_and_a_trailing_slash(home):
    run("add", "ds", "api.deepseek.com/", "--no-check")
    assert config.load().upstreams["ds"].base_url == "https://api.deepseek.com"


def test_an_explicit_kind_beats_the_guess(home):
    run("add", "local", "http://127.0.0.1:8080", "--kind", "openai", "--no-check")
    assert config.load().upstreams["local"].kind == "openai"


def test_add_refuses_when_the_probe_finds_nothing(home):
    res = run("add", "dead", "http://127.0.0.1:9", "--check")
    assert res.exit_code == 2
    assert "dead" not in config.load().upstreams
    assert "--no-check" in flat(res.output)


def test_add_saves_when_the_probe_answers(home, monkeypatch):
    class Fake:
        status_code = 200
    monkeypatch.setattr("httpx.get", lambda *a, **k: Fake())
    res = run("add", "live", "http://127.0.0.1:9", "--check")
    assert res.exit_code == 0
    assert "live" in config.load().upstreams


def test_removing_an_upstream_a_rule_points_at_warns_about_the_rule(home):
    cfg = config.load()
    cfg.upstreams["ds"] = config.Upstream("https://api.deepseek.com", "openai")
    cfg.tier3_opts.rules = [{"upstream": "ds", "max_difficulty": 1.0}]
    config.save(cfg)
    res = run("rm", "ds")
    assert res.exit_code == 0
    assert "1 routing rule still points at it" in flat(res.output)


def test_removing_something_that_is_not_there_is_an_error(home):
    assert run("rm", "nope").exit_code == 2


# ------------------------------------------------------------------ the listing
def test_the_listing_shows_which_protocols_may_reach_each_upstream(home):
    out = flat(run().output)
    assert "ollama, openai" in out          # an ollama upstream is reachable from both
    assert "reachable from" in out


def test_the_listing_survives_an_empty_ledger(home):
    res = run()
    assert res.exit_code == 0
    assert "No requests recorded" in flat(res.output)


def test_the_listing_shows_the_models_actually_used(home):
    led = Ledger(home / "ledger.sqlite")
    from tokunseba.ledger import RequestRecord
    fields = {f: 0 for f in RequestRecord.__dataclass_fields__}
    fields.update(id="r1", ts=time.time(), session_id="s", tool_id="t", project="p",
                  provider="anthropic", model="claude-haiku-4-5-20251001", stream=0,
                  arm="control", status=200,
                  latency_ms=1, body_path="")
    led.record_request(RequestRecord(**fields))
    assert "claude-haiku-4-5-20251001" in flat(run().output)


def test_an_empty_model_list_renders_rather_than_raising():
    assert seen_table([]) is not None


def test_the_check_column_only_appears_when_asked(home):
    cfg = config.load()
    assert "answering" not in " ".join(c.header for c in upstream_table(cfg).columns)
    checked = {"openai": (True, "HTTP 401")}
    assert "answering" in " ".join(c.header for c in upstream_table(cfg, checked).columns)
