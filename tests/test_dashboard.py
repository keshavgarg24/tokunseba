"""The browser dashboard: what it serves, what it refuses, and whether the numbers are real.

The page itself is checked here too, because its whole claim is that it reaches nothing but
this machine. That is a property of the bytes on disk, so it is asserted against them
rather than trusted to a comment.
"""
import re
import time

import pytest
from click.testing import CliRunner
from starlette.applications import Starlette

from tokunseba import config
from tokunseba.cli import main
from tokunseba.ledger import Ledger, RequestRecord, TransformRow
from tokunseba.ui import web


def _client(app):
    from starlette.testclient import TestClient
    # The default base_url is http://testserver, which the Host check correctly refuses.
    # Every test that is not about that check has to speak as a browser on this machine.
    return TestClient(app, base_url="http://127.0.0.1:7777")


def _seed(home):
    led = Ledger(home / "ledger.sqlite")
    now = time.time()
    led.upsert_session("s1", "claude-code", "/p/demo", "anthropic", "claude-sonnet-5", "treatment")
    for i in range(4):
        led.record_request(RequestRecord(
            id=f"r{i}", ts=now - i * 3600, session_id="s1", tool_id="claude-code",
            project="/p/demo", provider="anthropic", model="claude-sonnet-5", stream=False,
            input_tokens=1200, cache_read=800, cache_write=100, output_tokens=300,
            est_tokens_before=12000, est_tokens_after=1400, arm="treatment", status=200,
            latency_ms=820, body_path=""))
    led.put_transform(TransformRow(orig_sha="a" * 64, kind="dedup_ref", transformed="[ref]",
                                   orig_tokens=9000, new_tokens=40, handle="h_abc123", ref_sha=""))
    led.link_transform("r0", "a" * 64, "0:content", 8960)
    led.put_transform(TransformRow(orig_sha="b" * 64, kind="passthrough", transformed="",
                                   orig_tokens=4400, new_tokens=4400, handle="", ref_sha=""))
    led.record_event("route_signal", {"domain": "code", "difficulty": 2,
                                      "needs_tools": 1, "is_sensitive": 0}, "s1")
    return led


@pytest.fixture
def served(home):
    led = _seed(home)
    cfg = config.load()
    yield _client(Starlette(routes=web.routes(led, cfg))), led
    led.close()


# --------------------------------------------------------------- the page itself
def test_the_page_reaches_nothing_outside_this_machine():
    """No font host, no script CDN, no image host, no beacon. Offline or it is not local."""
    html = web.page()
    external = re.findall(r'(?:src|href)\s*=\s*["\'](?!data:|#)([a-zA-Z]+:)?//[^"\']+', html)
    assert external == [], f"the dashboard would fetch from outside: {external}"
    assert "fetch(" in html  # it does talk to its own origin, relatively
    for host in ("googleapis", "cdnjs", "jsdelivr", "unpkg", "http://", "https://"):
        assert host not in html, f"{host} appears in a page that claims to be offline"


def test_the_page_is_fetched_relatively_so_it_works_under_either_mount():
    """Served at / on its own and at /_tokunseba/ by the proxy. An absolute path breaks one."""
    assert 'fetch("api/overview' in web.page()


def test_serving_it_sets_a_policy_that_matches_the_claim(served):
    client, _ = served
    r = client.get("/")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "connect-src 'self'" in csp
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"


# ------------------------------------------------------------------- the numbers
def test_the_overview_carries_every_field_the_page_draws(served):
    client, _ = served
    d = client.get("/api/overview?since=7d").json()
    for key in ("version", "port", "running", "problem", "stats", "summary", "daily",
                "models", "top", "passthroughs", "signals", "sessions"):
        assert key in d, f"the page reads {key} and the endpoint does not send it"


def test_the_figures_are_the_ledger_rather_than_a_placeholder(served):
    client, led = served
    d = client.get("/api/overview?since=7d").json()
    s = d["stats"]
    assert s["requests"] == 4
    assert s["tokens_saved"] == 4 * (12000 - 1400)
    assert round(s["pct_saved"], 4) == round(s["tokens_saved"] / (4 * 12000), 4)
    assert s["by_tool"][0]["tool"] == "claude-code"
    assert d["summary"]["sessions"] == 1 and d["summary"]["projects"] == 1
    assert d["top"][0]["handle"] == "h_abc123" and d["top"][0]["saved"] == 8960
    assert d["passthroughs"][0]["orig_tokens"] == 4400
    assert d["models"][0]["model"] == "claude-sonnet-5"
    assert d["signals"]["judged"] == 1 and d["signals"]["domains"] == {"code": 1}
    assert d["sessions"][0]["tool"] == "claude-code"


def test_the_window_actually_narrows_the_window(served):
    client, _ = served
    wide = client.get("/api/overview?since=7d").json()["stats"]["requests"]
    narrow = client.get("/api/overview?since=2h").json()["stats"]["requests"]
    assert wide == 4 and narrow < wide


def test_a_nonsense_window_falls_back_instead_of_failing(served):
    client, _ = served
    assert client.get("/api/overview?since=banana").status_code == 200


# ---------------------------------------------------------------- what it refuses
@pytest.mark.parametrize("host", ["evil.example.com", "evil.example.com:8080", "10.0.0.4:80"])
def test_a_name_that_merely_resolves_here_is_turned_away(served, host):
    """DNS rebinding: the socket is loopback, but the browser still sends the real name.

    Same-origin does not cover this -- the attacker's page and the rebound address share an
    origin by the time the request is made. Comparing the Host header is what separates them.
    """
    client, _ = served
    assert client.get("/", headers={"host": host}).status_code == 403
    assert client.get("/api/overview", headers={"host": host}).status_code == 403


@pytest.mark.parametrize("host", ["localhost:9", "127.0.0.1:7777", "[::1]:900", "127.2.3.4:1"])
def test_this_machine_is_let_through_under_every_spelling_of_itself(served, host):
    client, _ = served
    assert client.get("/", headers={"host": host}).status_code == 200


def test_host_is_local_does_not_crash_on_junk():
    for junk in ("", ":", "::::", "[", "]:80", "not a host at all"):
        assert web.host_is_local(junk) is False


# ------------------------------------------------------------------ mount points
def test_the_proxy_serves_the_same_page_under_its_own_prefix(home):
    led = _seed(home)
    try:
        app = Starlette(routes=[])
        from tokunseba.ui.api import mount_ui
        mount_ui(app, led, config.load())
        client = _client(app)
        assert client.get("/_tokunseba/").status_code == 200
        assert client.get("/_tokunseba/api/overview").status_code == 200
        # Without the trailing slash the page's relative fetch would resolve to the root.
        r = client.get("/_tokunseba", follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"].endswith("/_tokunseba/")
        # The older per-view endpoints are still there for the status line.
        assert client.get("/_tokunseba/api/stats").status_code == 200
    finally:
        led.close()


# -------------------------------------------------------------------- the command
def test_print_url_points_at_the_proxy_when_one_is_running(home, monkeypatch):
    monkeypatch.setattr("tokunseba.service.running", lambda port: True)
    r = CliRunner().invoke(main, ["dashboard", "--print-url"])
    assert r.exit_code == 0 and "/_tokunseba/" in r.output


def test_print_url_says_so_rather_than_printing_a_dead_address(home, monkeypatch):
    monkeypatch.setattr("tokunseba.service.running", lambda port: False)
    r = CliRunner().invoke(main, ["dashboard", "--print-url"])
    assert r.exit_code == 1 and "not running" in r.output


def test_the_command_never_opens_a_browser_when_told_not_to(home, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    served = {}
    monkeypatch.setattr(web, "serve",
                        lambda led, cfg, port, host="127.0.0.1": served.update(port=port, host=host))
    r = CliRunner().invoke(main, ["dashboard", "--no-open", "--port", "8123"])
    assert r.exit_code == 0 and opened == []
    assert served == {"port": 8123, "host": "127.0.0.1"}, "it must bind loopback only"
    assert "127.0.0.1:8123" in " ".join(r.output.split())


def test_it_opens_a_browser_by_default_at_the_address_it_printed(home, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    monkeypatch.setattr(web, "serve", lambda *a, **k: None)
    r = CliRunner().invoke(main, ["dashboard", "--port", "8124"])
    assert r.exit_code == 0 and opened == ["http://127.0.0.1:8124/"]


def test_a_taken_port_is_reported_rather_than_swallowed(home, monkeypatch):
    monkeypatch.setattr("webbrowser.open", lambda url: None)

    def boom(*a, **k):
        raise OSError("address already in use")
    monkeypatch.setattr(web, "serve", boom)
    r = CliRunner().invoke(main, ["dashboard", "--port", "8125"])
    assert r.exit_code == 1 and "Could not listen" in r.output


def test_free_port_asks_the_operating_system_instead_of_picking_a_number():
    """Deliberately not re-bound here.

    Between `free_port` returning and anything binding, another process on the machine can
    take that port, and on a busy CI runner it sometimes does. That race is real and it is
    why `dashboard --port` exists; it is not a property this test can assert without
    failing for reasons that have nothing to do with the code.
    """
    p = web.free_port()
    assert isinstance(p, int) and 1024 < p <= 65535
