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


def test_static_page_exists_and_is_self_contained():
    from tokunseba.ui.api import STATIC
    html = (STATIC / "index.html").read_text()
    assert "<title>tokunseba</title>" in html
    assert "_tokunseba/api/stats" in html
    assert "http://" not in html.replace("http://www.apple.com", "")  # no external assets


async def test_dashboard_page_is_served(client):
    r = await client.get("/_tokunseba/")
    assert r.status_code == 200 and "tokunseba" in r.text
