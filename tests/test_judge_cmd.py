"""The judge lifecycle.

The judge is the one part of tokunseba with a real footprint: an ~800 MB download and about
2.2 GB of resident memory. These tests pin the properties that keep that cost opt-in, and in
particular that nothing here ever imports torch or loads a checkpoint.
"""
import click
import pytest
from click.testing import CliRunner

from tokunseba import config
from tokunseba.commands_judge import register


@pytest.fixture
def app():
    g = click.Group()
    register(g)
    return g


def run(app, args, **kw):
    return CliRunner().invoke(app, args, catch_exceptions=False, **kw)


@pytest.fixture
def _no_download(monkeypatch):
    """Fail loudly if a test would pull the weights."""
    import tokunseba.commands_judge as c

    def boom(_cfg):
        raise AssertionError("a test tried to download the judge weights")
    monkeypatch.setattr(c, "_download", boom)


@pytest.fixture
def _extra_installed(monkeypatch):
    """Pretend the laya extra is importable, without it being installed.

    `judge enable` refuses before it writes anything when the extra is missing, so a test
    of what enabling *does* has to pin this. Reading it off the machine instead means the
    test passes only for whoever happens to have run `uv sync --all-extras`, and fails in
    CI and for everyone who clones the repository -- which is exactly what it did.
    """
    import tokunseba.commands_judge as c
    monkeypatch.setattr(c, "_installed", lambda: True)


def test_the_judge_is_off_until_it_is_asked_for(home):
    assert config.load().judge.enabled is False


def test_a_disabled_judge_is_never_built_so_torch_is_never_imported(home):
    """build_chain must not even construct LayaJudge while the judge is off.

    Constructing one is harmless, but asking it `available()` imports torch, which costs
    about 65 MB and a visible pause. Leaving it out of the chain is what guarantees that.
    """
    from tokunseba.judge import build_chain
    cfg = config.load()
    assert [b.name for b in build_chain(cfg).backends] == ["rules"]
    cfg.judge.enabled = True
    assert "laya" in [b.name for b in build_chain(cfg).backends]


def test_status_says_it_is_off_and_how_to_turn_it_on(app, home):
    out = run(app, ["judge", "status"]).output
    assert "disabled" in out and "tokunseba judge enable" in out


def test_status_is_the_default_subcommand(app, home):
    assert "disabled" in run(app, ["judge"]).output


def test_enable_discloses_the_download_and_the_memory_before_asking(app, home, _no_download):
    out = run(app, ["judge", "enable"], input="n\n").output
    assert "808 MB" in out and "2200 MB" in out
    assert config.load().judge.enabled is False, "declining must change nothing"


def test_enable_then_disable_round_trips(app, home, _no_download, _extra_installed, monkeypatch):
    import tokunseba.commands_judge as c
    monkeypatch.setattr(c, "weights_cached", lambda *_a: True)
    run(app, ["judge", "enable", "-y"])
    assert config.load().judge.enabled is True
    run(app, ["judge", "disable"])
    cfg = config.load()
    assert cfg.judge.enabled is False and cfg.judge.warm is False and cfg.judge.inline is False


def test_enable_does_not_warm_unless_asked(app, home, _no_download, _extra_installed, monkeypatch):
    """Warming holds 2.2 GB from startup, so it is a second, separate opt-in."""
    import tokunseba.commands_judge as c
    monkeypatch.setattr(c, "weights_cached", lambda *_a: True)
    run(app, ["judge", "enable", "-y"])
    assert config.load().judge.warm is False
    run(app, ["judge", "enable", "-y", "--warm"])
    assert config.load().judge.warm is True


def test_enable_explains_the_missing_extra_without_markup_damage(app, home, monkeypatch):
    """Rich treats [laya] as markup, so the install hint has to survive rendering."""
    import tokunseba.commands_judge as c
    monkeypatch.setattr(c, "_installed", lambda: False)
    r = run(app, ["judge", "enable"])
    assert r.exit_code == 2
    assert "tokunseba[laya]" in r.output.replace("\n", "")


def test_install_explains_the_missing_extra(app, home, monkeypatch):
    import tokunseba.commands_judge as c
    monkeypatch.setattr(c, "_installed", lambda: False)
    r = run(app, ["judge", "install"])
    assert r.exit_code == 2 and "tokunseba[laya]" in r.output.replace("\n", "")


def test_remove_says_so_when_there_is_nothing_cached(app, home, monkeypatch):
    import tokunseba.commands_judge as c
    monkeypatch.setattr(c, "_cached_repo", lambda *_a: None)
    assert "Nothing to remove" in run(app, ["judge", "remove"]).output


def test_installed_check_does_not_import_laya(home, monkeypatch):
    """_installed uses find_spec precisely so that a status command stays instant."""
    import sys
    import tokunseba.commands_judge as c
    sys.modules.pop("laya", None)
    c._installed()
    assert "laya" not in sys.modules
