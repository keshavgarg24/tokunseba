"""Lossless canonicalization of tool output.

Every rule here removes characters that carry no meaning (escape sequences,
overwritten progress-bar frames, trailing whitespace) or replaces exact
duplication with an explicit, machine-readable marker.  Reading the output must
never leave a reader with a different understanding than reading the input.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator

__all__ = ["canonicalize"]

# `ESC [ ... final` (CSI: colours, cursor moves) and `ESC ] ... BEL/ST` (OSC:
# window titles, hyperlinks).
_ANSI_CSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_ANSI_OSC = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)")

# Absolute POSIX paths with at least two directory components.
_PATH = re.compile(r"/(?:[\w.@+-]+/){2,}[\w.@+-]*")

_ROOT_ALIAS = "$ROOT"
_MAX_BLANK_RUN = 2
_MIN_REPEAT_RUN = 3
_MIN_ROOT_SEGMENTS = 3
_MIN_ROOT_OCCURRENCES = 3


def canonicalize(text: str) -> str:
    """Return `text` with meaning-preserving noise removed.

    A trailing newline in the input is preserved in the output; the empty
    string maps to the empty string.
    """
    if not text:
        return ""

    ends_with_newline = text.endswith("\n")
    body = text[:-1] if ends_with_newline else text

    body = _ANSI_OSC.sub("", _ANSI_CSI.sub("", body))
    lines = [_after_last_carriage_return(line).rstrip() for line in body.split("\n")]
    lines = _collapse_blank_runs(lines)
    lines = _collapse_repeated_lines(lines)

    result = _alias_root("\n".join(lines))
    return result + "\n" if ends_with_newline else result


def _after_last_carriage_return(line: str) -> str:
    """Keep only what a terminal would still show after in-line redraws."""
    return line.rpartition("\r")[2] if "\r" in line else line


def _collapse_blank_runs(lines: list[str]) -> list[str]:
    kept: list[str] = []
    blanks = 0
    for line in lines:
        if line:
            blanks = 0
            kept.append(line)
            continue
        blanks += 1
        if blanks <= _MAX_BLANK_RUN:
            kept.append(line)
    return kept


def _collapse_repeated_lines(lines: list[str]) -> list[str]:
    kept: list[str] = []
    start = 0
    total = len(lines)
    while start < total:
        line = lines[start]
        end = start + 1
        if line:
            while end < total and lines[end] == line:
                end += 1
        run = end - start
        if line and run >= _MIN_REPEAT_RUN:
            kept.append(line)
            kept.append(f"[tokunseba: previous line repeated {run - 1} more times]")
        else:
            kept.extend(lines[start:end])
        start = end
    return kept


def _ancestors(directory: str) -> Iterator[str]:
    """Yield every prefix of `directory` that has at least 3 path segments."""
    segments = [segment for segment in directory.split("/") if segment]
    for size in range(_MIN_ROOT_SEGMENTS, len(segments) + 1):
        yield "/" + "/".join(segments[:size])


def _alias_root(text: str) -> str:
    candidates = _PATH.findall(text)
    if not candidates:
        return text

    counts: Counter[str] = Counter()
    for candidate in candidates:
        directory = candidate.rpartition("/")[0]
        counts.update(_ancestors(directory))

    frequent = [
        prefix for prefix, count in counts.items() if count >= _MIN_ROOT_OCCURRENCES
    ]
    if not frequent:
        return text

    root = max(frequent, key=lambda prefix: (len(prefix), prefix))
    occurrences = text.count(root)
    saved = occurrences * (len(root) - len(_ROOT_ALIAS))
    # The declaration line has to spell the root out once, so the substitutions
    # must recoup at least that much before aliasing is worth doing.
    if saved <= len(root):
        return text

    banner = f"[tokunseba: {_ROOT_ALIAS} = {root}]"
    return f"{banner}\n{text.replace(root, _ROOT_ALIAS)}"
