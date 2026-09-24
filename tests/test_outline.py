"""Folding function bodies out of a source file: what survives, and what is never touched.

The whole value of an outline is that the model can still see what is in the file. A fold
that removes a signature, a decorator or an import has not compressed the file, it has
hidden it, and every test here is a way of saying that.
"""
import re
import textwrap

import pytest

from tokunseba.transform import outline


def _py(n_bodies=4, body_lines=12):
    """A module long enough to be worth outlining, with bodies long enough to fold."""
    parts = ["import os", "import sys", "from typing import Any", "",
             "MAX_RETRIES = 5", "TIMEOUT = 30.0", "", "", "class Client:", '    """A client."""', ""]
    for i in range(n_bodies):
        parts += ["    @property", f"    def method_{i}(self, arg: str) -> int:",
                  f'        """What method {i} does."""']
        parts += [f"        x_{j} = {j}" for j in range(body_lines)]
        parts += ["        return x_0", ""]
    return "\n".join(parts)


# ------------------------------------------------------------------ what survives
def test_every_name_in_the_file_is_still_in_the_outline():
    src = _py()
    out, folded, bodies = outline.outline("python", src, "h_1")
    assert folded > 0 and bodies == 4
    for kept in ("import os", "from typing import Any", "MAX_RETRIES = 5", "class Client:",
                 "@property", "def method_0(self, arg: str) -> int:",
                 '"""What method 0 does."""', "def method_3"):
        assert kept in out, f"the outline dropped {kept!r}, which names something"


def test_the_docstring_is_kept_and_the_body_under_it_is_what_goes():
    src = _py(body_lines=20)
    out, _, _ = outline.outline("python", src, "h_1")
    assert '"""What method 1 does."""' in out
    assert "x_15 = 15" not in out


def test_a_function_with_no_docstring_keeps_its_signature():
    src = "\n".join(["def f(a, b, c=1, *, d=None):"] + [f"    y{i} = {i}" for i in range(80)])
    out, folded, _ = outline.outline("python", src, "h_1")
    assert folded > 0 and "def f(a, b, c=1, *, d=None):" in out and "y40 = 40" not in out


def test_the_outline_is_shorter_than_what_it_replaced():
    src = _py(n_bodies=6, body_lines=20)
    out, _, _ = outline.outline("python", src, "h_1")
    assert len(out) < len(src) / 2


def test_the_marker_says_how_many_lines_went_and_how_to_get_them():
    out, _, _ = outline.outline("python", _py(), "h_deadbeef")
    marker = next(x for x in out.splitlines() if "tokunseba:" in x)
    assert "lines folded" in marker and "tokunseba expand h_deadbeef" in marker


def test_without_a_handle_it_says_so_instead_of_naming_one_that_does_not_exist():
    """A secret in the file blocks the blob. The marker must not promise a recovery then."""
    out, _, _ = outline.outline("python", _py(), "")
    assert "expand " not in out and "not stored" in out


# ----------------------------------------------------------- what is never folded
def test_a_short_file_is_left_exactly_alone():
    src = "\n".join(["def f():"] + ["    pass"] * 10)
    assert outline.outline("python", src, "h") == (src, 0, 0)


def test_a_short_body_is_left_alone_even_in_a_long_file():
    src = "\n".join(f"def f{i}():\n    return {i}\n" for i in range(60))
    out, folded, _ = outline.outline("python", src, "h")
    assert folded == 0 and out == src


def test_a_file_that_does_not_parse_is_forwarded_whole():
    """An unparseable file is a file whose structure is unknown. Guessing is not allowed."""
    src = _py() + "\n\ndef broken(:\n    this is not python at all ((("
    out, folded, _ = outline.outline("python", src, "h")
    assert folded == 0 and out == src


def test_a_file_that_is_mostly_signatures_already_is_forwarded_whole():
    """Folding an interface file adds markers and removes almost nothing."""
    src = "\n".join([f"def f{i}(a, b):\n    return a + b + {i}\n" for i in range(40)])
    assert outline.outline("python", src, "h")[1] == 0


def test_module_level_code_is_never_folded():
    src = "\n".join(["import os"] + [f"CONST_{i} = {i}" for i in range(100)])
    assert outline.outline("python", src, "h")[1] == 0


def test_a_nested_function_is_not_folded_twice():
    inner = "\n".join(f"        z{i} = {i}" for i in range(20))
    src = ("def outer():\n" + "    def inner():\n" + inner + "\n        return z0\n"
           + "    return inner()\n") + "\n".join(f"x{i} = {i}" for i in range(60))
    out, _, bodies = outline.outline("python", src, "h")
    assert bodies == 1, "the outer fold already removed the inner one"
    assert out.count("tokunseba:") == 1


# ----------------------------------------------------------- the brace languages
TS = textwrap.dedent("""
    import { readFile } from "node:fs/promises";
    export const PORT = 7777;

    /** Loads config. */
    export async function loadConfig(path: string): Promise<Config> {
    %s
      return merged;
    }

    export class Proxy {
      private port: number;
      constructor(port: number) { this.port = port; }

      async start(): Promise<void> {
    %s
      }
    }
    """) % ("\n".join(f"  const v{i} = {i};" for i in range(30)),
            "\n".join(f"    const w{i} = {i};" for i in range(30)))


def test_typescript_keeps_imports_exports_signatures_and_field_declarations():
    out, folded, bodies = outline.outline("ts", TS, "h_ts")
    assert folded > 0 and bodies == 2
    for kept in ('import { readFile } from "node:fs/promises";', "export const PORT = 7777;",
                 "/** Loads config. */", "export async function loadConfig(path: string)",
                 "export class Proxy {", "private port: number;",
                 "constructor(port: number) { this.port = port; }",
                 "async start(): Promise<void> {"):
        assert kept in out, f"the outline dropped {kept!r}"
    assert "const v10 = 10;" not in out and "const w20 = 20;" not in out


@pytest.mark.parametrize("lang", ["ts", "js", "go", "rust", "java", "c", "cpp", "csharp"])
def test_a_brace_language_never_gets_a_hash_comment_in_the_middle_of_it(lang):
    """`#` is a syntax error in every language here but Python."""
    out, folded, _ = outline.outline(lang, TS, "h")
    assert folded > 0
    marker = next(x for x in out.splitlines() if "tokunseba:" in x)
    assert marker.lstrip().startswith("//")
    assert outline.footer(lang, 1, 1, "h").startswith("//")


def test_python_does_get_a_hash_comment():
    out, _, _ = outline.outline("python", _py(), "h")
    assert next(x for x in out.splitlines() if "tokunseba:" in x).lstrip().startswith("#")
    assert outline.footer("python", 1, 1, "h").startswith("#")


def test_a_brace_inside_a_string_does_not_move_the_fold():
    body = "\n".join(['  const s%d = "}}}}";' % i for i in range(20)])
    src = ("function f() {\n" + body + "\n  return 1;\n}\n"
           + "\n".join(f"const k{i} = {i};" for i in range(60)))
    out, folded, bodies = outline.outline("js", src, "h")
    assert bodies == 1 and folded > 0
    assert "const k59 = 59;" in out, "the fold ran past the end of the function"
    assert "return 1;" not in out and out.rstrip().endswith("const k59 = 59;")


def test_a_brace_inside_a_comment_does_not_move_the_fold():
    body = "\n".join("  // }" for _ in range(20))
    src = ("function f() {\n" + body + "\n  return 1;\n}\n"
           + "\n".join(f"const k{i} = {i};" for i in range(60)))
    out, _, bodies = outline.outline("js", src, "h")
    assert bodies == 1 and "const k59 = 59;" in out


def test_an_unbalanced_file_folds_nothing_rather_than_guessing():
    src = "function f() {\n" + "\n".join(f"  const v{i} = {i};" for i in range(80))
    assert outline.outline("js", src, "h")[1] == 0


@pytest.mark.parametrize("kw", ["if", "for", "while", "switch", "catch"])
def test_a_control_block_is_not_mistaken_for_a_function(kw):
    body = "\n".join(f"  const v{i} = {i};" for i in range(30))
    src = (f"{kw} (a) {{\n" + body + "\n}\n"
           + "\n".join(f"const k{i} = {i};" for i in range(40)))
    assert outline.outline("js", src, "h")[1] == 0


# ------------------------------------------------------------------ line gutters
def _gutter(src: str) -> str:
    return "\n".join(f"{i:6d}\t{line}" for i, line in enumerate(src.split("\n"), 1))


def test_a_file_read_through_a_line_numbered_gutter_is_still_outlined():
    """This is how most coding agents hand a file over. Missing it would miss the common case."""
    out, folded, bodies = outline.outline("python", _gutter(_py()), "h")
    assert folded > 0 and bodies == 4


def test_the_line_numbers_that_survive_are_the_real_ones():
    """A kept line keeps its own number, so the gap says exactly which lines to ask for."""
    src = _py()
    out, _, _ = outline.outline("python", _gutter(src), "h")
    kept = [x for x in out.splitlines() if "\t" in x and "tokunseba:" not in x]
    original = _gutter(src).splitlines()
    for line in kept:
        assert line in original, "a kept line was rewritten rather than passed through"
    numbers = [int(x.split("\t", 1)[0]) for x in kept]
    assert numbers == sorted(numbers) and numbers[0] == 1
    assert max(numbers) - len(numbers) > 10, "nothing was actually folded out of the middle"


# -------------------------------------------------------------------- which files
@pytest.mark.parametrize("path,lang", [
    ("a/b/thing.py", "python"), ("x.pyi", "python"), ("src/App.tsx", "ts"),
    ("main.go", "go"), ("lib.rs", "rust"), ("Main.java", "java"), ("a.cpp", "cpp"),
    ("a.c", "c"), ("s.swift", "swift"), ("v.kt", "kotlin"), ("q.php", "php"),
])
def test_a_source_path_is_recognised(path, lang):
    assert outline.language(path, "x = 1\n" * 80) == lang


@pytest.mark.parametrize("path", ["notes.md", "data.json", "log.txt", "a.yaml", "Makefile",
                                  "a.lock", "image.png", "", None])
def test_anything_that_is_not_source_is_not_outlined(path):
    assert outline.language(path, "x = 1\n" * 80) is None


def test_a_minified_bundle_is_not_treated_as_source():
    """One 40,000 character line is not a file with a structure worth keeping."""
    assert outline.language("bundle.min.js", "var a=1;" * 5000 + "\nx\ny\nz") is None


def test_language_needs_a_path_because_content_alone_is_ambiguous():
    assert outline.language(None, "def f():\n    pass\n" * 80) is None


def test_a_gutter_survives_the_trailing_whitespace_strip_that_runs_before_this():
    """The regression that made outlining silently never fire in the proxy.

    Canonicalisation rstrips every line before the pipeline gets here, so the gutter on a
    blank source line arrives as a bare number with its tab gone. Those lines then failed
    to match, the match rate fell under the threshold on any file with blank lines in it,
    and every guttered file fell through to the summariser instead. It passed the unit
    tests because they built the gutter themselves and never rstripped it.
    """
    from tokunseba.transform.canonical import canonicalize
    guttered = canonicalize(_gutter(_py()))
    assert re.search(r"^\s*\d+$", guttered, re.M), \
        "the fixture needs a blank source line, stripped bare, or this tests nothing"
    out, folded, bodies = outline.outline("python", guttered, "h")
    assert folded > 0 and bodies == 4


@pytest.mark.parametrize("sep", ["\t", "\u2192", " | ", "|"])
def test_every_spelling_of_a_line_number_gutter_is_recognised(sep):
    """A separator is required on a line with code on it; only a blank line may lose it."""
    src = _py()
    guttered = "\n".join(f"{i:6d}{sep}{line}" if line.strip() else f"{i:6d}"
                         for i, line in enumerate(src.split("\n"), 1))
    assert outline.outline("python", guttered, "h")[1] > 0


def test_a_file_of_bare_numbers_without_a_path_is_still_not_outlined():
    """The end-of-line branch must not turn a column of integers into a gutter."""
    assert outline.language(None, "\n".join(str(i) for i in range(200))) is None
