"""The same dashboard as `tokunseba ui`, in a browser, served from this machine.

The terminal dashboard is still the default and still the one that needs nothing. This
exists because a browser can hold more on screen at once, redraw without clearing the
scrollback, and sit on a second monitor while you work. It is opt-in per invocation:
no page is served unless you ask for one.

Three properties are load-bearing and each is enforced here rather than documented:

* The socket binds to the loopback address, so nothing outside this machine can reach it.
* Every request is checked against the Host header it arrived with, which is what stops a
  page you visited from reaching in through DNS rebinding -- the browser's own origin
  rules do not cover that case.
* The page itself is one file with no external reference in it: no font host, no script
  CDN, no beacon. Unplug the network and it still renders.
"""
from __future__ import annotations

import ipaddress
import socket
import time
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

_PAGE = Path(__file__).with_name("dashboard.html")

#: The only Host values a browser may legitimately send here. A rebound DNS name resolves
#: to 127.0.0.1 but still carries the attacker's hostname in this header, so comparing it
#: is enough to tell the two apart.
_LOCAL_NAMES = frozenset({"localhost", "127.0.0.1", "[::1]", "::1", "0.0.0.0"})


def page() -> str:
    return _PAGE.read_text(encoding="utf-8")


def host_is_local(header: str) -> bool:
    """True when `header` names this machine rather than something that resolved to it."""
    host = (header or "").rsplit(":", 1)[0] if not header.startswith("[") else \
        header.split("]")[0] + "]"
    if host in _LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def parse_since(s: str) -> float:
    s = (s or "7d").strip()
    units = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
    try:
        if s[-1] in units:
            return time.time() - float(s[:-1]) * units[s[-1]]
        return time.time() - float(s)
    except (ValueError, IndexError):
        return time.time() - 7 * 86400


def overview(ledger, cfg, since: str = "7d") -> dict:
    """Everything the page draws, in one read.

    One endpoint rather than eight because the page polls: eight round trips every few
    seconds would open eight connections and take eight locks on the same sqlite file to
    answer questions that are only comparable if they were asked at the same moment.
    """
    from .. import __version__
    since_ts = parse_since(since)
    # Both of these read the machine rather than the ledger, and the dashboard is still
    # worth drawing if either one cannot answer. A page that goes blank because a health
    # probe tripped over an unusual network stack is worse than one that says less.
    try:
        from ..health import check
        problem = check(cfg, ledger).problem or ""
    except Exception:  # noqa: BLE001
        problem = ""
    try:
        from ..service import running
        up = running(cfg.port)
    except OSError:
        up = False
    return {
        "version": __version__,
        "port": cfg.port,
        "running": up,
        "problem": problem,
        "since": since,
        "stats": ledger.stats(since_ts),
        "summary": ledger.summary_counts(since_ts),
        "daily": ledger.daily(14),
        "models": ledger.models_seen(since_ts),
        "top": ledger.top_transforms(since_ts, 12),
        "passthroughs": ledger.biggest_passthroughs(since_ts, 12),
        "signals": ledger.signal_breakdown(since_ts),
        "sessions": ledger.recent_sessions(12),
    }


def routes(ledger, cfg, prefix: str = "") -> list[Route]:
    """The page and its one endpoint, ready to be mounted under `prefix`."""
    async def index(request):
        if not host_is_local(request.headers.get("host", "")):
            return Response("tokunseba serves this page to this machine only.", status_code=403)
        return HTMLResponse(page(), headers={
            # The page has no external reference; this says so to the browser as well, so
            # a future edit that adds one fails loudly instead of quietly phoning out.
            "Content-Security-Policy":
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                "img-src data:; connect-src 'self'; base-uri 'none'; form-action 'none'",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        })

    async def api(request):
        if not host_is_local(request.headers.get("host", "")):
            return JSONResponse({"error": "not served off this machine"}, status_code=403)
        return JSONResponse(overview(ledger, cfg, request.query_params.get("since", "7d")),
                            headers={"Cache-Control": "no-store"})

    async def slash(request):
        return RedirectResponse(prefix + "/", status_code=307)

    out = [Route(prefix + "/", index, methods=["GET"]),
           Route(prefix + "/api/overview", api, methods=["GET"])]
    if prefix:
        # Without this, a visit to /_tokunseba resolves the page's relative fetch against
        # the root and the dashboard comes up permanently empty.
        out.append(Route(prefix, slash, methods=["GET"]))
    return out


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(ledger, cfg, port: int, host: str = "127.0.0.1") -> None:
    """Run the dashboard on its own, without needing the proxy to be up.

    Deliberately a second process rather than a flag on the proxy: the dashboard reads the
    ledger and nothing else, so it stays useful when the proxy is stopped, and closing it
    can never take traffic down with it.
    """
    import uvicorn
    app = Starlette(routes=routes(ledger, cfg))
    uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)
