"""Content-addressed blob store. Nothing is ever lost, only deferred behind a handle the model can expand."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class HandleStore:
    def __init__(self, dir: Path):
        self.dir = Path(dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            self.dir.chmod(0o700)
        except OSError:
            pass
        self.index_path = self.dir / "index.json"

    def _index(self) -> dict:
        if not self.index_path.exists():
            return {}
        try:
            return json.loads(self.index_path.read_text())
        except ValueError:
            return {}

    def put(self, text: str) -> str:
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        handle = f"h_{sha[:12]}"
        blob = self.dir / sha
        if not blob.exists():
            blob.write_text(text)
            try:
                blob.chmod(0o600)
            except OSError:
                pass
        idx = self._index()
        if idx.get(handle) != sha:
            idx[handle] = sha
            self.index_path.write_text(json.dumps(idx))
            try:
                self.index_path.chmod(0o600)
            except OSError:
                pass
        return handle

    def get(self, handle: str) -> str | None:
        sha = self._index().get(handle)
        if not sha:
            return None
        blob = self.dir / sha
        return blob.read_text() if blob.exists() else None

    def prune(self, live_handles: set[str]) -> int:
        idx = self._index()
        removed = 0
        keep_shas = {sha for h, sha in idx.items() if h in live_handles}
        for h in list(idx):
            if h not in live_handles:
                idx.pop(h)
        for blob in self.dir.iterdir():
            if blob.name == "index.json" or blob.name in keep_shas:
                continue
            blob.unlink(missing_ok=True)
            removed += 1
        self.index_path.write_text(json.dumps(idx))
        return removed

    @staticmethod
    def footer(handle: str, omitted_lines: int, omitted_tokens: int) -> str:
        return (f"[tokunseba: {omitted_lines} lines / ~{omitted_tokens} tokens omitted. "
                f"Full output: run `tokunseba expand {handle}`]")

    @staticmethod
    def blocked_footer() -> str:
        return "[tokunseba: full output not stored because it contains a detected secret]"
