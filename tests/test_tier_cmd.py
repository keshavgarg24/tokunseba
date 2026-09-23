"""The `tokunseba tier` group.

The point of this command is informed consent, so most of these tests are about what is
said before a change is made, not only about the flag that ends up in the file.
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from tokunseba import config
from tokunseba.cli import main
from tokunseba.commands_tier import TIERS, tier_table


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKUNSEBA_HOME", str(tmp_path))
    return tmp_path


def run(*args, stdin: str = ""):
    return CliRunner().invoke(main, ["tier", *args], input=stdin)


def flat(text: str) -> str:
    return " ".join(text.split())


def test_the_default_listing_shows_every_tier(home):
    out = flat(run().output)
    for tier in TIERS:
        assert tier.name in out


def test_a_tier_is_addressable_by_number_and_by_name(home):
    assert flat(run("explain", "2").output) == flat(run("explain", "reach-preserving").output)


def test_an_unknown_tier_is_an_error_that_lists_the_real_ones(home):
    res = run("explain", "nine")
    assert res.exit_code == 2
    assert "reach-preserving" in flat(res.output)


def test_tier_zero_cannot_be_turned_off(home):
    res = run("disable", "0")
    assert res.exit_code == 2
    assert "tokunseba off" in flat(res.output)


def test_enabling_tier_three_says_what_it_may_change_before_asking(home):
    res = run("enable", "3", stdin="n\n")
    assert "change which model answers" in flat(res.output)
    assert config.load().tier3 is False


def test_declining_changes_nothing(home):
    run("disable", "1", stdin="n\n")
    assert config.load().lossless is True


def test_confirming_writes_the_flag(home):
    res = run("enable", "3", stdin="y\n")
    assert res.exit_code == 0
    assert config.load().tier3 is True


def test_yes_skips_the_prompt(home):
    assert run("disable", "2", "-y").exit_code == 0
    assert config.load().reach_preserving is False


def test_disabling_tier_one_warns_that_tier_two_goes_with_it(home):
    assert "Tier 2 runs inside tier 1" in flat(run("disable", "1", stdin="n\n").output)


def test_a_tier_that_is_already_in_that_state_is_a_no_op(home):
    res = run("enable", "1", "-y")
    assert res.exit_code == 0
    assert "already on" in flat(res.output)


def test_the_status_warns_when_nothing_is_being_transformed(home):
    run("disable", "1", "-y")
    assert "nothing is being transformed" in flat(run().output)


def test_the_table_reflects_the_config_it_is_given(home):
    cfg = config.load()
    cfg.tier3 = True
    cells = [c._cells for c in tier_table(cfg).columns]
    assert "[green]on[/green]" in cells[2]


def test_every_tier_describes_what_it_may_change():
    """A tier with no stated limit is a tier nobody can consent to."""
    for tier in TIERS:
        assert tier.does and tier.changes and tier.detail
        assert tier.changes.endswith(".")
