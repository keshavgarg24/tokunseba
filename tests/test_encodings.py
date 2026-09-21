"""Tests for alternative payload encodings."""

import json

from tokunseba.transform.encodings import best


def count(s: str) -> int:
    return max(1, len(s) // 4)


def _uniform_rows(n: int = 10) -> list[dict[str, object]]:
    return [
        {"id": i, "name": f"widget-number-{i}", "active": i % 2 == 0} for i in range(n)
    ]


def test_uniform_array_becomes_a_table():
    text = json.dumps(_uniform_rows())
    out, kind = best(text, count)

    assert kind == "table"
    lines = out.splitlines()
    assert lines[0] == (
        "[tokunseba: JSON array of 10 objects rendered as a table; "
        "columns in order: id, name, active]"
    )
    assert lines[1] == "id\tname\tactive"
    assert lines[2] == "0\twidget-number-0\ttrue"
    assert lines[3] == "1\twidget-number-1\tfalse"
    assert len(lines) == 12
    assert count(out) <= count(text) * 0.85


def test_null_renders_as_empty_cell():
    rows = [{"a": 1, "b": None} for _ in range(8)]
    out, kind = best(json.dumps(rows), count)
    assert kind == "table"
    assert out.splitlines()[2] == "1\t"


def test_non_uniform_keys_rejected():
    rows = _uniform_rows()
    rows[3] = {"id": 3, "name": "x", "extra": 1}
    text = json.dumps(rows)
    assert best(text, count) == (text, "none")


def test_too_few_rows_rejected():
    text = json.dumps([{"a": 1, "b": 2}] * 3)
    assert best(text, count) == (text, "none")


def test_non_list_rejected():
    text = json.dumps({"a": 1, "b": 2})
    assert best(text, count) == (text, "none")


def test_non_json_text_rejected():
    text = "just some log output\nwith two lines\n"
    assert best(text, count) == (text, "none")


def test_nested_value_rejected():
    rows = [{"a": 1, "b": {"nested": True}} for _ in range(6)]
    text = json.dumps(rows)
    assert best(text, count) == (text, "none")


def test_string_containing_newline_rejected():
    rows = [{"a": i, "b": "line one\nline two"} for i in range(6)]
    text = json.dumps(rows)
    assert best(text, count) == (text, "none")


def test_string_containing_tab_rejected():
    rows = [{"a": i, "b": "col\tcol"} for i in range(6)]
    text = json.dumps(rows)
    assert best(text, count) == (text, "none")


def test_table_rejected_when_it_does_not_save_enough():
    text = json.dumps(_uniform_rows())
    assert best(text, lambda s: 100) == (text, "none")
