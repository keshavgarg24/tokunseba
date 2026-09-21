"""MCP server exposing a single tool: expand a tokunseba handle back to text.

Whenever tokunseba hides output behind a handle it leaves the handle in view.
An agent speaking MCP can call ``expand`` to get the omitted text back without
shelling out. The ``mcp`` dependency is optional, so it is imported lazily and
this module stays importable without the extra installed.
"""

from __future__ import annotations

import sys

from ..config import home
from ..transform.handles import HandleStore

__all__ = ["build_server", "main"]

_INSTALL_HINT = 'install with: uv tool install "tokunseba[mcp]"'


def build_server():
    """Create the FastMCP server. Raises ImportError without the ``mcp`` extra."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("tokunseba")

    @server.tool()
    def expand(handle: str) -> str:
        """Return the full original text that tokunseba replaced with this handle."""
        text = HandleStore(home() / "blobs").get(handle)
        return text if text is not None else f"unknown handle {handle}"

    return server


def main() -> int:
    """Run the MCP server on stdio. Returns 2 if the ``mcp`` extra is missing."""
    try:
        server = build_server()
    except ImportError:
        print(_INSTALL_HINT, file=sys.stderr)
        return 2

    server.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
