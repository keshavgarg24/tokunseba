"""Offline what-if: re-run traffic that already happened under a configuration you have
not committed to.

Every setting in tokunseba arrives with the same question, and no README can answer it:
what would this have done to *my* work? A number measured on somebody else's repository is
not an answer, and the only other way to find out has always been to turn the thing on and
watch what happens to real requests.

The original request bodies are already on disk. So point the transform pipeline at them
with a candidate configuration, walk each conversation in the order it happened so the
prefix every decision depends on is the real one, and report what would have been
different. No network, no upstream, nothing sent anywhere.

Nothing it touches is yours. The scratch ledger and blob store live in a temporary
directory that is removed on the way out, so a replay cannot write a handle, an event, a
frozen replacement or a learned token ratio into your real history. That is the whole
point: the answer has to be free to be worth asking for.

The one thing replay will not claim is an answer. Tier 3 decides which model replies, and
no offline pass can tell you what a different model would have said, so replay stays on
the tiers whose promise is that the reply does not change. `tokunseba advise` is the
command for the other question.
"""
from __future__ import annotations

import json
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .guards import secrets
from .ledger import Ledger
from .protocols import ADAPTERS
from .session import SessionIndex
from .tokens.estimator import Estimator
from .transform.handles import HandleStore
from .transform.pipeline import Pipeline


@dataclass
class Turn:
    """One recorded request, as it went out then and as it would go out now."""
    request_id: str
    session_id: str
    model: str
    tool_id: str
    was_before: int
    was_after: int
    now_before: int = 0
    now_after: int = 0
    kinds: list[str] = field(default_factory=list)

    @property
    def was_saved(self) -> int:
        return max(self.was_before - self.was_after, 0)

    @property
    def would_save(self) -> int:
        return max(self.now_before - self.now_after, 0)

    @property
    def change(self) -> int:
        """Positive means the candidate configuration removes more from this request."""
        return self.would_save - self.was_saved


@dataclass
class Result:
    turns: list[Turn] = field(default_factory=list)
    considered: int = 0
    no_body: int = 0
    unreadable: int = 0
    by_kind: Counter = field(default_factory=Counter)

    @property
    def replayed(self) -> int:
        return len(self.turns)

    @property
    def was_saved(self) -> int:
        return sum(t.was_saved for t in self.turns)

    @property
    def would_save(self) -> int:
        return sum(t.would_save for t in self.turns)

    @property
    def change(self) -> int:
        return self.would_save - self.was_saved

    @property
    def changed(self) -> list[Turn]:
        """Only the requests the candidate configuration treats differently."""
        return [t for t in self.turns if t.change != 0]

    def biggest(self, limit: int = 10) -> list[Turn]:
        return sorted(self.changed, key=lambda t: abs(t.change), reverse=True)[:limit]


def run(cfg, rows: list[dict], bodies_dir: Path) -> Result:
    """Replay `rows`, oldest first, against `cfg`. Nothing outside the temp dir is written.

    `rows` must arrive in the order the requests happened. tokunseba may only touch what is
    new in a request, so a turn replayed before the turn it follows would look like a whole
    fresh conversation and every figure below it would be inflated.
    """
    res = Result(considered=len(rows))
    with tempfile.TemporaryDirectory(prefix="tokunseba-replay-") as tmp:
        scratch = Path(tmp)
        ledger = Ledger(scratch / "scratch.db")
        try:
            est = Estimator(ledger)
            pipeline = Pipeline(cfg, ledger, HandleStore(scratch / "blobs"), est,
                                pre_store=lambda t: not secrets.has_secret(t))
            sessions = SessionIndex()
            for row in rows:
                body = _load(bodies_dir / f"{row['id']}.orig.json", res)
                if body is None:
                    continue
                adapter = ADAPTERS.get(row.get("provider") or "")
                if adapter is None:
                    res.unreadable += 1
                    continue
                try:
                    norm = adapter.parse(body)
                    chain = norm.chain()
                    match = sessions.match(chain)
                    out = pipeline.apply(norm, body, match.prefix_len,
                                         match.session_id, row["id"])
                except Exception:  # noqa: BLE001
                    # A body recorded by an older version, or one a newer adapter no longer
                    # recognises. Skipping it is honest; failing the whole replay is not.
                    res.unreadable += 1
                    continue
                delta_chars = sum(len(b.text or "") for m in norm.messages[match.prefix_len:]
                                  for b in m.blocks)
                sessions.commit(match.session_id, row["id"], chain, delta_chars=delta_chars)
                turn = Turn(request_id=row["id"], session_id=match.session_id,
                            model=row.get("model") or "", tool_id=row.get("tool_id") or "",
                            was_before=int(row.get("est_before") or 0),
                            was_after=int(row.get("est_after") or 0),
                            now_before=out.tokens_before, now_after=out.tokens_after,
                            kinds=[a.kind for a in out.applied])
                res.by_kind.update(turn.kinds)
                res.turns.append(turn)
        finally:
            ledger.close()
    return res


def _load(path: Path, res: Result) -> dict | None:
    if not path.exists():
        res.no_body += 1
        return None
    try:
        body = json.loads(path.read_text())
    except (ValueError, OSError):
        res.unreadable += 1
        return None
    return body if isinstance(body, dict) else None
