"""SQLite ledger: every request, transform, event and session. Local file, no telemetry."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests(
  id TEXT PRIMARY KEY, ts REAL, session_id TEXT, tool_id TEXT, project TEXT,
  provider TEXT, model TEXT, stream INTEGER,
  input_tokens INTEGER, cache_read INTEGER, cache_write INTEGER, output_tokens INTEGER,
  est_tokens_before INTEGER, est_tokens_after INTEGER,
  cost_usd REAL, counterfactual_usd REAL, arm TEXT, status INTEGER, latency_ms INTEGER, body_path TEXT);
CREATE TABLE IF NOT EXISTS transforms(
  orig_sha TEXT PRIMARY KEY, kind TEXT, transformed TEXT, orig_tokens INTEGER, new_tokens INTEGER,
  handle TEXT, ref_sha TEXT, created REAL);
CREATE TABLE IF NOT EXISTS request_transforms(request_id TEXT, orig_sha TEXT, position TEXT, saved_tokens INTEGER);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, session_id TEXT, request_id TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS sessions(
  id TEXT PRIMARY KEY, started REAL, last_seen REAL, tool_id TEXT, project TEXT,
  provider TEXT, model TEXT, arm TEXT);
CREATE TABLE IF NOT EXISTS tool_sessions(session_id TEXT PRIMARY KEY, tool TEXT, cwd TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS idx_requests_ts ON requests(ts);
CREATE INDEX IF NOT EXISTS idx_requests_session ON requests(session_id);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind, ts);
CREATE INDEX IF NOT EXISTS idx_transforms_created ON transforms(created);
"""


@dataclass
class RequestRecord:
    id: str
    ts: float
    session_id: str
    tool_id: str
    project: str
    provider: str
    model: str
    stream: bool
    input_tokens: int
    cache_read: int
    cache_write: int
    output_tokens: int
    est_tokens_before: int
    est_tokens_after: int
    cost_usd: float
    counterfactual_usd: float
    arm: str
    status: int
    latency_ms: int
    body_path: str


@dataclass
class TransformRow:
    orig_sha: str
    kind: str
    transformed: str
    orig_tokens: int
    new_tokens: int
    handle: str
    ref_sha: str


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # --- writes ---
    def record_request(self, r: RequestRecord) -> None:
        d = asdict(r)
        d["stream"] = int(r.stream)
        cols = ",".join(d)
        qs = ",".join("?" * len(d))
        with self._lock:
            self._conn.execute(f"INSERT OR REPLACE INTO requests({cols}) VALUES({qs})", list(d.values()))
            self._conn.commit()

    def record_event(self, kind: str, payload: dict, session_id: str | None = None,
                     request_id: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events(ts,kind,session_id,request_id,payload) VALUES(?,?,?,?,?)",
                (time.time(), kind, session_id, request_id, json.dumps(payload, default=str)),
            )
            self._conn.commit()

    def put_transform(self, t: TransformRow) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO transforms VALUES(?,?,?,?,?,?,?,?)",
                (t.orig_sha, t.kind, t.transformed, t.orig_tokens, t.new_tokens, t.handle, t.ref_sha, time.time()),
            )
            self._conn.commit()

    def link_transform(self, request_id: str, sha: str, position: str, saved: int) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO request_transforms VALUES(?,?,?,?)",
                               (request_id, sha, position, saved))
            self._conn.commit()

    def upsert_session(self, id: str, tool_id: str, project: str, provider: str, model: str, arm: str) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                """INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen, model=excluded.model,
                   project=CASE WHEN excluded.project<>'' THEN excluded.project ELSE sessions.project END""",
                (id, now, now, tool_id, project, provider, model, arm),
            )
            self._conn.commit()

    def register_tool_session(self, session_id: str, tool: str, cwd: str) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO tool_sessions VALUES(?,?,?,?)",
                               (session_id, tool, cwd, time.time()))
            self._conn.commit()

    def kv_set(self, key: str, value) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (key, json.dumps(value)))
            self._conn.commit()

    # --- reads ---
    def get_transform(self, sha: str) -> TransformRow | None:
        row = self._conn.execute(
            "SELECT orig_sha,kind,transformed,orig_tokens,new_tokens,handle,ref_sha FROM transforms WHERE orig_sha=?",
            (sha,),
        ).fetchone()
        return TransformRow(*row) if row else None

    def kv_get(self, key: str, default=None):
        row = self._conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def session_arm(self, session_id: str) -> str:
        row = self._conn.execute("SELECT arm FROM sessions WHERE id=?", (session_id,)).fetchone()
        return row[0] if row else ""

    def recent_cwd(self, tool: str, within_seconds: float = 600.0) -> str:
        row = self._conn.execute(
            "SELECT cwd FROM tool_sessions WHERE tool=? AND ts>=? ORDER BY ts DESC LIMIT 1",
            (tool, time.time() - within_seconds),
        ).fetchone()
        return row[0] if row else ""

    def cwd_for_session(self, session_id: str) -> str:
        row = self._conn.execute("SELECT cwd FROM tool_sessions WHERE session_id=?", (session_id,)).fetchone()
        return row[0] if row else ""

    def tool_session_ids(self, within_seconds: float = 86400.0) -> list[str]:
        return [r[0] for r in self._conn.execute(
            "SELECT session_id FROM tool_sessions WHERE ts>=?", (time.time() - within_seconds,))]

    def spend_since(self, since_ts: float, project: str | None = None) -> float:
        where, args = "ts>=?", [since_ts]
        if project:
            where += " AND project=?"
            args.append(project)
        row = self._conn.execute(f"SELECT COALESCE(SUM(cost_usd),0) FROM requests WHERE {where}", args).fetchone()
        return float(row[0])

    def events(self, kind: str | None = None, limit: int = 200) -> list[dict]:
        if kind:
            rows = self._conn.execute(
                "SELECT ts,kind,session_id,request_id,payload FROM events WHERE kind=? ORDER BY ts DESC LIMIT ?",
                (kind, limit)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT ts,kind,session_id,request_id,payload FROM events ORDER BY ts DESC LIMIT ?",
                (limit,)).fetchall()
        return [{"ts": t, "kind": k, "session_id": s, "request_id": r, "payload": json.loads(p or "{}")}
                for t, k, s, r, p in rows]

    def recent_sessions(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            """SELECT s.id, s.last_seen, s.tool_id, s.project, s.model, s.arm,
                      COUNT(r.id), COALESCE(SUM(r.est_tokens_before-r.est_tokens_after),0),
                      COALESCE(SUM(r.cost_usd),0)
               FROM sessions s LEFT JOIN requests r ON r.session_id=s.id
               GROUP BY s.id ORDER BY s.last_seen DESC LIMIT ?""", (limit,)).fetchall()
        return [{"id": a, "last_seen": b, "tool": c, "project": d, "model": e, "arm": f,
                 "requests": g, "tokens_saved": h, "usd": round(i, 4)} for a, b, c, d, e, f, g, h, i in rows]

    def transforms_for(self, request_id: str) -> list[dict]:
        rows = self._conn.execute(
            """SELECT rt.position, t.kind, t.orig_tokens, t.new_tokens, t.handle, t.orig_sha, t.transformed
               FROM request_transforms rt JOIN transforms t ON t.orig_sha=rt.orig_sha
               WHERE rt.request_id=?""", (request_id,)).fetchall()
        return [{"position": a, "kind": b, "orig_tokens": c, "new_tokens": d,
                 "handle": e, "orig_sha": f, "transformed": g} for a, b, c, d, e, f, g in rows]

    def daily(self, days: int = 14) -> list[dict]:
        since = time.time() - days * 86400
        rows = self._conn.execute(
            """SELECT CAST(ts/86400 AS INTEGER) d, COALESCE(SUM(est_tokens_before-est_tokens_after),0),
                      COALESCE(SUM(cost_usd),0), COALESCE(SUM(counterfactual_usd-cost_usd),0), COUNT(*)
               FROM requests WHERE ts>=? GROUP BY d ORDER BY d""", (since,)).fetchall()
        return [{"day": int(d * 86400), "tokens_saved": s, "usd_spent": round(c, 4),
                 "usd_saved": round(v, 4), "requests": n} for d, s, c, v, n in rows]

    def stats(self, since_ts: float, project: str | None = None) -> dict:
        where, args = "ts>=?", [since_ts]
        if project:
            where += " AND project=?"
            args.append(project)
        row = self._conn.execute(
            f"""SELECT COUNT(*), COALESCE(SUM(input_tokens+cache_read+cache_write),0),
                COALESCE(SUM(output_tokens),0), COALESCE(SUM(est_tokens_before-est_tokens_after),0),
                COALESCE(SUM(cost_usd),0), COALESCE(SUM(counterfactual_usd-cost_usd),0),
                COALESCE(SUM(cache_read),0), COALESCE(SUM(est_tokens_before),0)
                FROM requests WHERE {where}""", args).fetchone()
        events = dict(self._conn.execute(
            "SELECT kind, COUNT(*) FROM events WHERE ts>=? GROUP BY kind ORDER BY 2 DESC", (since_ts,)).fetchall())
        by_tool = self._conn.execute(
            f"""SELECT tool_id, COUNT(*), COALESCE(SUM(est_tokens_before-est_tokens_after),0),
                COALESCE(SUM(cost_usd),0) FROM requests WHERE {where} GROUP BY tool_id ORDER BY 3 DESC""",
            args).fetchall()
        total_in, before = row[1], row[7]
        return {
            "requests": row[0], "input_tokens": total_in, "output_tokens": row[2],
            "tokens_saved": row[3], "usd_spent": round(row[4], 4), "usd_saved": round(row[5], 4),
            "cache_read": row[6],
            "cache_hit_rate": (row[6] / total_in) if total_in else 0.0,
            "pct_saved": (row[3] / before) if before else 0.0,
            "events": events,
            "by_tool": [{"tool": t, "requests": n, "tokens_saved": s, "usd": round(c, 4)}
                        for t, n, s, c in by_tool],
        }

    def stats_ab(self, since_ts: float) -> dict:
        rows = self._conn.execute(
            """SELECT arm, COUNT(DISTINCT session_id), COUNT(*),
                      COALESCE(SUM(input_tokens+cache_read+cache_write),0),
                      COALESCE(SUM(output_tokens),0), COALESCE(SUM(cost_usd),0)
               FROM requests WHERE ts>=? AND arm<>'' GROUP BY arm""", (since_ts,)).fetchall()
        out = {}
        for arm, sess, reqs, inp, outp, usd in rows:
            s = max(sess, 1)
            out[arm] = {"sessions": sess, "requests": reqs,
                        "requests_per_session": round(reqs / s, 2),
                        "input_tokens_per_session": round(inp / s, 1),
                        "output_tokens_per_session": round(outp / s, 1),
                        "usd_per_session": round(usd / s, 5)}
        return out

    def prune(self, days: int = 30) -> int:
        cutoff = time.time() - days * 86400
        with self._lock:
            cur = self._conn.execute("DELETE FROM requests WHERE ts<?", (cutoff,))
            n = cur.rowcount
            self._conn.execute("DELETE FROM events WHERE ts<?", (cutoff,))
            self._conn.execute("DELETE FROM transforms WHERE created<?", (cutoff,))
            self._conn.execute("DELETE FROM tool_sessions WHERE ts<?", (cutoff,))
            self._conn.commit()
        return n

    def live_handles(self) -> set[str]:
        return {r[0] for r in self._conn.execute("SELECT handle FROM transforms WHERE handle<>''")}

    def close(self) -> None:
        self._conn.close()
