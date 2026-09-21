"""Second reads of the same file, and re-reads after an edit, do not need to be re-sent in full."""
from __future__ import annotations

import difflib

from ..protocols.base import Block, NormalizedRequest, sha256_text

PATH_KEYS = ("file_path", "path", "target_file", "filename", "file", "notebook_path")


def _path_of(norm: NormalizedRequest, block: Block) -> str | None:
    if not block.tool_use_id:
        return None
    tu = norm.tool_use_index.get(block.tool_use_id)
    if not tu or not isinstance(tu.tool_input, dict):
        return None
    for k in PATH_KEYS:
        v = tu.tool_input.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def find_reference(norm: NormalizedRequest, upto: int, sha: str) -> tuple[int, str] | None:
    """An earlier tool result with byte-identical content."""
    for i in range(upto):
        for b in norm.messages[i].blocks:
            if b.kind == "tool_result" and b.text and sha256_text(b.text) == sha:
                return i, sha
    return None


def find_reread(norm: NormalizedRequest, upto: int, block: Block) -> tuple[int, str, str] | None:
    """The most recent earlier read of the same path with different content."""
    path = _path_of(norm, block)
    if not path or not block.text:
        return None
    for i in range(upto - 1, -1, -1):
        for b in norm.messages[i].blocks:
            if b.kind != "tool_result" or not b.text or b.text == block.text:
                continue
            if _path_of(norm, b) == path:
                return i, sha256_text(b.text), b.text
    return None


def reference_text(index: int, handle: str) -> str:
    return (f"[tokunseba: identical to the tool result in message {index} ({handle}). "
            f"Full output: run `tokunseba expand {handle}`]")


def make_diff(earlier: str, current: str, path: str, index: int, handle: str) -> str | None:
    """Return a unified diff, but only when it is meaningfully smaller than the full text."""
    diff = "\n".join(difflib.unified_diff(
        earlier.splitlines(), current.splitlines(),
        fromfile=f"message {index}", tofile="now", lineterm="", n=2))
    if not diff or len(diff) >= len(current) * 0.6:
        return None
    header = (f"[tokunseba: {path} changed since message {index}; unified diff against that version "
              f"follows. Full file: run `tokunseba expand {handle}`]")
    return header + "\n" + diff


def path_of(norm: NormalizedRequest, block: Block) -> str | None:
    return _path_of(norm, block)
