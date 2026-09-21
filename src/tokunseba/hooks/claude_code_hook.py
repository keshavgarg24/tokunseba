"""Claude Code hook entry point: session mapping, and no Bash rewriting.

What it does
------------
For every hook event it receives it tells a locally running tokunseba proxy
which Claude Code session is behind the requests it is about to see, so the
dashboard can attribute tokens to a session and a working directory. The post
is best-effort: if no proxy is listening, the hook stays silent and exits 0.

Why Bash rewriting is disabled
------------------------------
Checked https://code.claude.com/docs/en/hooks on 2026-09-22.

* The event name arrives in the field ``hook_event_name``; a ``PreToolUse``
  payload also carries ``tool_name`` and ``tool_input``.
* A ``PreToolUse`` hook modifies a tool's arguments through
  ``hookSpecificOutput.updatedInput``.
* The documentation states verbatim that ``updatedInput`` is **"Only valid when
  ``permissionDecision`` is ``allow``"**, and that ``"allow"`` **"bypasses the
  user's permission prompt for this tool call only"**. The remaining values are
  ``"deny"`` (blocks the call) and ``"abstain"`` (the default: no decision,
  normal permission flow applies) -- neither of which permits ``updatedInput``.

So there is no documented shape that rewrites a Bash command while still
letting the user's own permission prompt run. Rewriting every Bash command to
``tokunseba run -- ...`` would therefore also auto-approve every Bash command
Claude Code wanted to execute, silently removing the user's last chance to
refuse a destructive one. Saving tokens is not worth that trade, so the rewrite
is deliberately not implemented: on ``PreToolUse`` this hook prints nothing and
exits 0, leaving the permission flow untouched.

``cfg.rewrite_bash`` consequently has no effect here. To get the same savings
safely, invoke ``tokunseba run -- <command>`` explicitly, or route the tool
results through the proxy.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import httpx

from .. import config

__all__ = ["BASH_REWRITE_SUPPORTED", "main"]

#: Whether the hooks API offers a way to rewrite tool input without also
#: auto-approving the tool call. Determined from the documentation on
#: 2026-09-22; see the module docstring. While this is False the hook never
#: emits a rewrite.
BASH_REWRITE_SUPPORTED: bool = False

_SESSION_PATH = "/_tokunseba/api/session"
_POST_TIMEOUT = 0.3


def main(argv: list[str] | None = None) -> int:
    """Read one hook event from stdin and report its session to the proxy.

    Always returns 0 and, by design, never writes to stdout: a hook that fails
    must not be able to disturb the session that invoked it.
    """
    try:
        event: Any = json.loads(sys.stdin.read())
    except (ValueError, TypeError):
        return 0
    if not isinstance(event, dict):
        return 0

    _report_session(event)

    # No rewrite branch: see the module docstring for why.
    return 0


def _report_session(event: dict[str, Any]) -> None:
    """Best-effort announcement of this session to a local proxy."""
    try:
        port = config.load().port
        httpx.post(
            f"http://127.0.0.1:{port}{_SESSION_PATH}",
            json={
                "session_id": event.get("session_id"),
                "cwd": event.get("cwd"),
                "tool": "claude-code",
            },
            timeout=_POST_TIMEOUT,
        )
    except Exception:
        # A missing proxy, an unreadable config, a timeout: none of them are
        # this hook's problem, and none may surface to the caller.
        pass


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
