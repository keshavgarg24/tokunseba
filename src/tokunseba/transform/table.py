"""The frozen transform table.

A harness re-sends the whole conversation every turn. If the same original bytes ever produced
two different replacements, the cached prefix would break and cost more than the compression saved.
So a transformation is keyed by the hash of its original and never recomputed.
"""
from __future__ import annotations

from ..ledger import Ledger, TransformRow


class FrozenTable:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    def get(self, sha: str) -> TransformRow | None:
        return self.ledger.get_transform(sha)

    def put(self, row: TransformRow) -> TransformRow:
        self.ledger.put_transform(row)
        return self.ledger.get_transform(row.orig_sha) or row
