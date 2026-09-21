"""Upstream HTTP plumbing. Auth headers are forwarded exactly as received and never stored."""
from __future__ import annotations

import httpx

HOP = {"host", "content-length", "connection", "accept-encoding", "transfer-encoding",
       "keep-alive", "upgrade", "proxy-connection", "te", "trailer"}
RESP_DROP = {"content-length", "content-encoding", "transfer-encoding", "connection", "keep-alive"}


def make_client(transport=None) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport,
                             timeout=httpx.Timeout(600.0, connect=15.0),
                             follow_redirects=False)


def forward_headers(headers) -> dict:
    out = {k: v for k, v in headers.items() if k.lower() not in HOP}
    out["accept-encoding"] = "identity"
    return out


def passthrough_headers(headers) -> dict:
    return {k: v for k, v in headers.items() if k.lower() not in RESP_DROP}
