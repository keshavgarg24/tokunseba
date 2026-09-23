"""Routing for applications the Dock launches, and the `tokunseba apps` group.

This is the failure that cost the most time to diagnose in practice: a correct install that
sees nothing, because the application was never started by a shell and so never read the
shell profile. Most of these tests are about that being said out loud, and about the command
not touching anything it did not put there.
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from tokunseba.cli import main
from tokunseba.detect import guiapps


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKUNSEBA_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def unsealed(monkeypatch, tmp_path):
    """Let the real code paths run, with launchd and the home directory faked out."""
    monkeypatch.delenv(guiapps.SEAL, raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def launchd(monkeypatch, unsealed):
    """A fake login session. Records every launchctl call and answers getenv from a dict."""
    store: dict[str, str] = {}
    calls: list[tuple[str, ...]] = []

    def fake(*args: str) -> tuple[bool, str]:
        calls.append(args)
        if args[0] == "setenv":
            store[args[1]] = args[2]
        elif args[0] == "unsetenv":
            store.pop(args[1], None)
        elif args[0] == "getenv":
            return (args[1] in store), store.get(args[1], "")
        return True, ""

    monkeypatch.setattr(guiapps, "_launchctl", fake)
    monkeypatch.setattr(guiapps, "system", lambda: "macos")
    return store, calls


def run(*args, stdin: str = ""):
    return CliRunner().invoke(main, ["apps", *args], input=stdin)


def flat(text: str) -> str:
    return " ".join(text.split())


# ------------------------------------------------------------------- what it would change
def test_the_four_urls_all_point_at_the_configured_port():
    vals = guiapps.values(9999)
    assert set(vals) == set(guiapps.VARS)
    assert all("127.0.0.1:9999" in v for v in vals.values())


def test_the_plan_on_macos_names_every_command_it_would_run(monkeypatch):
    monkeypatch.setattr(guiapps, "system", lambda: "macos")
    plan = guiapps.plan(7777)
    for name in guiapps.VARS:
        assert any(f"launchctl setenv {name}" in line for line in plan)
    assert any("LaunchAgents" in line for line in plan)


def test_the_plan_on_linux_names_the_file_it_would_write(monkeypatch):
    monkeypatch.setattr(guiapps, "system", lambda: "linux")
    plan = guiapps.plan(7777)
    assert any("environment.d" in line for line in plan)
    assert not any("launchctl" in line for line in plan)


def test_an_unsupported_platform_gets_commands_to_run_by_hand(monkeypatch):
    monkeypatch.setattr(guiapps, "system", lambda: "other")
    assert guiapps.plan(7777) == []
    manual = guiapps.manual(7777)
    assert len(manual) == len(guiapps.VARS)
    assert all(line.startswith("setx ") for line in manual)


# ------------------------------------------------------------------------- not by accident
def test_nothing_touches_the_login_session_while_the_seal_is_set(monkeypatch):
    monkeypatch.setenv(guiapps.SEAL, "1")
    monkeypatch.setattr(guiapps, "_launchctl",
                        lambda *a: pytest.fail(f"launchctl was called: {a}"))
    untouched = f"{guiapps.SEAL} is set, so the login session was not touched"
    assert guiapps.apply(7777) == [untouched]
    assert guiapps.restore(7777)[0].startswith(guiapps.SEAL)
    assert guiapps.current() == dict.fromkeys(guiapps.VARS, "")
    assert not guiapps.supported()


def test_the_seal_is_visible_in_status_rather_than_looking_like_an_unsupported_platform(
        monkeypatch):
    monkeypatch.setenv(guiapps.SEAL, "1")
    _, _, note = guiapps.status(7777)
    assert guiapps.SEAL in note


# ---------------------------------------------------------------------------- applying it
def test_applying_sets_all_four_and_writes_an_agent_that_survives_a_restart(launchd):
    store, _ = launchd
    guiapps.apply(7777)
    assert store == guiapps.values(7777)
    plist = guiapps.agent_plist().read_text()
    for name in guiapps.VARS:
        assert f"launchctl setenv {name}" in plist
    assert "RunAtLoad" in plist


def test_applying_twice_leaves_the_same_state(launchd):
    store, _ = launchd
    guiapps.apply(7777)
    guiapps.apply(7777)
    assert store == guiapps.values(7777)


def test_configured_is_true_only_when_every_variable_points_at_this_proxy(launchd):
    store, _ = launchd
    assert not guiapps.configured(7777)
    guiapps.apply(7777)
    assert guiapps.configured(7777)
    store.pop("OLLAMA_HOST")
    assert not guiapps.configured(7777)


def test_a_proxy_on_a_different_port_does_not_count_as_configured(launchd):
    guiapps.apply(7777)
    assert not guiapps.configured(8888)


# ---------------------------------------------------------------------------- removing it
def test_removing_clears_what_tokunseba_set(launchd):
    store, _ = launchd
    guiapps.apply(7777)
    guiapps.restore(7777)
    assert store == {}
    assert not guiapps.agent_plist().exists()


def test_removing_leaves_a_value_somebody_else_set_alone(launchd):
    store, _ = launchd
    store["ANTHROPIC_BASE_URL"] = "https://my-own-gateway.internal"
    out = guiapps.restore(7777)
    assert store["ANTHROPIC_BASE_URL"] == "https://my-own-gateway.internal"
    assert any("left ANTHROPIC_BASE_URL alone" in line for line in out)


def test_removing_when_nothing_was_ever_applied_is_not_an_error(launchd):
    assert guiapps.restore(7777) == ["nothing to remove"]


# --------------------------------------------------------------------------- the command
def test_status_explains_why_a_dock_launched_app_is_not_routed(home, launchd):
    out = flat(run("status").output)
    assert "never reads that file" in out
    assert "tokunseba apps on" in out


def test_turning_it_on_discloses_the_change_before_asking(home, launchd):
    store, _ = launchd
    out = flat(run("on", stdin="n\n").output)
    assert "will change your login session" in out
    assert "launchctl setenv ANTHROPIC_BASE_URL" in out
    assert "Nothing changed" in out
    assert store == {}


def test_turning_it_on_says_that_open_applications_keep_their_old_environment(home, launchd):
    out = flat(run("on", "-y").output)
    assert "Quit and reopen" in out


def test_turning_it_on_actually_applies_when_confirmed(home, launchd):
    store, _ = launchd
    run("on", stdin="y\n")
    assert store == guiapps.values(7777)


def test_turning_it_on_twice_is_a_no_op_rather_than_a_second_prompt(home, launchd):
    run("on", "-y")
    out = flat(run("on").output)
    assert "already route" in out


def test_turning_it_off_says_terminals_are_unaffected(home, launchd):
    run("on", "-y")
    out = flat(run("off").output)
    assert "Terminals still route" in out
    assert not guiapps.configured(7777)


def test_the_status_table_shows_what_an_app_would_actually_connect_to(home, launchd):
    run("on", "-y")
    out = flat(run("status").output)
    assert "127.0.0.1:7777/anthropic" in out
    assert "GUI applications route through tokunseba" in out


def test_an_unsupported_platform_is_told_what_to_do_instead(home, monkeypatch, unsealed):
    monkeypatch.setattr(guiapps, "system", lambda: "other")
    out = flat(run("status").output)
    assert "setx ANTHROPIC_BASE_URL" in out


# --------------------------------------------------------- stopping is not a silent revert
def _stop(stdin: str = "", *args):
    return CliRunner().invoke(main, ["stop", *args], input=stdin)


def test_stopping_warns_that_routed_tools_will_fail_rather_than_fall_back(home, monkeypatch):
    """Stopping the proxy does not send tools back to the provider.

    Their base URL still points at 127.0.0.1, so the next request is a connection refused.
    That is worth one sentence before it happens.
    """
    from tokunseba.detect import registry
    monkeypatch.setattr(registry, "detect_all", lambda: [
        registry.ToolStatus("claude-code", True, True, "", ""),
    ])
    out = flat(_stop("n\n").output)
    assert "fail to connect" in out
    assert "tokunseba off" in out
    assert "Still running" in out


def test_stopping_with_nothing_routed_does_not_ask(home, monkeypatch):
    from tokunseba import service
    from tokunseba.detect import registry
    monkeypatch.setattr(registry, "detect_all", lambda: [])
    monkeypatch.setattr(service, "stop", lambda: "stopped")
    assert "stopped" in _stop().output


def test_yes_skips_the_question(home, monkeypatch):
    from tokunseba import service
    from tokunseba.detect import registry
    monkeypatch.setattr(registry, "detect_all", lambda: [
        registry.ToolStatus("claude-code", True, True, "", ""),
    ])
    monkeypatch.setattr(service, "stop", lambda: "stopped")
    out = _stop("", "-y").output
    assert "stopped" in out
    assert "fail to connect" not in out
