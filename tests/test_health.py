"""The quiet failure: not being in the path at all."""
from tokunseba.health import Routing


def _r(**kw):
    base = dict(proxy_running=True, port=7777, routed_tools=["claude-code"],
                unrouted_installed=[], requests_last_hour=5, requests_ever=20)
    base.update(kw)
    return Routing(**base)


def test_healthy_setup_has_no_problem():
    assert _r().problem is None
    assert _r().in_the_path


def test_proxy_down_is_reported_first():
    p = _r(proxy_running=False, routed_tools=[]).problem
    assert "not running" in p and "tokunseba start" in p


def test_unrouted_is_the_headline_and_names_the_fix():
    p = _r(routed_tools=[], unrouted_installed=["claude-code", "codex"]).problem
    assert "No tool is routed" in p
    assert "every number below is zero for that reason" in p
    assert "claude-code, codex are installed" in p and "tokunseba init" in p
    assert not _r(routed_tools=[]).in_the_path


def test_routed_but_never_used_says_open_a_new_shell():
    p = _r(requests_ever=0, requests_last_hour=0).problem
    assert "NEW terminal" in p


def test_routed_but_quiet_this_hour():
    p = _r(requests_last_hour=0, requests_ever=50).problem
    assert "last hour" in p


def test_check_never_raises_on_a_broken_ledger(home):
    from tokunseba import config
    from tokunseba.health import check

    class Broken:
        def stats(self, *a, **k):
            raise RuntimeError("no table")

    r = check(config.load(), Broken())
    assert r.requests_ever == 0 and isinstance(r.problem, (str, type(None)))


def test_single_unrouted_tool_reads_as_singular():
    p = _r(routed_tools=[], unrouted_installed=["claude-code"]).problem
    assert "claude-code is installed but goes straight" in p


def test_no_known_tools_still_gives_the_fix():
    p = _r(routed_tools=[], unrouted_installed=[]).problem
    assert "Your tools go straight" in p and "tokunseba init" in p


def test_exported_base_url_is_detected(monkeypatch):
    from tokunseba.health import conflicting_env
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    assert conflicting_env(7777) == {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}


def test_our_own_base_url_is_not_a_conflict(monkeypatch):
    from tokunseba.health import conflicting_env
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:7777/anthropic")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:7777/openai/v1")
    assert conflicting_env(7777) == {}


def test_conflict_outranks_every_other_problem():
    """It is the cause; the others are symptoms of it."""
    r = _r(routed_tools=[], proxy_running=False, requests_ever=0,
           overriding_env={"ANTHROPIC_BASE_URL": "https://api.anthropic.com"})
    p = r.problem
    assert "already exported in your environment" in p
    assert "beats the settings file" in p
    assert "https://api.anthropic.com" in p


def test_no_conflict_when_unset(monkeypatch):
    from tokunseba.health import conflicting_env
    for v in ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE", "OLLAMA_HOST"):
        monkeypatch.delenv(v, raising=False)
    assert conflicting_env(7777) == {}


def test_silent_but_configured_points_at_the_gui_app_step():
    """The commonest reason for a correct install that sees nothing.

    A tool opened from the Dock never runs the shell profile, so the one sentence shown
    when the ledger is empty has to name that, or the user has no way to find it.
    """
    never = _r(requests_ever=0).problem
    quiet = _r(requests_ever=200, requests_last_hour=0).problem
    for text in (never, quiet):
        assert "tokunseba apps on" in text


def test_an_overriding_variable_mentions_both_ways_a_tool_gets_started():
    problem = _r(overriding_env={"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}).problem
    assert "new shell" in problem
    assert "tokunseba apps on" in problem
