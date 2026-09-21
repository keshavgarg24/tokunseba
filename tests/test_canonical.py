"""Tests for the lossless canonicalization rules."""

from tokunseba.transform.canonical import canonicalize


def test_canonicalize_ansi_and_repeats():
    text = "\x1b[32mok\x1b[0m\nline\nline\nline\nline\n   \n\n\n\nend   \n"
    assert canonicalize(text) == "ok\nline\n[tokunseba: previous line repeated 3 more times]\n\n\nend\n"


def test_root_alias():
    t = "\n".join(f"/Users/k/proj/src/{n}.py: error" for n in "abc")
    out = canonicalize(t)
    assert out.startswith("[tokunseba: $ROOT = /Users/k/proj/src]\n") and "$ROOT/a.py" in out


def test_strips_osc_escape_sequences():
    assert canonicalize("\x1b]0;window title\x07hello") == "hello"
    assert canonicalize("\x1b]8;;http://x/\x1b\\link") == "link"


def test_carriage_return_keeps_only_final_frame():
    progress = "10%\r50%\r100% done\nnext"
    assert canonicalize(progress) == "100% done\nnext"


def test_trailing_whitespace_is_stripped_per_line():
    assert canonicalize("a   \n\tb\t\t\nc") == "a\n\tb\nc"


def test_blank_runs_collapse_to_two():
    assert canonicalize("a\n\n\n\n\n\nb") == "a\n\n\nb"
    # Runs shorter than three are left untouched.
    assert canonicalize("a\n\nb") == "a\n\nb"


def test_repeat_marker_only_for_three_or_more():
    assert canonicalize("x\nx\ny") == "x\nx\ny"
    assert canonicalize("x\nx\nx\ny") == "x\n[tokunseba: previous line repeated 2 more times]\ny"


def test_root_alias_skipped_when_it_does_not_pay_off():
    # Only two occurrences, so the declaration line would cost more than it saves.
    text = "/Users/k/proj/src/a.py\n/Users/k/proj/src/b.py"
    assert canonicalize(text) == text


def test_root_alias_picks_longest_frequent_prefix():
    text = "\n".join(
        [
            "/home/u/repo/pkg/mod/one.py",
            "/home/u/repo/pkg/mod/two.py",
            "/home/u/repo/pkg/mod/three.py",
            "/home/u/other/four.py",
        ]
    )
    out = canonicalize(text)
    assert out.startswith("[tokunseba: $ROOT = /home/u/repo/pkg/mod]\n")
    assert "$ROOT/one.py" in out
    # A path outside the aliased root is left intact.
    assert "/home/u/other/four.py" in out


def test_trailing_newline_is_preserved_both_ways():
    assert canonicalize("a\nb\n") == "a\nb\n"
    assert canonicalize("a\nb") == "a\nb"


def test_empty_input():
    assert canonicalize("") == ""


def test_plain_text_is_unchanged():
    text = "def main():\n    return 1\n\nmain()\n"
    assert canonicalize(text) == text
