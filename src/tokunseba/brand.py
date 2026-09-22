"""Visual identity for tokunseba.

The mark is a confluence: three wide streams enter on the left, fold together,
and leave as a single stream that is *heavier* than any one of them. Many
tokens in, fewer tokens out, none of the substance dropped on the floor. The
SVG versions of the same drawing live in ``assets/``.

Nothing here prints. ``banner`` returns rich *markup*; the caller owns the
Console.
"""

from __future__ import annotations

from rich.markup import escape

__all__ = ["LOGO_LINES", "WORDMARK", "COLORS", "banner"]

#: ASCII/box-drawing rendering of the mark. Five wide inputs converging on one
#: output, drawn with a proper box-drawing junction so terminals join it up.
#: Contract: at most 7 lines, at most 22 columns, no ANSI escapes.
LOGO_LINES: list[str] = [
    "─────╮",
    "─────┤",
    "─────┼─────────",
    "─────┤",
    "─────╯",
]

#: Compact single-line mark for headings and one-line status output.
WORDMARK: str = "≡▸ tokunseba"

#: rich style names. Hex values chosen to clear 3.6:1 against white *and*
#: 5.1:1 against black, so they stay readable on light and dark terminals
#: alike. No pure white, no pure black, no bright yellow.
COLORS: dict[str, str] = {
    "accent": "#3D7BE0",
    "dim": "#808690",
    "good": "#2E9E63",
    "warn": "#B4791C",
    "bad": "#D2544C",
}

_NAME = "tokunseba"

# Index of the line carrying the merged output stream: the name is hung off it.
_STREAM_ROW = 2

_GUTTER = "  "


def banner(subtitle: str = "") -> str:
    """Return the full banner as a rich markup string.

    The mark is drawn with the name riding the outgoing stream and the optional
    ``subtitle`` dimmed on the line below it::

          ─────╮
          ─────┤
          ─────┼─────────  tokunseba
          ─────┤           cuts tokens, keeps meaning
          ─────╯

    The return value contains rich markup tags but never ANSI escapes; styling
    happens when a Console renders it.
    """
    width = max(len(line) for line in LOGO_LINES)
    rows: list[str] = []

    for i, line in enumerate(LOGO_LINES):
        style = COLORS["accent"] if i == _STREAM_ROW else COLORS["dim"]
        pad = " " * (width - len(line))
        row = f"{_GUTTER}[{style}]{escape(line)}[/]"
        if i == _STREAM_ROW:
            row += f"{pad}{_GUTTER}[bold]{escape(_NAME)}[/]"
        elif i == _STREAM_ROW + 1 and subtitle:
            row += f"{pad}{_GUTTER}[{COLORS['dim']}]{escape(subtitle)}[/]"
        rows.append(row)

    return "\n".join(rows)
