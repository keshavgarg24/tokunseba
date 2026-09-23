"""Detect the shape of tool output and summarize it without losing failures.

Two stages:

1. :func:`detect_type` classifies a blob of tool output into one of :data:`LABELS`.
   Classification is quick regex/heuristic work; an optional :data:`tie_breaker`
   hook can be consulted when the regex verdict is weak.
2. :func:`summarize` applies a per-label reduction that keeps the lines a human
   (or a model) actually needs -- failures, errors, summary counts -- and drops
   the repetitive noise around them.

Every rule is failure-preserving: a line that names a failure or an error is
never dropped, and the number of dropped lines is always reported so callers can
show an honest "N lines omitted" hint.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Final

__all__ = ["LABELS", "detect_type", "detect_type_regex_only", "summarize", "tie_breaker"]

#: Optional escalation hook. When set, it is called only for low-confidence
#: regex verdicts and may return ``(label, confidence)`` or ``None``.
tie_breaker: Callable[[str], tuple[str, float] | None] | None = None

LABELS: Final[tuple[str, ...]] = (
    "pytest",
    "jest",
    "cargo_test",
    "go_test",
    "install_log",
    "git_diff",
    "listing",
    "stack_trace",
    "json",
    "source",
    "generic",
)

_SOURCE_TOOLS: Final[frozenset[str]] = frozenset(
    {"read", "read_file", "view_file", "cat", "str_replace_based_edit_tool"}
)

_M = re.MULTILINE

# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #

_SIGNALS: Final[dict[str, tuple[re.Pattern[str], ...]]] = {
    "pytest": (
        re.compile(r"^=+ .*(passed|failed|error).* =+$", _M),
        re.compile(r"^(FAILED|ERROR) ", _M),
        re.compile(r"collected \d+ items?", _M),
        re.compile(r"^_{3,} .+ _{3,}$", _M),
    ),
    "jest": (
        re.compile(r"^Tests:\s+\d+", _M),
        re.compile(r"^Test Suites:", _M),
        re.compile(r"^\s+[✓✕●] ", _M),
    ),
    "cargo_test": (
        re.compile(r"^test result: ", _M),
        re.compile(r"^running \d+ tests?", _M),
        re.compile(r"^test .+ \.\.\. (ok|FAILED)$", _M),
    ),
    "go_test": (
        re.compile(r"^--- (PASS|FAIL): ", _M),
        re.compile(r"^(ok|FAIL)\s+\S+\s+[\d.]+s", _M),
        re.compile(r"^=== RUN ", _M),
    ),
    "install_log": (
        re.compile(r"npm (WARN|ERR!?)", _M),
        re.compile(r"added \d+ packages", _M),
        re.compile(r"Successfully installed", _M),
        re.compile(r"^Collecting ", _M),
        re.compile(r"Resolved \d+ packages", _M),
    ),
    "git_diff": (
        re.compile(r"^diff --git ", _M),
        re.compile(r"^@@ .* @@", _M),
    ),
    "stack_trace": (
        re.compile(r"^\s+at .+\(.+:\d+:\d+\)$", _M),
        re.compile(r'^\s+File ".+", line \d+', _M),
        re.compile(r"^Traceback \(most recent call last\)", _M),
    ),
}

_LISTING_NAME_RE: Final = re.compile(r"^[\w./@~-]+$")
_LISTING_LS_RE: Final = re.compile(r"^[d-][rwx-]{9}\s")

_CMD_INSTALL_RE: Final = re.compile(
    r"npm (i|install|ci)\b|pip install|uv (sync|pip)|yarn add|pnpm (i|install|add)"
)
_CMD_LISTING_RE: Final = re.compile(r"^\s*(ls|find|tree)\b")

_COMMAND_CONFIDENCE: Final = 0.95
_TIE_BREAK_THRESHOLD: Final = 0.6


def _command_override(command: str) -> str | None:
    """Return a label implied by the command line itself, if any."""
    if "pytest" in command:
        return "pytest"
    if "jest" in command or "vitest" in command:
        return "jest"
    if "cargo test" in command:
        return "cargo_test"
    if "go test" in command:
        return "go_test"
    if _CMD_INSTALL_RE.search(command):
        return "install_log"
    if "git diff" in command:
        return "git_diff"
    if _CMD_LISTING_RE.search(command):
        return "listing"
    return None


def detect_type_regex_only(
    text: str, tool_name: str | None, command: str | None
) -> tuple[str, float]:
    """Classify ``text`` using only regexes and quick heuristics.

    The command line wins outright when it is recognizable. Otherwise each label
    scores one point per matching signal, and the confidence of the winner is
    ``score / (score + 1)``.
    """
    if command:
        label = _command_override(command)
        if label is not None:
            return (label, _COMMAND_CONFIDENCE)

    scores: dict[str, int] = dict.fromkeys(LABELS, 0)
    for label, patterns in _SIGNALS.items():
        scores[label] = sum(1 for pattern in patterns if pattern.search(text))

    non_empty = [line for line in text.splitlines() if line.strip()]
    if non_empty:
        listing_like = sum(
            1
            for line in non_empty
            if _LISTING_NAME_RE.match(line) or _LISTING_LS_RE.match(line)
        )
        if listing_like / len(non_empty) > 0.70:
            scores["listing"] = 3

    stripped = text.strip()
    if stripped:
        try:
            json.loads(stripped)
        except (ValueError, TypeError):
            pass
        else:
            scores["json"] = 3

    if (
        tool_name
        and tool_name.lower() in _SOURCE_TOOLS
        and all(value == 0 for value in scores.values())
    ):
        scores["source"] = 2

    winner = max(LABELS, key=lambda label: scores[label])
    top = scores[winner]
    if top <= 0:
        return ("generic", 0.0)
    return (winner, top / (top + 1))


def detect_type(text: str, tool_name: str | None, command: str | None) -> tuple[str, float]:
    """Classify ``text``, escalating to :data:`tie_breaker` when unsure."""
    label, confidence = detect_type_regex_only(text, tool_name, command)
    if confidence >= _TIE_BREAK_THRESHOLD or tie_breaker is None:
        return (label, confidence)

    verdict = tie_breaker(text)
    if isinstance(verdict, tuple) and len(verdict) == 2:
        candidate, candidate_confidence = verdict
        if candidate in LABELS:
            return (str(candidate), float(candidate_confidence))
    return (label, confidence)


# --------------------------------------------------------------------------- #
# Summarization
# --------------------------------------------------------------------------- #

# A line matching this is never dropped by the whitelist test-runner rules.
_FAILURE_HINT_RE: Final = re.compile(r"FAILED|FAIL\b|ERROR|[Ee]rror|Traceback|panic:|Exception")

_PY_SECTION_RE: Final = re.compile(r"^_{3,} .+ _{3,}$")
_PY_COLLECTED_RE: Final = re.compile(r"collected \d+ items?")
_PY_PROGRESS_RE: Final = re.compile(r"^\S+\.py[\s:]+[.FsxE]+")
_PY_FINAL_RE: Final = re.compile(r"^=+ .* =+$")
_PY_SECTION_CAP: Final = 40

_JEST_SUITES_RE: Final = re.compile(r"^Test Suites:")
_JEST_SUMMARY_RE: Final = re.compile(r"^(Test Suites:|Tests:|Snapshots:|Time:|Ran all)")
_JEST_PASS_RE: Final = re.compile(r"^PASS ")

_CARGO_FAILED_RE: Final = re.compile(r"^test .+ \.\.\. FAILED$")
_CARGO_OK_RE: Final = re.compile(r"^test .+ \.\.\. ok$")
_CARGO_RUNNING_RE: Final = re.compile(r"^running \d+ tests?$")
_CARGO_FAILURES_RE: Final = re.compile(r"^failures:$")
_CARGO_RESULT_RE: Final = re.compile(r"^test result:")

_GO_PKG_RE: Final = re.compile(r"^(FAIL|ok)\s+\S+")
_GO_RUN_RE: Final = re.compile(r"^=== RUN ")
_GO_PASS_RE: Final = re.compile(r"^(--- PASS|PASS$)")
_GO_PANIC_TAIL: Final = 10

_INSTALL_KEEP_RE: Final = re.compile(
    r"WARN|ERR|error|warning|deprecat|vulnerab", re.IGNORECASE
)
_INSTALL_TAIL: Final = 3

_DIFF_HEADER_RE: Final = re.compile(r"^diff --git ")
_DIFF_FILE_CAP: Final = 80

_LISTING_CAP: Final = 150

_FRAME_RE: Final = re.compile(r'^\s+at |^\s+File "')
_FRAME_EDGE: Final = 6

# A rule reports which line indices to keep, plus markers to emit after a line.
_Plan = tuple[set[int], dict[int, str]]


def _keep_failure_lines(
    lines: list[str], keep: set[int], forbidden: set[int], skip: re.Pattern[str] | None
) -> None:
    """Re-add any line that names a failure, unless it was explicitly dropped."""
    for index, line in enumerate(lines):
        if index in keep or index in forbidden or not line.strip():
            continue
        if skip is not None and skip.search(line):
            continue
        if _FAILURE_HINT_RE.search(line):
            keep.add(index)


def _plan_pytest(lines: list[str]) -> _Plan:
    keep: set[int] = set()
    markers: dict[int, str] = {}
    total = len(lines)

    headers = [i for i, line in enumerate(lines) if _PY_SECTION_RE.match(line)]
    summary_starts = [i for i, line in enumerate(lines) if "short test summary" in line]
    truncated: set[int] = set()

    for position, start in enumerate(headers):
        end = headers[position + 1] if position + 1 < len(headers) else total
        for index in summary_starts:
            if start < index < end:
                end = index
                break
        length = end - start
        if length > _PY_SECTION_CAP:
            keep.update(range(start, start + _PY_SECTION_CAP))
            truncated.update(range(start + _PY_SECTION_CAP, end))
            markers[start + _PY_SECTION_CAP - 1] = (
                f"[... {length - _PY_SECTION_CAP} lines of this section omitted]"
            )
        else:
            keep.update(range(start, end))

    for index, line in enumerate(lines):
        if line.startswith(("FAILED ", "ERROR ")):
            keep.add(index)
        elif _PY_COLLECTED_RE.search(line):
            keep.add(index)

    final = [i for i, line in enumerate(lines) if _PY_FINAL_RE.match(line)]
    if final:
        keep.add(final[-1])

    forbidden = truncated | {
        i for i, line in enumerate(lines) if _PY_PROGRESS_RE.match(line)
    }
    _keep_failure_lines(lines, keep, forbidden, None)
    return keep, markers


def _plan_jest(lines: list[str]) -> _Plan:
    keep: set[int] = set()
    total = len(lines)

    bullets = [i for i, line in enumerate(lines) if line.strip().startswith("●")]
    stops = sorted(
        set(bullets) | {i for i, line in enumerate(lines) if _JEST_SUITES_RE.match(line)}
    )

    for start in bullets:
        end = total
        for index in stops:
            if index > start:
                end = index
                break
        keep.update(range(start, end))

    for index, line in enumerate(lines):
        if _JEST_SUMMARY_RE.match(line):
            keep.add(index)

    forbidden = {
        i
        for i, line in enumerate(lines)
        if line.strip().startswith("✓") or _JEST_PASS_RE.match(line)
    }
    _keep_failure_lines(lines, keep, forbidden, None)
    return keep, {}


def _plan_cargo(lines: list[str]) -> _Plan:
    keep: set[int] = set()

    for index, line in enumerate(lines):
        if _CARGO_FAILED_RE.match(line) or _CARGO_RESULT_RE.match(line):
            keep.add(index)

    failures = next(
        (i for i, line in enumerate(lines) if _CARGO_FAILURES_RE.match(line)), None
    )
    if failures is not None:
        result = next(
            (
                i
                for i, line in enumerate(lines)
                if i > failures and _CARGO_RESULT_RE.match(line)
            ),
            len(lines) - 1,
        )
        keep.update(range(failures, result + 1))

    forbidden = {
        i
        for i, line in enumerate(lines)
        if _CARGO_OK_RE.match(line) or _CARGO_RUNNING_RE.match(line)
    }
    _keep_failure_lines(lines, keep, forbidden, None)
    return keep, {}


def _plan_go(lines: list[str]) -> _Plan:
    keep: set[int] = set()
    total = len(lines)

    for index, line in enumerate(lines):
        if line.startswith("--- FAIL"):
            keep.add(index)
            follower = index + 1
            while follower < total and lines[follower][:1] in (" ", "\t"):
                keep.add(follower)
                follower += 1
        elif _GO_PKG_RE.match(line):
            keep.add(index)
        elif line.startswith("panic:"):
            keep.update(range(index, min(total, index + _GO_PANIC_TAIL + 1)))

    forbidden = {
        i
        for i, line in enumerate(lines)
        if _GO_RUN_RE.match(line) or _GO_PASS_RE.match(line)
    }
    _keep_failure_lines(lines, keep, forbidden, None)
    return keep, {}


def _plan_install(lines: list[str]) -> _Plan:
    keep = {i for i, line in enumerate(lines) if _INSTALL_KEEP_RE.search(line)}
    keep.update(range(max(0, len(lines) - _INSTALL_TAIL), len(lines)))
    return keep, {}


def _plan_git_diff(lines: list[str]) -> _Plan:
    headers = [i for i, line in enumerate(lines) if _DIFF_HEADER_RE.match(line)]
    if not headers:
        return set(range(len(lines))), {}

    keep: set[int] = set(range(headers[0]))
    markers: dict[int, str] = {}
    for position, start in enumerate(headers):
        end = headers[position + 1] if position + 1 < len(headers) else len(lines)
        body = end - start - 1
        keep.add(start)
        kept_body = min(body, _DIFF_FILE_CAP)
        keep.update(range(start + 1, start + 1 + kept_body))
        if body > _DIFF_FILE_CAP:
            markers[start + kept_body] = (
                f"[... {body - _DIFF_FILE_CAP} more lines in this file omitted]"
            )
    return keep, markers


def _plan_listing(lines: list[str]) -> _Plan:
    return set(range(min(len(lines), _LISTING_CAP))), {}


def _plan_stack_trace(lines: list[str]) -> _Plan:
    frames = [i for i, line in enumerate(lines) if _FRAME_RE.match(line)]
    keep = {i for i in range(len(lines)) if i not in set(frames)}
    keep.update(frames[:_FRAME_EDGE])
    keep.update(frames[-_FRAME_EDGE:])

    dropped = [i for i in frames if i not in keep]
    markers: dict[int, str] = {}
    if dropped:
        markers[frames[_FRAME_EDGE - 1]] = f"[... {len(dropped)} frames omitted]"
    return keep, markers


_PLANNERS: Final[dict[str, Callable[[list[str]], _Plan]]] = {
    "pytest": _plan_pytest,
    "jest": _plan_jest,
    "cargo_test": _plan_cargo,
    "go_test": _plan_go,
    "install_log": _plan_install,
    "git_diff": _plan_git_diff,
    "listing": _plan_listing,
    "stack_trace": _plan_stack_trace,
}


def summarize(label: str, text: str) -> tuple[str, int]:
    """Reduce ``text`` according to ``label``.

    Returns ``(kept_text, omitted_line_count)``. The count never includes the
    inserted ``[... N ... omitted]`` markers, and is ``0`` -- with ``text``
    returned verbatim -- whenever the rule would have kept everything.
    """
    planner = _PLANNERS.get(label)
    if planner is None:
        return (text, 0)

    lines = text.splitlines()
    if not lines:
        return (text, 0)

    keep, markers = planner(lines)

    out: list[str] = []
    kept = 0
    for index, line in enumerate(lines):
        if index in keep:
            out.append(line)
            kept += 1
        marker = markers.get(index)
        if marker is not None:
            out.append(marker)

    omitted = len(lines) - kept
    if omitted <= 0:
        return (text, 0)
    return ("\n".join(out), omitted)
