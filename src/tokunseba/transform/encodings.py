"""Pick the cheapest faithful encoding for a payload."""

from __future__ import annotations

import json
from collections.abc import Callable

__all__ = ["best"]

_MIN_ROWS = 5
_SAVING_RATIO = 0.85


def best(text: str, count_fn: Callable[[str], int]) -> tuple[str, str]:
    """Return (chosen_text, kind) where kind is "table" or "none".

    A uniform JSON array of flat objects is re-rendered as a tab-separated
    table when that saves at least 15% of the tokens reported by `count_fn`.
    """
    rows = _tabular_rows(text)
    if rows is None:
        return text, "none"

    table = _render_table(rows)
    if count_fn(table) <= count_fn(text) * _SAVING_RATIO:
        return table, "table"
    return text, "none"


def _tabular_rows(text: str) -> list[dict[str, object]] | None:
    """Parse `text` as a uniform array of flat objects, else None."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, list) or len(data) < _MIN_ROWS:
        return None
    if not all(isinstance(row, dict) for row in data):
        return None

    keys = set(data[0])
    for row in data:
        if set(row) != keys:
            return None
        for value in row.values():
            if not _is_scalar(value):
                return None
            if isinstance(value, str) and ("\t" in value or "\n" in value):
                return None
    return data


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _render_table(rows: list[dict[str, object]]) -> str:
    columns = list(rows[0])
    lines = [
        f"[tokunseba: JSON array of {len(rows)} objects rendered as a table; "
        f"columns in order: {', '.join(columns)}]",
        "\t".join(columns),
    ]
    lines.extend(
        "\t".join(_cell(row[column]) for column in columns) for row in rows
    )
    return "\n".join(lines)


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
