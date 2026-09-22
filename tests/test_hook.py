"""Tests for the Claude Code hook and the optional MCP server."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from tokunseba import config
from tokunseba.hooks import claude_code_hook, mcp_server

SESSION_URL = "http://127.0.0.1:7777/_tokunseba/api/session"


@pytest.fixture
def posts(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record every httpx.post the hook makes instead of performing it."""
    recorded: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> None:
        recorded.append({"url": url, **kwargs})

    monkeypatch.setattr(claude_code_hook.httpx, "post", fake_post)
    return recorded


def _feed(monkeypatch: pytest.MonkeyPatch, payload: Any) -> None:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))


def test_session_start_posts_the_session_mapping(
    home: Path, posts: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _feed(
        monkeypatch,
        {"hook_event_name": "SessionStart", "session_id": "abc123", "cwd": "/w/proj"},
    )

    assert claude_code_hook.main() == 0
    assert capsys.readouterr().out == ""
    assert len(posts) == 1
    assert posts[0]["url"] == SESSION_URL
    assert posts[0]["json"] == {
        "session_id": "abc123",
        "cwd": "/w/proj",
        "tool": "claude-code",
    }
    assert posts[0]["timeout"] == 0.3


def test_user_prompt_submit_posts_too(
    home: Path, posts: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _feed(
        monkeypatch,
        {"hook_event_name": "UserPromptSubmit", "session_id": "s2", "cwd": "/w/other"},
    )

    assert claude_code_hook.main() == 0
    assert capsys.readouterr().out == ""
    assert [p["json"]["session_id"] for p in posts] == ["s2"]


def test_pre_tool_use_bash_prints_nothing_when_rewrite_disabled(
    home: Path, posts: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config.save(config.Config())
    _feed(
        monkeypatch,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s3",
            "cwd": "/w/proj",
            "tool_name": "Bash",
            "tool_input": {"command": "npm test"},
        },
    )

    assert claude_code_hook.main() == 0
    assert capsys.readouterr().out == ""
    assert len(posts) == 1


def test_pre_tool_use_bash_prints_nothing_even_when_rewrite_enabled(
    home: Path, posts: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rewriting needs permissionDecision "allow", so it is never emitted.

    See the claude_code_hook module docstring: the hooks documentation (checked
    2026-09-22) only accepts ``updatedInput`` alongside ``permissionDecision:
    "allow"``, which bypasses the user's permission prompt. tokunseba therefore
    declines to rewrite at all, so there is no setting that could enable it.
    """
    config.save(config.Config())
    assert claude_code_hook.BASH_REWRITE_SUPPORTED is False

    _feed(
        monkeypatch,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s4",
            "cwd": "/w/proj",
            "tool_name": "Bash",
            "tool_input": {"command": "npm test"},
        },
    )

    assert claude_code_hook.main() == 0
    assert capsys.readouterr().out == ""
    assert len(posts) == 1


def test_malformed_stdin_exits_zero_silently(
    home: Path, posts: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _feed(monkeypatch, "{not json at all")

    assert claude_code_hook.main() == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert posts == []


def test_non_object_stdin_exits_zero_silently(
    home: Path, posts: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _feed(monkeypatch, "[1, 2, 3]")

    assert claude_code_hook.main() == 0
    assert capsys.readouterr().out == ""
    assert posts == []


def test_failing_post_does_not_raise(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(url: str, **kwargs: Any) -> None:
        raise RuntimeError("no proxy listening")

    monkeypatch.setattr(claude_code_hook.httpx, "post", boom)
    _feed(monkeypatch, {"hook_event_name": "SessionStart", "session_id": "s5"})

    assert claude_code_hook.main() == 0
    assert capsys.readouterr().out == ""


def test_port_from_config_is_used(
    home: Path, posts: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    config.save(config.Config(port=9123))
    _feed(monkeypatch, {"hook_event_name": "SessionStart", "session_id": "s6"})

    assert claude_code_hook.main() == 0
    assert posts[0]["url"] == "http://127.0.0.1:9123/_tokunseba/api/session"


def test_build_server_either_builds_or_needs_the_extra(home: Path) -> None:
    pytest.importorskip("mcp", reason="the mcp extra is not installed")
    server = mcp_server.build_server()
    assert server is not None


def test_main_returns_2_when_mcp_is_missing(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A None entry in sys.modules makes `import mcp` raise ImportError, but a submodule
    # already imported elsewhere in the run would still resolve directly, so blank those too.
    import sys
    for name in [m for m in list(sys.modules) if m == "mcp" or m.startswith("mcp.")]:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setitem(sys.modules, "mcp", None)

    assert mcp_server.main() == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == mcp_server.INSTALL_HINT
    assert captured.out == ""
