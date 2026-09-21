"""Detect low-signal payloads and replace them with a compact summary."""

from __future__ import annotations

import json
import os

__all__ = ["detect", "summary"]

_LOCKFILE_NAMES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "Cargo.lock",
        "poetry.lock",
        "uv.lock",
        "Gemfile.lock",
        "composer.lock",
        "go.sum",
    }
)

_GENERATED_MARKERS = (
    "/node_modules/",
    "/dist/",
    "/build/",
    "/.git/",
    "/__pycache__/",
    "/.next/",
    "/vendor/",
)

_MINIFIED_SUFFIXES = (".min.js", ".min.css", ".map")

_BINARY_SAMPLE = 4000
_BINARY_RATIO = 0.05
_TEXT_CONTROL = frozenset("\t\n\r")

_MIN_MINIFIED_LINES = 5
_MAX_MEAN_LINE_LENGTH = 1000

_PREVIEW_LINES = 20
_LOCKFILE_SECTIONS = ("packages", "dependencies")
_MAX_SAMPLE_NAMES = 10


def detect(path: str | None, text: str) -> str | None:
    """Classify `text` as junk, returning the label or None if it looks useful."""
    if _is_binary(text):
        return "binary"

    if path is not None:
        if os.path.basename(path) in _LOCKFILE_NAMES:
            return "lockfile"
        if any(marker in path for marker in _GENERATED_MARKERS):
            return "generated"
        if path.endswith(_MINIFIED_SUFFIXES):
            return "minified"

    if _has_minified_shape(text):
        return "minified"
    return None


def summary(label: str, path: str | None, text: str, handle: str) -> str:
    """Render a short stand-in for `text`, always under 40 lines."""
    name = os.path.basename(path) if path else "content"
    lines = [f"[tokunseba: {name} ({label}) replaced with a summary]"]
    lines.extend(_lockfile_lines(label, text) or _preview_lines(text))
    lines.append(
        "[tokunseba: full content omitted. "
        f"Full output: run `tokunseba expand {handle}`]"
    )
    return "\n".join(lines)


def _is_binary(text: str) -> bool:
    sample = text[:_BINARY_SAMPLE]
    if not sample:
        return False
    control = sum(
        1 for char in sample if ord(char) < 32 and char not in _TEXT_CONTROL
    )
    return control > len(sample) * _BINARY_RATIO


def _has_minified_shape(text: str) -> bool:
    lines = text.split("\n")
    if len(lines) < _MIN_MINIFIED_LINES:
        return False
    mean_length = sum(len(line) for line in lines) / len(lines)
    return mean_length > _MAX_MEAN_LINE_LENGTH


def _lockfile_lines(label: str, text: str) -> list[str] | None:
    """Structured digest of a JSON lockfile, or None if it is not one."""
    if label != "lockfile":
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    lines = [f"top-level keys: {', '.join(sorted(data))}"]
    sections: list[dict[str, object]] = []
    for key in _LOCKFILE_SECTIONS:
        value = data.get(key)
        if isinstance(value, dict):
            sections.append(value)
            lines.append(f"{key}: {len(value)} entries")

    if sections:
        largest = max(sections, key=len)
        names = list(largest)[:_MAX_SAMPLE_NAMES]
        if names:
            lines.append(f"sample: {', '.join(names)}")
    return lines


def _preview_lines(text: str) -> list[str]:
    return text.splitlines()[:_PREVIEW_LINES]
