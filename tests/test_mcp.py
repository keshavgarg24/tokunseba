"""The MCP expand tool is how an agent without a shell recovers deferred content.

These run only when the `mcp` extra is installed.
"""
import pytest

pytest.importorskip("mcp")

from tokunseba.hooks.mcp_server import build_server, expand_handle  # noqa: E402
from tokunseba.transform.handles import HandleStore  # noqa: E402


def test_expand_handle_roundtrip(home):
    from tokunseba.config import home as th
    h = HandleStore(th() / "blobs").put("full original\nsecond line")
    assert expand_handle(h) == "full original\nsecond line"


def test_expand_handle_unknown(home):
    assert expand_handle("h_nope") == "unknown handle h_nope"


def test_server_exposes_exactly_the_expand_tool(home):
    import asyncio
    tools = asyncio.run(build_server().list_tools())
    assert [t.name for t in tools] == ["expand"]
    assert "tokunseba expand" in tools[0].description


def test_server_call_returns_the_original(home):
    import asyncio
    from tokunseba.config import home as th
    h = HandleStore(th() / "blobs").put("recovered content here")
    res = asyncio.run(build_server().call_tool("expand", {"handle": h}))
    assert "recovered content here" in res.content[0].text
    assert not res.is_error


def test_server_call_handles_an_unknown_handle(home):
    import asyncio
    res = asyncio.run(build_server().call_tool("expand", {"handle": "h_missing00000"}))
    assert "unknown handle" in res.content[0].text


def test_main_reports_how_to_install_when_the_sdk_is_absent(home, monkeypatch, capsys):
    import tokunseba.hooks.mcp_server as m

    def no_sdk():
        raise ImportError("no mcp")
    monkeypatch.setattr(m, "_server_class", no_sdk)
    assert m.main() == 2
    assert "tokunseba[mcp]" in capsys.readouterr().err
