"""Local JSON endpoints for the status line. Bound to localhost, never public.

There is deliberately no web page: the dashboard lives in the terminal (`tokunseba ui`).
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
    async def hint(request):
        return JSONResponse({"tokunseba": "this is a local JSON API; the dashboard is "
                                          "in your terminal: run `tokunseba ui`"})

    app.router.routes.insert(0, Route("/_tokunseba/", hint, methods=["GET"]))
    app.router.routes.insert(0, Route("/_tokunseba", hint, methods=["GET"]))
