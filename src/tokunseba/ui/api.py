"""Local JSON endpoints, and the browser dashboard, bound to loopback and never public.

The terminal remains the default surface: `tokunseba ui` needs no browser and no port. The
page mounted here is the same view for people who would rather leave it open on a second
screen, and it is served by the proxy only because the proxy is already listening -- see
`tokunseba.ui.web` for what it does and does not allow.
"""
from __future__ import annotations

import time

from starlette.responses import JSONResponse
from starlette.routing import Route



def parse_since(s: str) -> float:
    s = (s or "7d").strip()
    units = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
    try:
        if s[-1] in units:
            return time.time() - float(s[:-1]) * units[s[-1]]
        return time.time() - float(s)
    except (ValueError, IndexError):
        return time.time() - 7 * 86400


def mount_ui(app, ledger, cfg) -> None:
    async def stats(request):
        return JSONResponse(ledger.stats(parse_since(request.query_params.get("since", "7d")),
                                         request.query_params.get("project") or None))

    async def events(request):
        return JSONResponse(ledger.events(request.query_params.get("kind") or None,
                                          int(request.query_params.get("limit", 200))))

    async def sessions(request):
        return JSONResponse(ledger.recent_sessions(int(request.query_params.get("limit", 50))))

    async def daily(request):
        return JSONResponse(ledger.daily(int(request.query_params.get("days", 14))))

    async def ab(request):
        return JSONResponse(ledger.stats_ab(parse_since(request.query_params.get("since", "30d"))))

    for path, fn in (("/_tokunseba/api/stats", stats), ("/_tokunseba/api/events", events),
                     ("/_tokunseba/api/sessions", sessions), ("/_tokunseba/api/daily", daily),
                     ("/_tokunseba/api/ab", ab)):
        app.router.routes.insert(0, Route(path, fn, methods=["GET"]))
    from .web import routes as web_routes
    for route in web_routes(ledger, cfg, "/_tokunseba"):
        app.router.routes.insert(0, route)
