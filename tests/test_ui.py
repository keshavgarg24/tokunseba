from tokunseba.ui.api import parse_since


def test_parse_since_units():
    import time
    now = time.time()
    assert abs((now - parse_since("1d")) - 86400) < 2
    assert abs((now - parse_since("2h")) - 7200) < 2
    assert abs((now - parse_since("30m")) - 1800) < 2
    assert abs((now - parse_since("1w")) - 604800) < 2


def test_parse_since_bad_input_defaults_to_a_week():
    import time
    assert abs((time.time() - parse_since("nonsense")) - 7 * 86400) < 2
    assert abs((time.time() - parse_since("")) - 7 * 86400) < 2


def test_there_is_no_web_page():
    """The dashboard is the terminal. Nothing should ship an HTML page or open a browser."""
    from pathlib import Path
    import tokunseba.ui.api as api
    assert not (Path(api.__file__).parent / "static").exists()
    import tokunseba.cli as cli
    assert "webbrowser" not in Path(cli.__file__).read_text()


async def test_root_points_at_the_terminal(client):
    r = await client.get("/_tokunseba/")
    assert r.status_code == 200 and "tokunseba ui" in r.text


def test_every_emitted_signal_is_explained_on_the_dashboard():
    """A signal nobody can interpret is noise. Keep the map and the code in step."""
    import re
    from pathlib import Path
    src = Path("src/tokunseba")
    emitted = set()
    for f in src.rglob("*.py"):
        emitted |= set(re.findall(r'record_event\(\s*"([a-z_]+)"', f.read_text()))
    from tokunseba.ui.terminal import EVENT_HELP
    explained = set(EVENT_HELP)
    missing = sorted(emitted - explained)
    assert not missing, f"signals with no explanation on the dashboard: {missing}"
