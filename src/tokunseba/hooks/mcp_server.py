"""MCP server exposing `expand`, for agents that have no shell.

Nothing tokunseba shortens is ever lost; it is replaced by a handle. An agent with a shell
runs `tokunseba expand <handle>`. An agent without one calls this tool instead.

Supports both MCP SDK generations: 2.x renamed FastMCP to MCPServer, and an agent running
an older host may still have 1.x installed.
"""
from __future__ import annotations

import sys

from ..config import home
from ..transform.handles import HandleStore

INSTALL_HINT = "install with: uv tool install 'tokunseba[mcp]'"
DESCRIPTION = (
    "Return the full original text that tokunseba replaced with a handle. "
    "Use it whenever you see a line like "
    "'[tokunseba: N lines omitted. Full output: run `tokunseba expand h_...`]' "
    "and you need the part that was left out."
)


def expand_handle(handle: str) -> str:
    text = HandleStore(home() / "blobs").get(handle)
    return text if text is not None else f"unknown handle {handle}"


def _server_class():
    """MCP 2.x first, then the 1.x name."""
    try:
        from mcp.server.mcpserver import MCPServer
        return MCPServer
    except ImportError:
        from mcp.server.fastmcp import FastMCP
        return FastMCP


def build_server():
    server = _server_class()("tokunseba")

    @server.tool(description=DESCRIPTION)
    def expand(handle: str) -> str:
        return expand_handle(handle)

    return server


def main() -> int:
    try:
        server = build_server()
    except ImportError:
        print(INSTALL_HINT, file=sys.stderr)
        return 2
    server.run()
    return 0
