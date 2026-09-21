"""Local model context windows.

A cloud model refuses an over-long request. A local server usually truncates the front of it
silently, which changes the answer. Knowing the window lets tokunseba make the request fit
instead of letting the server quietly drop the beginning.
"""
from __future__ import annotations

DEFAULT_CONTEXT = 8192
HEADROOM = 1024


async def context_length(client, base_url: str, model: str, ledger) -> int:
    key = f"ctx/{model}"
    cached = ledger.kv_get(key)
    if isinstance(cached, int) and cached > 0:
        return cached
    length = DEFAULT_CONTEXT
    try:
        r = await client.post(base_url.rstrip("/") + "/api/show", json={"model": model}, timeout=5.0)
        if r.status_code < 300:
            info = (r.json() or {}).get("model_info") or {}
            arch = info.get("general.architecture")
            if arch and f"{arch}.context_length" in info:
                length = int(info[f"{arch}.context_length"])
            else:
                for k, v in info.items():
                    if k.endswith(".context_length") and isinstance(v, int):
                        length = v
                        break
    except Exception:  # noqa: BLE001 - never let a probe break a request
        pass
    ledger.kv_set(key, length)
    return length


def request_budget(norm, body: dict, limit: int) -> int:
    opts = body.get("options")
    if isinstance(opts, dict) and isinstance(opts.get("num_ctx"), int):
        limit = opts["num_ctx"]
    return max(limit - HEADROOM, 512)
