"""Housekeeping: keep the history the user asked for and no more."""
from __future__ import annotations

import time
from pathlib import Path

STAMP = "last_prune"


def due(ledger, every_seconds: float = 86400.0) -> bool:
    last = ledger.kv_get(STAMP, 0)
    try:
        return (time.time() - float(last)) >= every_seconds
    except (TypeError, ValueError):
        return True


def run(cfg, ledger, home: Path) -> dict:
    """Prune to the configured window. Returns what was removed."""
    out = {"rows": 0, "blobs": 0, "bodies": 0, "skipped": False}
    if cfg.retention.days <= 0:
        out["skipped"] = True
        return out

    out["rows"] = ledger.prune(cfg.retention.days)

    from .transform.handles import HandleStore
    out["blobs"] = HandleStore(home / "blobs").prune(ledger.live_handles())

    body_days = cfg.retention.keep_bodies_days or cfg.retention.days
    cutoff = time.time() - body_days * 86400
    bodies = home / "bodies"
    if bodies.exists():
        for f in bodies.iterdir():
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
                    out["bodies"] += 1
            except OSError:
                continue
    ledger.kv_set(STAMP, time.time())
    return out


def maybe_run(cfg, ledger, home: Path) -> dict | None:
    """Prune at most once a day, and only when the user left auto_prune on."""
    if not cfg.retention.auto_prune or not due(ledger):
        return None
    try:
        return run(cfg, ledger, home)
    except Exception:  # noqa: BLE001 - housekeeping must never stop the proxy
        return None
