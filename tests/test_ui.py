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


def test_the_terminal_is_still_the_default_and_still_needs_no_browser():
    """`ui` and `watch` must never reach for a browser. Only `dashboard` may, on request.

    The browser page was added because a second screen holds more than a scrollback does.
    It did not replace anything: someone on a server over ssh still runs `tokunseba ui` and
    still gets the whole view, and nothing opens a window behind their back.
    """
    import re
    from pathlib import Path
    import tokunseba.cli as cli
    src = Path(cli.__file__).read_text()
    # The one place a browser may be opened is the command whose name says so.
    start, end = src.index("def dashboard("), src.index('@main.command("watch")')
    opens = [m.start() for m in re.finditer(r"webbrowser", src)]
    assert opens, "the dashboard command is supposed to be able to open one"
    assert all(start < i < end for i in opens), (
        "only `tokunseba dashboard` may open a browser; `ui` and `watch` may not")
    for terminal in ("def ui(", "def watch_cmd(", "def _render_dashboard("):
        at = src.index(terminal)
        assert not (start < at < end)


async def test_the_proxy_serves_the_dashboard_at_its_own_prefix(client):
    # The fixture speaks as http://proxy.test; a browser on this machine does not, and the
    # page refuses any other name on purpose. See tests/test_dashboard.py for that check.
    r = await client.get("/_tokunseba/", headers={"host": "127.0.0.1:7777"})
    assert r.status_code == 200 and "tokunseba" in r.text
    assert "<!doctype html>" in r.text.lower()


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
