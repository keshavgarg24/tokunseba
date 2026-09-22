"""The brand module is imported by the CLI and the SVGs ship in the wheel's repo,
so both have contracts worth pinning: the art must fit a narrow terminal, the
banner must survive rich's markup parser, and the SVGs must stay small and valid.
"""

import io
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from rich.console import Console

from tokunseba import brand

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS = REPO_ROOT / "assets"

SVG_FILES = [
    "logo.svg",
    "logo-wordmark.svg",
    "logo-dark.svg",
    "logo-light.svg",
]

MAX_LOGO_LINES = 7
MAX_LOGO_COLS = 22
ESC = "\x1b"


def render(markup: str) -> str:
    """Render markup through a real Console and hand back the plain text."""
    buf = io.StringIO()
    Console(file=buf, width=100, force_terminal=False, no_color=True).print(markup)
    return buf.getvalue()


# --- exported names -------------------------------------------------------


def test_exports_exist_with_expected_types():
    assert isinstance(brand.LOGO_LINES, list)
    assert all(isinstance(line, str) for line in brand.LOGO_LINES)
    assert isinstance(brand.WORDMARK, str)
    assert isinstance(brand.COLORS, dict)
    assert callable(brand.banner)


def test_wordmark_is_one_line_and_names_the_tool():
    assert "\n" not in brand.WORDMARK
    assert "tokunseba" in brand.WORDMARK


# --- the art --------------------------------------------------------------


def test_logo_lines_within_seven_lines():
    assert 0 < len(brand.LOGO_LINES) <= MAX_LOGO_LINES


def test_logo_lines_within_twenty_two_columns():
    too_wide = [line for line in brand.LOGO_LINES if len(line) > MAX_LOGO_COLS]
    assert not too_wide, f"lines over {MAX_LOGO_COLS} cols: {too_wide}"


def test_logo_lines_have_no_embedded_newlines():
    assert not any("\n" in line for line in brand.LOGO_LINES)


# --- no ANSI anywhere -----------------------------------------------------


@pytest.mark.parametrize("subtitle", ["", "cuts tokens, keeps meaning"])
def test_no_ansi_escapes_in_banner(subtitle):
    assert ESC not in brand.banner(subtitle)


def test_no_ansi_escapes_in_art_constants():
    assert ESC not in brand.WORDMARK
    assert all(ESC not in line for line in brand.LOGO_LINES)


# --- banner rendering -----------------------------------------------------


def test_banner_without_subtitle_renders_and_names_the_tool():
    out = render(brand.banner())
    assert "tokunseba" in out


def test_banner_with_subtitle_renders_the_subtitle():
    out = render(brand.banner("cuts tokens, keeps meaning"))
    assert "tokunseba" in out
    assert "cuts tokens, keeps meaning" in out


def test_banner_includes_every_logo_line():
    out = render(brand.banner())
    for line in brand.LOGO_LINES:
        assert line in out


def test_banner_markup_with_brackets_in_subtitle_does_not_raise():
    # A subtitle carrying literal brackets must not be parsed as markup.
    subtitle = "[tokunseba: 312 lines omitted]"
    out = render(brand.banner(subtitle))
    assert subtitle in out


def test_banner_returns_a_string_and_is_not_empty():
    result = brand.banner()
    assert isinstance(result, str)
    assert result.strip()


# --- colours --------------------------------------------------------------


def test_colors_has_exactly_the_five_required_keys():
    assert set(brand.COLORS) == {"accent", "dim", "good", "warn", "bad"}


def test_color_values_are_usable_rich_styles():
    from rich.style import Style

    for key, value in brand.COLORS.items():
        assert isinstance(value, str) and value, key
        Style.parse(value)  # raises rich.errors.StyleSyntaxError if bogus


def test_colors_avoid_pure_black_and_white():
    banned = {"#ffffff", "#000000", "white", "black", "bright_yellow", "yellow"}
    assert not {v.lower() for v in brand.COLORS.values()} & banned


# --- the SVGs -------------------------------------------------------------


@pytest.mark.parametrize("name", SVG_FILES)
def test_svg_exists_and_is_non_empty(name):
    path = ASSETS / name
    assert path.is_file(), f"missing {path}"
    assert path.stat().st_size > 0


@pytest.mark.parametrize("name", SVG_FILES)
def test_svg_under_eight_kilobytes(name):
    assert (ASSETS / name).stat().st_size < 8 * 1024


@pytest.mark.parametrize("name", SVG_FILES)
def test_svg_parses_as_xml(name):
    root = ET.parse(ASSETS / name).getroot()
    assert root.tag == "{http://www.w3.org/2000/svg}svg"


@pytest.mark.parametrize("name", SVG_FILES)
def test_svg_has_viewbox(name):
    root = ET.parse(ASSETS / name).getroot()
    assert root.get("viewBox")


@pytest.mark.parametrize("name", SVG_FILES)
def test_svg_has_title(name):
    root = ET.parse(ASSETS / name).getroot()
    titles = root.findall(".//{http://www.w3.org/2000/svg}title")
    assert titles, f"{name} has no <title>"
    assert titles[0].text == "tokunseba"


def test_logo_svg_under_two_kilobytes():
    assert (ASSETS / "logo.svg").stat().st_size < 2 * 1024


def test_logo_svg_is_themeable():
    text = (ASSETS / "logo.svg").read_text(encoding="utf-8")
    assert "currentColor" in text
    assert "var(--tokunseba-accent, #3D7BE0)" in text


def test_explicit_variants_carry_no_currentcolor():
    # These exist precisely for contexts that cannot supply a text colour.
    for name in ("logo-dark.svg", "logo-light.svg"):
        text = (ASSETS / name).read_text(encoding="utf-8")
        assert "currentColor" not in text
        assert "var(--" not in text


def test_readme_shows_the_wordmark():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "assets/logo-wordmark.svg" in readme
