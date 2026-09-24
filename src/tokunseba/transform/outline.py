"""Fold the bodies of functions out of a source file, keeping everything that names things.

A coding agent that asks to read a 2,000 line module almost never needs all 2,000 lines. It
needs to know what is in there: the imports, the classes, the function signatures, the
docstrings, the constants, the decorators. The bodies matter for the two or three functions
the task is actually about, and those it can ask for.

So this keeps the skeleton and replaces each long body with one line saying how many lines
went and how to get them back. Nothing is guessed at and nothing is rewritten: the kept
lines are the file's own bytes, and the whole original stays behind a handle, so
`tokunseba expand` returns it to the byte.

What is never folded, in any language:

* imports, and anything else at module level -- that is the file's interface
* the signature line, its decorators, and its docstring
* a body shorter than `MIN_BODY_LINES`, where the marker is not smaller than the body
* anything at all, if the result is not meaningfully smaller than what it replaced

Python is parsed with the standard library, so the line ranges are exact. The brace
languages are scanned rather than parsed: a real parser for each of them would be a
dependency tree larger than this project, and a scanner that tracks strings and comments
gets the same answer on anything that compiles. When the scan is not certain, it folds
nothing -- a file that comes through untouched costs tokens, a file folded in the wrong
place costs the answer.
"""
from __future__ import annotations

import ast
import re

#: A body shorter than this is left alone: the marker line, plus the tokens it takes to say
#: which handle holds the rest, comes to about as much as the lines it would replace.
MIN_BODY_LINES = 8

#: Below this there is no outlining worth doing, whatever the file is.
MIN_FILE_LINES = 60

#: The fold has to remove at least this share of the file, or the file goes through whole.
#: Outlining a file that is mostly signatures already just adds noise to the middle of it.
MIN_SHARE_FOLDED = 0.25

_PY = {".py", ".pyi"}
_BRACE = {
    ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js",
    ".ts": "ts", ".tsx": "ts", ".mts": "ts", ".cts": "ts",
    ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".swift": "swift", ".cs": "csharp", ".php": "php", ".scala": "scala",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp",
    ".hpp": "cpp", ".hh": "cpp", ".m": "objc", ".mm": "objc",
}

#: Declaration lines whose block is a body worth folding. Anchored at the start of the
#: line's own indentation so a call that merely mentions `function` is never matched, and
#: required to end in `{` so a forward declaration or an interface member is left alone.
_DECL = re.compile(
    r"""^[ \t]*
    (?!(?:if|for|while|switch|catch|else|do|return|match|when|try|using|lock)\b)
    (?:(?:export|default|public|private|protected|internal|static|final|abstract|async|
        unsafe|override|open|suspend|inline|virtual|extern|const|func|fn|def|sealed|
        operator|partial|readonly)\s+)*
    [A-Za-z_~$<][\w$<>,:\[\]\ .*&?~-]*
    \s*\([^;]*\)
    [^;{}]*\{\s*$
    """,
    re.VERBOSE,
)

#: A `func`/`fn`/`function`/`sub` keyword form, which the general shape above can miss when
#: the return type sits after the parameter list or the name is unusual.
_DECL_KEYWORD = re.compile(r"^[ \t]*(?:[\w$]+\s+)*(?:function|func|fn|sub)\b[^;{}]*\{\s*$")


def language(path: str | None, text: str) -> str | None:
    """Which language this is, or None when it is not source that can be outlined."""
    if not path:
        return None
    lower = path.lower()
    dot = lower.rfind(".")
    if dot < 0:
        return None
    ext = lower[dot:]
    if ext in _PY:
        return "python"
    if ext in _BRACE:
        # A minified bundle is one enormous line. Folding it would fold the whole file
        # into a marker, which is what `junk` already does and says more clearly.
        lines = text.split("\n", 400)
        if len(lines) > 3 and max(len(x) for x in lines[:400]) > 2000:
            return None
        return _BRACE[ext]
    return None


def _python_folds(text: str) -> list[tuple[int, int]]:
    """Half-open [start, end) line ranges, zero-based, that are function bodies.

    Docstrings are excluded from the range rather than folded with it: the docstring is
    usually the most informative thing in the function and the smallest part of it.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        # A file that does not parse is a file whose structure is not known. Fold nothing.
        return []
    folds: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        if not body or node.end_lineno is None:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str) and len(body) > 1):
            start = (first.end_lineno or first.lineno)  # 1-based, inclusive: next line starts
        else:
            start = first.lineno - 1
        end = node.end_lineno
        if end - start >= MIN_BODY_LINES:
            folds.append((start, end))
    # An inner function inside a folded outer one is already gone; keep only the outermost.
    folds.sort(key=lambda r: (r[0], -r[1]))
    out: list[tuple[int, int]] = []
    for s, e in folds:
        if out and s < out[-1][1]:
            continue
        out.append((s, e))
    return out


def _strip_for_scan(text: str) -> str:
    """The text with string and comment contents blanked, so brace counting is honest.

    Characters are replaced one for one rather than removed, so every offset in the result
    still points at the same place in the original.
    """
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'`":
            quote, j = c, i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote:
                    break
                if text[j] != "\n":
                    out[j] = " "
                j += 1
            i = j + 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if c == "#" and (i == 0 or text[i - 1] == "\n" or text[i - 1] in " \t"):
            # Only useful for the languages that have it; harmless elsewhere because a
            # blanked `#` run never changes a brace count.
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, min(j, n)):
                if text[k] != "\n":
                    out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def _brace_folds(text: str) -> list[tuple[int, int]]:
    scan = _strip_for_scan(text)
    lines = scan.split("\n")
    # Offset of the start of each line in `scan`, so a line number can become an index.
    starts, pos = [], 0
    for ln in lines:
        starts.append(pos)
        pos += len(ln) + 1
    folds: list[tuple[int, int]] = []
    for i, line in enumerate(lines):
        if not (_DECL.match(line) or _DECL_KEYWORD.match(line)):
            continue
        open_at = starts[i] + line.rindex("{")
        depth, j, n = 0, open_at, len(scan)
        while j < n:
            if scan[j] == "{":
                depth += 1
            elif scan[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth != 0:
            continue  # unbalanced: the scan is not certain, so nothing is folded
        close_line = scan.count("\n", 0, j)
        if close_line - (i + 1) >= MIN_BODY_LINES:
            folds.append((i + 1, close_line))
    folds.sort(key=lambda r: (r[0], -r[1]))
    out: list[tuple[int, int]] = []
    for s, e in folds:
        if out and s < out[-1][1]:
            continue
        out.append((s, e))
    return out


#: `cat -n` style gutters, which is how most coding agents hand a file to the model. The
#: fold has to be computed on the source underneath them, or the parse fails and a file that
#: was read the usual way is never outlined at all.
#:
#: The final alternative, end of line, is not padding. Canonicalisation strips trailing
#: whitespace from every line before this runs, so the gutter on a blank source line loses
#: its separator and arrives as a bare number. Without that branch those lines fail to match,
#: the match rate falls under the threshold on any file with blank lines in it, and nothing
#: is ever outlined -- which is precisely what happened the first time this shipped.
_GUTTER = re.compile(r"^\s*\d+(?:\t|\u2192|\s*\|\s?|$)")


def _ungutter(lines: list[str]) -> tuple[list[str], bool]:
    """Strip a line-number gutter if every non-blank line has one. Otherwise, unchanged."""
    hits = [_GUTTER.match(x) for x in lines]
    real = [i for i, x in enumerate(lines) if x.strip()]
    if not real or sum(1 for i in real if hits[i]) < 0.9 * len(real):
        return lines, False
    return [x[hits[i].end():] if hits[i] else x for i, x in enumerate(lines)], True


def outline(lang: str, text: str, handle: str) -> tuple[str, int, int]:
    """Return (outlined text, lines folded, bodies folded).

    `(text, 0, 0)` whenever there is nothing worth folding -- too short, unparseable, or a
    fold that would not remove enough of the file to be worth the markers it leaves behind.
    """
    lines = text.split("\n")
    if len(lines) < MIN_FILE_LINES:
        return text, 0, 0
    source, guttered = _ungutter(lines)
    body = "\n".join(source) if guttered else text
    folds = _python_folds(body) if lang == "python" else _brace_folds(body)
    if not folds:
        return text, 0, 0
    folded = sum(e - s for s, e in folds)
    if folded < MIN_SHARE_FOLDED * len(lines):
        return text, 0, 0

    # Python is the only language here whose line comment is `#`. Getting this wrong puts a
    # syntax error in the middle of the file the model is reading.
    comment = "#" if lang == "python" else "//"
    # Emitted from the original lines, gutter and all, so what is kept is byte-for-byte what
    # the tool produced. Only the fold ranges come from the stripped copy.
    out: list[str] = []
    at = 0
    for s, e in folds:
        out.extend(lines[at:s])
        sample = source[s] if s < len(source) else ""
        indent = sample[:len(sample) - len(sample.lstrip())] or "    "
        out.append(f"{indent}{comment} [tokunseba: {e - s} lines folded; whole file: "
                   + (f"tokunseba expand {handle}]" if handle
                      else "the original was not stored]"))
        at = e
    out.extend(lines[at:])
    return "\n".join(out), folded, len(folds)


def footer(lang: str, folded: int, count: int, handle: str) -> str:
    """One line under the outline saying what happened to the file and how to undo it."""
    comment = "#" if lang == "python" else "//"
    where = (f"tokunseba expand {handle}" if handle
             else "the original was not stored: it held something that looked like a secret")
    return (f"{comment} [tokunseba: {count} function bodies folded, {folded} lines. "
            f"Signatures, imports, docstrings and every line between them are the file's "
            f"own. For any body: {where}]")
