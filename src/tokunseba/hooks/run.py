"""Run a shell command and print its output already compressed.

This is the no-proxy path: any agent that can call a shell gets the same
canonicalization, summarization and handle-backed truncation that the proxy
applies to tool results, simply by prefixing its command with ``tokunseba run``.

Nothing is ever destroyed. Whatever is dropped from the visible output is
stored verbatim in the handle store and can be recovered with
``tokunseba expand <handle>`` -- unless it contains a detected secret, in which
case it is neither shown nor stored.
"""

from __future__ import annotations

import subprocess

from ..config import Config
from ..guards import secrets
from ..tokens.estimator import Estimator
from ..transform.canonical import canonicalize
from ..transform.handles import HandleStore
from ..transform.summarize import detect_type, summarize

__all__ = ["run_command"]

_NOT_FOUND_CODE = 127

#: Share of the line budget spent on the head of a capped output. The tail gets
#: the rest, because the end of a long run (the failure, the summary) usually
#: matters more per line than its middle.
_HEAD_SHARE = 0.60


def run_command(
    argv: list[str],
    cfg: Config,
    handles: HandleStore,
    estimator: Estimator,
) -> tuple[str, int]:
    """Execute ``argv`` and return ``(compressed_output, returncode)``.

    A single-element ``argv`` is run through the shell so that pipes and
    redirections keep working; anything longer is executed directly, without a
    shell, so no quoting rules apply to the arguments.

    Never raises: a missing executable is reported as text with exit code 127.
    """
    if not argv:
        return ("", 0)

    try:
        if len(argv) == 1:
            proc = subprocess.run(argv[0], shell=True, capture_output=True, text=True)
        else:
            proc = subprocess.run(argv, shell=False, capture_output=True, text=True)
    except FileNotFoundError:
        return (f"tokunseba: command not found: {argv[0]}", _NOT_FOUND_CODE)

    original = _merge(proc.stdout, proc.stderr)
    command = " ".join(argv)

    text = canonicalize(original)
    label, _confidence = detect_type(text, None, command)
    kept, omitted = summarize(label, text)

    if omitted > 0:
        kept = f"{kept}\n{_footer(original, kept, omitted, handles, estimator)}"

    return (_cap(kept, original, cfg, handles, estimator), proc.returncode)


def _merge(stdout: str, stderr: str) -> str:
    """Concatenate the two streams, keeping stdout first."""
    if stdout and stderr:
        return f"{stdout}\n{stderr}"
    return stdout + stderr


def _footer(
    original: str,
    kept: str,
    omitted_lines: int,
    handles: HandleStore,
    estimator: Estimator,
) -> str:
    """Store ``original`` behind a handle and describe what was dropped.

    When ``original`` looks like it contains a credential nothing is written to
    disk at all, and the footer says so instead of offering a handle.
    """
    if secrets.has_secret(original):
        return HandleStore.blocked_footer()

    handle = handles.put(original)
    omitted_tokens = max(
        0,
        estimator.count(original, "anthropic", "")
        - estimator.count(kept, "anthropic", ""),
    )
    return HandleStore.footer(handle, omitted_lines, omitted_tokens)


def _cap(
    text: str,
    original: str,
    cfg: Config,
    handles: HandleStore,
    estimator: Estimator,
) -> str:
    """Clamp ``text`` to the configured line budget, head and tail preserved."""
    budget = cfg.thresholds.truncate_lines
    lines = text.splitlines()
    if budget <= 0 or len(lines) <= budget:
        return text

    head = int(budget * _HEAD_SHARE)
    tail = budget - head
    kept_lines = lines[:head] + (lines[-tail:] if tail > 0 else [])
    omitted = len(lines) - len(kept_lines)

    footer = _footer(original, "\n".join(kept_lines), omitted, handles, estimator)
    return "\n".join(lines[:head] + [footer] + (lines[-tail:] if tail > 0 else []))
