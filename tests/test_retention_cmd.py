"""Choosing how long history is kept.

Reports can only reach as far back as retention allows, so the window has to be visible and
changeable in one command rather than buried in a config file.
"""
import click
import pytest
from click.testing import CliRunner

from tokunseba import config
from tokunseba.commands_retention import humanise, parse_days, register


@pytest.fixture
def app():
    g = click.Group()
    register(g)
    return g


def run(app, args):
    return CliRunner().invoke(app, args, catch_exceptions=False)


def flat(result) -> str:
    """Rich wraps to the terminal width, so a hint can straddle a newline."""
    return " ".join(result.output.split())


@pytest.mark.parametrize("text,days", [
    ("24h", 1), ("12h", 1), ("7d", 7), ("30d", 30), ("6w", 42), ("6m", 180),
    ("1y", 365), ("2y", 730), ("90", 90),
    ("forever", 0), ("always", 0), ("0", 0), ("  1Y  ", 365),
])
def test_windows_people_actually_type(text, days):
    assert parse_days(text) == days


@pytest.mark.parametrize("bad", ["soon", "-5d", "", "d"])
def test_a_window_it_cannot_read_is_an_error_not_a_guess(bad):
    with pytest.raises(click.BadParameter):
        parse_days(bad)


def test_sub_day_windows_round_up_rather_than_to_zero():
    """0 means forever, so a short window must never round down into it."""
    assert parse_days("1h") == 1


@pytest.mark.parametrize("days,text", [
    (0, "forever"), (1, "1 day"), (7, "1 week"), (14, "2 weeks"),
    (30, "1 month"), (90, "3 months"), (365, "1 year"), (730, "2 years"), (45, "45 days"),
])
def test_windows_read_back_in_words(days, text):
    assert humanise(days) == text


def test_show_states_the_window_and_where_to_change_it(app, home):
    out = flat(run(app, ["retention"]))
    assert "3 months" in out and "tokunseba retention keep" in out


def test_keep_changes_the_window(app, home):
    run(app, ["retention", "keep", "1y"])
    assert config.load().retention.days == 365


def test_keep_forever_disables_pruning(app, home):
    out = run(app, ["retention", "keep", "forever"]).output
    assert config.load().retention.days == 0
    assert "grows without bound" in out, "keeping everything deserves a warning"


def test_bodies_cannot_outlive_the_history_they_belong_to(app, home):
    out = run(app, ["retention", "keep", "30d", "--bodies", "90d"]).output
    cfg = config.load()
    assert cfg.retention.keep_bodies_days == 30 and "Clamping" in out


def test_auto_toggles_the_daily_prune(app, home):
    run(app, ["retention", "auto", "off"])
    assert config.load().retention.auto_prune is False
    run(app, ["retention", "auto", "on"])
    assert config.load().retention.auto_prune is True


def test_prune_on_a_forever_window_says_so_instead_of_doing_nothing(app, home):
    run(app, ["retention", "keep", "forever"])
    assert "nothing to prune" in run(app, ["retention", "prune"]).output


def test_prune_reports_what_it_removed(app, home):
    out = run(app, ["retention", "prune"]).output
    assert "Removed" in out and "request rows" in out


def test_prune_keep_does_not_change_the_saved_window(app, home):
    run(app, ["retention", "keep", "1y"])
    run(app, ["retention", "prune", "--keep", "1d"])
    assert config.load().retention.days == 365
