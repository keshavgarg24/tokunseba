"""Tests for junk detection and summarization."""

from pathlib import Path

from tokunseba.transform.junk import detect, summary

FIXTURES = Path(__file__).parent / "fixtures"
LOCKFILE = FIXTURES / "package-lock.json"


def _lockfile_text() -> str:
    return LOCKFILE.read_text()


def test_detect_lockfile_by_basename():
    assert detect(str(LOCKFILE), _lockfile_text()) == "lockfile"
    assert detect("/repo/uv.lock", "a\nb\n") == "lockfile"


def test_lockfile_summary_is_compact_and_structured():
    text = _lockfile_text()
    out = summary("lockfile", str(LOCKFILE), text, "h7f3a1")
    lines = out.splitlines()

    assert len(lines) < 40
    assert lines[0] == "[tokunseba: package-lock.json (lockfile) replaced with a summary]"
    assert "top-level keys: dependencies, lockfileVersion, name, packages" in out
    assert "packages: 14 entries" in out
    assert "dependencies: 3 entries" in out
    assert "sample: " in out
    assert lines[-1] == (
        "[tokunseba: full content omitted. Full output: run `tokunseba expand h7f3a1`]"
    )
    assert len(out) < len(text)


def test_lockfile_summary_sample_is_capped_at_ten_names():
    out = summary("lockfile", str(LOCKFILE), _lockfile_text(), "h1")
    sample_line = next(line for line in out.splitlines() if line.startswith("sample: "))
    assert len(sample_line.removeprefix("sample: ").split(", ")) == 10


def test_non_json_lockfile_falls_back_to_preview():
    text = "\n".join(f"dep-{i} 1.0.{i}" for i in range(50))
    out = summary("lockfile", "/repo/go.sum", text, "abc")
    lines = out.splitlines()
    assert len(lines) == 22  # header + 20 preview lines + footer
    assert lines[1] == "dep-0 1.0.0"
    assert lines[20] == "dep-19 1.0.19"
    assert "tokunseba expand abc" in lines[-1]


def test_detect_binary():
    text = "header" + "\x00\x01\x02" * 100
    assert detect("/repo/data.bin", text) == "binary"
    # Binary wins even when the name looks like a lockfile.
    assert detect("/repo/Cargo.lock", text) == "binary"


def test_tabs_and_newlines_do_not_count_as_binary():
    assert detect("/repo/app.py", "a\tb\nc\r\n" * 200) is None


def test_detect_minified_by_extension():
    assert detect("/repo/static/app.min.js", "x = 1\n") == "minified"
    assert detect("/repo/static/app.min.css", "a{}\n") == "minified"
    assert detect("/repo/static/app.js.map", "{}\n") == "minified"


def test_detect_minified_by_long_line_heuristic():
    text = "\n".join("a" * 1500 for _ in range(6))
    assert detect("/repo/static/bundle.js", text) == "minified"
    assert detect(None, text) == "minified"


def test_short_long_lined_text_is_not_minified():
    text = "\n".join("a" * 1500 for _ in range(4))
    assert detect("/repo/static/bundle.js", text) is None


def test_detect_generated_by_path():
    assert detect("/repo/node_modules/left-pad/index.js", "x\n") == "generated"
    assert detect("/repo/dist/main.js", "x\n") == "generated"
    assert detect("/repo/src/__pycache__/mod.cpython-312.pyc", "x\n") == "generated"


def test_normal_python_file_is_not_junk():
    assert detect("/repo/src/app.py", "def main():\n    return 1\n") is None


def test_detect_handles_missing_path():
    assert detect(None, "def main():\n    return 1\n") is None
    assert detect(None, "\x00" * 500) == "binary"


def test_summary_without_path_still_renders():
    out = summary("binary", None, "\x00\x01", "zz9")
    assert out.startswith("[tokunseba: content (binary) replaced with a summary]")
    assert out.endswith("`tokunseba expand zz9`]")
