from pathlib import Path
import pytest
from tokunseba.transform.summarize import detect_type, summarize

FIX = Path(__file__).parent / "fixtures"

@pytest.mark.parametrize("fixture,label,must_keep,must_drop", [
    ("pytest_output.txt", "pytest", "FAILED tests/test_x.py::test_y", "tests/test_ok.py ...."),
    ("jest_output.txt", "jest", "● renders header", "✓ renders footer"),
    ("cargo_output.txt", "cargo_test", "test parse::bad ... FAILED", "test parse::good ... ok"),
    ("go_output.txt", "go_test", "--- FAIL: TestSum", "--- PASS: TestOk"),
])
def test_summarize_keeps_failures_drops_noise(fixture, label, must_keep, must_drop):
    text = (FIX / fixture).read_text()
    assert detect_type(text, None, None)[0] == label
    out, omitted = summarize(label, text)
    assert must_keep in out and must_drop not in out and omitted > 0


# --------------------------------------------------------------------------- #
# Command override
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("command,label", [
    ("uv run pytest -q tests/", "pytest"),
    ("npx jest --ci", "jest"),
    ("npx vitest run", "jest"),
    ("cargo test --all-features", "cargo_test"),
    ("go test ./...", "go_test"),
    ("npm install --save-dev typescript", "install_log"),
    ("pip install -r requirements.txt", "install_log"),
    ("uv sync --frozen", "install_log"),
    ("yarn add react", "install_log"),
    ("pnpm add -D vite", "install_log"),
    ("git diff --stat HEAD~1", "git_diff"),
    ("ls -la /tmp", "listing"),
    ("find . -name '*.py'", "listing"),
    ("  tree src", "listing"),
])
def test_command_override_wins_over_content(command, label):
    # Content that looks like a stack trace must not beat an explicit command.
    text = 'Traceback (most recent call last):\n  File "x.py", line 1, in <module>\n'
    assert detect_type(text, None, command) == (label, 0.95)


# --------------------------------------------------------------------------- #
# Passthrough labels
# --------------------------------------------------------------------------- #

JSON_TEXT = '{\n  "name": "widget",\n  "count": 3,\n  "tags": ["a", "b"]\n}'

LISTING_TEXT = "\n".join(
    ["README.md", "pyproject.toml", "uv.lock", "src/tokunseba/cli.py", "docs/index.md"] * 4
)

SOURCE_TEXT = (
    "import os\n"
    "from pathlib import Path\n"
    "\n"
    "\n"
    "def load(path: str) -> str:\n"
    "    return Path(path).read_text()\n"
)

GENERIC_TEXT = "the quick brown fox jumped over the lazy dog\nand then it took a nap\n"


def test_json_detected_and_passed_through():
    label, confidence = detect_type(JSON_TEXT, None, None)
    assert label == "json"
    assert confidence >= 0.6
    assert summarize("json", JSON_TEXT) == (JSON_TEXT, 0)


def test_listing_detected_and_passed_through_when_short():
    label, _ = detect_type(LISTING_TEXT, None, None)
    assert label == "listing"
    assert summarize("listing", LISTING_TEXT) == (LISTING_TEXT, 0)


def test_source_detected_from_tool_name_and_passed_through():
    label, confidence = detect_type(SOURCE_TEXT, "Read", None)
    assert label == "source"
    assert confidence == pytest.approx(2 / 3)
    assert summarize("source", SOURCE_TEXT) == (SOURCE_TEXT, 0)


def test_generic_when_nothing_matches():
    assert detect_type(GENERIC_TEXT, None, None) == ("generic", 0.0)
    assert summarize("generic", GENERIC_TEXT) == (GENERIC_TEXT, 0)


# --------------------------------------------------------------------------- #
# Per-label reduction rules
# --------------------------------------------------------------------------- #

def test_listing_truncates_at_150_lines():
    text = "\n".join(f"src/module_{i}.py" for i in range(200))
    assert detect_type(text, None, None)[0] == "listing"
    out, omitted = summarize("listing", text)
    assert omitted == 50
    assert "src/module_149.py" in out
    assert "src/module_150.py" not in out


def test_stack_trace_elides_middle_frames():
    text = (FIX / "stack_trace.txt").read_text()
    label, confidence = detect_type(text, None, None)
    assert label == "stack_trace"
    assert confidence >= 0.6

    out, omitted = summarize(label, text)
    assert omitted == 4
    assert "[... 4 frames omitted]" in out
    # First and last frames survive, the middle ones do not.
    assert '"/app/main.py", line 42' in out
    assert '"/app/coerce.py", line 40' in out
    assert '"/app/handlers/ingest.py", line 54' not in out
    # Non-frame lines are always kept.
    assert "Traceback (most recent call last):" in out
    assert "ValueError: invalid literal for int()" in out


def test_install_log_keeps_warnings_and_tail():
    text = (FIX / "npm_install.txt").read_text()
    label, confidence = detect_type(text, None, None)
    assert label == "install_log"
    assert confidence >= 0.6

    out, omitted = summarize(label, text)
    assert omitted > 0
    assert "npm WARN deprecated inflight@1.0.6" in out
    assert "7 vulnerabilities (3 moderate, 4 high)" in out
    assert "Run `npm audit` for details." in out
    assert "added 412 packages in 18s" not in out


def _build_diff(body_lines: int) -> str:
    small = (
        "diff --git a/small.py b/small.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/small.py\n"
        "+++ b/small.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-a = 1\n"
        "+a = 2\n"
    )
    big = (
        "diff --git a/big.py b/big.py\n"
        "index 3333333..4444444 100644\n"
        "--- a/big.py\n"
        "+++ b/big.py\n"
        f"@@ -1,{body_lines} +1,{body_lines} @@\n"
    )
    big += "\n".join(f"+line {i}" for i in range(body_lines))
    return small + big


def test_git_diff_truncates_long_files():
    text = _build_diff(200)
    assert detect_type(text, None, None)[0] == "git_diff"

    out, omitted = summarize("git_diff", text)
    assert omitted > 0
    # The small file is untouched, the big one is capped at 80 body lines.
    assert "-a = 1" in out
    assert "diff --git a/big.py b/big.py" in out
    assert "+line 0" in out
    assert "+line 199" not in out
    assert "[... 124 more lines in this file omitted]" in out


def test_pytest_caps_long_failure_sections():
    text = "\n".join(
        [
            "collected 3 items",
            "______________________________ test_big _______________________________",
            *[f"    detail line {i}" for i in range(100)],
            "=========================== short test summary info ===========================",
            "FAILED tests/t.py::test_big - AssertionError: boom",
            "========================= 1 failed, 2 passed in 0.50s =========================",
        ]
    )
    out, omitted = summarize("pytest", text)
    assert "[... 61 lines of this section omitted]" in out
    assert "    detail line 0" in out
    # 61 section lines plus the dropped "short test summary info" header.
    assert omitted == 62


def test_omitted_count_excludes_inserted_markers():
    text = (FIX / "pytest_output.txt").read_text()
    out, omitted = summarize("pytest", text)
    original = len(text.splitlines())
    real_kept = [line for line in out.splitlines() if not line.startswith("[... ")]
    assert omitted == original - len(real_kept)


def test_unknown_label_is_passthrough():
    assert summarize("not_a_label", GENERIC_TEXT) == (GENERIC_TEXT, 0)


def test_empty_text_is_passthrough():
    assert summarize("pytest", "") == ("", 0)


# --------------------------------------------------------------------------- #
# tie_breaker hook
# --------------------------------------------------------------------------- #

# Exactly one git_diff signal -> score 1 -> confidence 0.5, below the threshold.
LOW_CONFIDENCE_TEXT = "some build output\ndiff --git a/x.py b/x.py\nmore text here\n"


def test_low_confidence_text_is_actually_low_confidence():
    assert detect_type(LOW_CONFIDENCE_TEXT, None, None) == ("git_diff", 0.5)


def test_tie_breaker_not_consulted_when_confident(monkeypatch):
    calls: list[str] = []

    def spy(text: str) -> tuple[str, float] | None:
        calls.append(text)
        return ("json", 0.99)

    monkeypatch.setattr("tokunseba.transform.summarize.tie_breaker", spy)
    text = (FIX / "pytest_output.txt").read_text()
    label, confidence = detect_type(text, None, None)
    assert (label, calls) == ("pytest", [])
    assert confidence >= 0.6


def test_tie_breaker_honored_for_low_confidence(monkeypatch):
    calls: list[str] = []

    def spy(text: str) -> tuple[str, float] | None:
        calls.append(text)
        return ("stack_trace", 0.88)

    monkeypatch.setattr("tokunseba.transform.summarize.tie_breaker", spy)
    assert detect_type(LOW_CONFIDENCE_TEXT, None, None) == ("stack_trace", 0.88)
    assert calls == [LOW_CONFIDENCE_TEXT]


def test_tie_breaker_returning_none_falls_back_to_regex(monkeypatch):
    monkeypatch.setattr("tokunseba.transform.summarize.tie_breaker", lambda text: None)
    assert detect_type(LOW_CONFIDENCE_TEXT, None, None) == ("git_diff", 0.5)


def test_tie_breaker_returning_unknown_label_falls_back(monkeypatch):
    monkeypatch.setattr(
        "tokunseba.transform.summarize.tie_breaker", lambda text: ("nonsense", 0.99)
    )
    assert detect_type(LOW_CONFIDENCE_TEXT, None, None) == ("git_diff", 0.5)


def test_tie_breaker_is_restored_between_tests():
    import tokunseba.transform.summarize as module

    assert module.tie_breaker is None
