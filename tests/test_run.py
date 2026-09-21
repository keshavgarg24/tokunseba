"""Tests for the no-proxy path: `tokunseba run -- <command>`."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from tokunseba import config
from tokunseba.hooks.run import run_command
from tokunseba.tokens.estimator import Estimator
from tokunseba.transform.handles import HandleStore

HANDLE_RE = re.compile(r"\bh_[0-9a-f]{12}\b")


def _parts(home: Path, truncate_lines: int | None = None):
    cfg = config.load()
    if truncate_lines is not None:
        cfg.thresholds.truncate_lines = truncate_lines
    return cfg, HandleStore(home / "blobs"), Estimator(None)


def _emit(code: str) -> list[str]:
    """argv that runs `code` with the interpreter running these tests."""
    return [sys.executable, "-c", code]


def test_long_output_is_truncated_behind_an_expandable_handle(home: Path) -> None:
    cfg, handles, estimator = _parts(home, truncate_lines=100)

    out, rc = run_command(
        _emit("for i in range(500): print(f'line {i}')"), cfg, handles, estimator
    )

    assert rc == 0
    assert len(out.splitlines()) <= cfg.thresholds.truncate_lines + 1

    match = HANDLE_RE.search(out)
    assert match is not None, out
    expanded = HandleStore(home / "blobs").get(match.group(0))
    assert expanded is not None
    for i in range(500):
        assert f"line {i}" in expanded


def test_exit_code_is_propagated(home: Path) -> None:
    cfg, handles, estimator = _parts(home)

    out, rc = run_command(_emit("import sys; sys.exit(3)"), cfg, handles, estimator)

    assert rc == 3
    assert out == ""


def test_stderr_is_captured_and_merged_after_stdout(home: Path) -> None:
    cfg, handles, estimator = _parts(home)

    out, rc = run_command(
        _emit("import sys; print('on-stdout'); sys.stderr.write('on-stderr\\n')"),
        cfg,
        handles,
        estimator,
    )

    assert rc == 0
    assert "on-stdout" in out
    assert "on-stderr" in out
    assert out.index("on-stdout") < out.index("on-stderr")


def test_short_output_is_returned_unchanged_with_no_footer(home: Path) -> None:
    cfg, handles, estimator = _parts(home)

    out, rc = run_command(_emit("print('hello')"), cfg, handles, estimator)

    assert rc == 0
    assert out == "hello\n"
    assert "tokunseba:" not in out
    assert HANDLE_RE.search(out) is None


def test_ansi_escape_codes_are_stripped(home: Path) -> None:
    cfg, handles, estimator = _parts(home)

    out, rc = run_command(
        _emit(r"print('\x1b[31mred\x1b[0m plain')"), cfg, handles, estimator
    )

    assert rc == 0
    assert out == "red plain\n"
    assert "\x1b" not in out


def test_pytest_output_keeps_failures_and_drops_progress(home: Path, tmp_path: Path) -> None:
    cfg, handles, estimator = _parts(home)
    fixture = tmp_path / "pytest_output.txt"
    progress = [f"tests/test_mod{i}.py ........................" for i in range(40)]
    fixture.write_text(
        "collected 400 items\n"
        + "\n".join(progress)
        + "\nFAILED tests/test_mod3.py::test_broken - AssertionError: nope\n"
        "FAILED tests/test_mod7.py::test_other - ValueError: bad\n"
        "======================== 2 failed, 398 passed ========================\n"
    )

    # The command mentions pytest, so detection routes on the command string.
    out, rc = run_command([f"cat {fixture}"], cfg, handles, estimator)

    assert rc == 0
    assert "FAILED tests/test_mod3.py::test_broken" in out
    assert "FAILED tests/test_mod7.py::test_other" in out
    assert "2 failed, 398 passed" in out
    assert "tests/test_mod0.py ..." not in out
    assert HANDLE_RE.search(out) is not None


def test_missing_binary_returns_127_without_raising(home: Path) -> None:
    cfg, handles, estimator = _parts(home)

    out, rc = run_command(
        ["tokunseba-no-such-binary-xyz", "--help"], cfg, handles, estimator
    )

    assert rc == 127
    assert out == "tokunseba: command not found: tokunseba-no-such-binary-xyz"


def test_output_with_a_secret_is_never_written_to_a_blob(home: Path) -> None:
    cfg, handles, estimator = _parts(home, truncate_lines=100)

    out, rc = run_command(
        _emit(
            "print('AKIAIOSFODNN7EXAMPLE')\n"
            "for i in range(500): print(f'filler {i}')"
        ),
        cfg,
        handles,
        estimator,
    )

    assert rc == 0
    assert out.count(HandleStore.blocked_footer()) == 1
    assert HANDLE_RE.search(out) is None

    blobs = home / "blobs"
    written = [p.read_text() for p in blobs.iterdir() if p.is_file()] if blobs.exists() else []
    assert not any("AKIA" in blob for blob in written)


def test_list_argv_runs_without_a_shell(home: Path) -> None:
    cfg, handles, estimator = _parts(home)

    # Shell metacharacters stay literal arguments when argv has several parts.
    out, rc = run_command(["python", "-c", "print(1)"], cfg, handles, estimator)

    assert rc == 0
    assert out == "1\n"


def test_shell_form_expands_metacharacters(home: Path) -> None:
    cfg, handles, estimator = _parts(home)

    out, rc = run_command(["echo one && echo two"], cfg, handles, estimator)

    assert rc == 0
    assert out.splitlines() == ["one", "two"]
