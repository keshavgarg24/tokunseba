"""Wrapping is the reliable way in: it sets the tool's own environment.

An exported base URL beats a settings file, and several launchers export one, so a correct
`init` can be silently overridden. These tests pin the behaviour that makes wrapping immune.
"""
import click
import pytest
from click.testing import CliRunner

from tokunseba.commands_wrap import register
from tokunseba.wrap import (UNSUPPORTED, Wrappable, available, build_env, exec_wrapped,
                            full_env, registry, resolve)


@pytest.fixture
def app():
    g = click.Group()
    register(g)
    return g


def run(app, args, **kw):
    return CliRunner().invoke(app, args, **kw)


# --- the env contract ---

def test_every_tool_points_at_the_local_proxy():
    for name, w in registry(7777).items():
        assert w.env, f"{name} sets no variables"
        for key, val in w.env.items():
            assert val.startswith("http://127.0.0.1:7777/"), f"{name}.{key} escaped localhost"


def test_the_port_is_honoured():
    assert registry(9123)["claude"].env["ANTHROPIC_BASE_URL"].startswith("http://127.0.0.1:9123/")


def test_an_inherited_variable_is_overridden(monkeypatch):
    """The whole point: whatever the parent exported must not survive into the child."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    env = build_env(registry(7777)["claude"].env)
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:7777/anthropic"


def test_the_rest_of_the_environment_is_preserved(monkeypatch):
    monkeypatch.setenv("SOME_TOKEN", "keep-me")
    env = build_env(registry(7777)["claude"].env)
    assert env["SOME_TOKEN"] == "keep-me"
    assert env["TOKUNSEBA_WRAPPED"] == "1"


def test_wrap_any_exports_every_surface():
    keys = set(full_env(7777))
    assert keys == {"ANTHROPIC_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE",
                    "OLLAMA_HOST", "GOOGLE_GEMINI_BASE_URL"}


def test_codex_sets_both_openai_spellings():
    env = registry(7777)["codex"].env
    assert env["OPENAI_BASE_URL"] == env["OPENAI_API_BASE"]


def test_resolve_is_case_insensitive_and_returns_none_for_unknown():
    assert isinstance(resolve("CLAUDE", 7777), Wrappable)
    assert resolve("nonesuch", 7777) is None


def test_closed_tools_are_named_with_a_reason():
    assert set(UNSUPPORTED) == {"cursor", "copilot", "windsurf"}
    assert all("closed protocol" in why for why in UNSUPPORTED.values())


def test_available_reports_presence(monkeypatch):
    import tokunseba.wrap as w
    monkeypatch.setattr(w.shutil, "which", lambda b: "/bin/x" if b == "claude" else None)
    found = {x.name: present for x, present in available(7777)}
    assert found["claude"] is True and found["aider"] is False


def test_exec_wrapped_reports_a_missing_binary(monkeypatch):
    import tokunseba.wrap as w
    monkeypatch.setattr(w.shutil, "which", lambda _b: None)
    assert exec_wrapped("nope", [], {}) == 127


def test_exec_wrapped_falls_back_when_exec_is_unavailable(monkeypatch):
    import tokunseba.wrap as w
    calls = {}

    def boom(*a, **k):
        raise OSError("exec not permitted")

    class Done:
        returncode = 7

    monkeypatch.setattr(w.shutil, "which", lambda _b: "/bin/tool")
    monkeypatch.setattr(w.os, "execvpe", boom)
    monkeypatch.setattr(w.subprocess, "run", lambda argv, env: calls.setdefault("r", Done()))
    assert exec_wrapped("tool", ["--x"], {"A": "1"}) == 7


# --- the commands ---

def test_wrap_refuses_a_closed_tool(app, home):
    r = run(app, ["wrap", "cursor"])
    assert r.exit_code == 2 and "closed protocol" in r.output


def test_wrap_rejects_an_unknown_tool_and_suggests_wrap_any(app, home):
    r = run(app, ["wrap", "nonesuch"])
    assert r.exit_code == 2 and "wrap-any" in r.output


def test_wrap_reports_a_tool_that_is_not_installed(app, home, monkeypatch):
    import tokunseba.commands_wrap as c
    monkeypatch.setattr(c.shutil, "which", lambda _b: None)
    r = run(app, ["wrap", "claude"])
    assert r.exit_code == 127 and "not on PATH" in r.output


def test_wrap_starts_the_proxy_then_execs(app, home, monkeypatch):
    import tokunseba.commands_wrap as c
    seen = {}
    monkeypatch.setattr(c, "ensure_proxy", lambda cfg, quiet=False: seen.setdefault("started", True))
    monkeypatch.setattr(c.shutil, "which", lambda _b: "/bin/claude")
    monkeypatch.setattr(c, "exec_wrapped",
                        lambda b, a, e: seen.update(binary=b, args=a, env=e) or 0)
    r = run(app, ["wrap", "claude", "--", "--resume"])
    assert r.exit_code == 0
    assert seen["started"] and seen["binary"] == "claude"
    assert seen["env"]["ANTHROPIC_BASE_URL"].startswith("http://127.0.0.1:")


def test_wrap_aborts_when_the_proxy_will_not_start(app, home, monkeypatch):
    import tokunseba.commands_wrap as c
    monkeypatch.setattr(c, "ensure_proxy", lambda cfg, quiet=False: False)
    monkeypatch.setattr(c.shutil, "which", lambda _b: "/bin/claude")
    assert run(app, ["wrap", "claude"]).exit_code == 1


def test_wrappable_lists_tools_and_the_closed_ones(app, home):
    out = run(app, ["wrappable"]).output
    assert "claude" in out and "codex" in out
    assert "cursor" in out and "wrap-any" in out
