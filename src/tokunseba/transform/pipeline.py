"""Transform orchestration.

Two rules govern everything here:
  - Only content new in this request is ever transformed (delta-only).
  - A given original always maps to the same replacement, forever (frozen table),
    so re-sent history stays byte-identical and the prompt cache survives.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..ledger import Ledger, TransformRow
from ..protocols.base import NormalizedRequest, json_set, sha256_text
from . import canonical, dedup, encodings, junk, summarize
from .handles import HandleStore
from .table import FrozenTable


@dataclass
class Applied:
    position: str
    kind: str
    before: int
    after: int
    handle: str


@dataclass
class PipelineResult:
    body: dict
    applied: list[Applied] = field(default_factory=list)
    tokens_before: int = 0
    tokens_after: int = 0

    @property
    def saved(self) -> int:
        return max(self.tokens_before - self.tokens_after, 0)


class Pipeline:
    def __init__(self, cfg, ledger: Ledger, handles: HandleStore, estimator, pre_store=None):
        self.cfg = cfg
        self.ledger = ledger
        self.handles = handles
        self.est = estimator
        self.table = FrozenTable(ledger)
        self.pre_store = pre_store or (lambda _text: True)

    # --- helpers ---
    def _store(self, text: str) -> tuple[str, bool]:
        """Return (handle, allowed). Never writes a blob that holds a detected secret."""
        if not self.pre_store(text):
            return "", False
        return self.handles.put(text), True

    def _footer(self, text: str, kept: str, provider: str, model: str) -> str:
        handle, ok = self._store(text)
        if not ok:
            return HandleStore.blocked_footer()
        omitted_lines = max(text.count("\n") - kept.count("\n"), 0)
        omitted_tokens = max(self.est.count(text, provider, model) - self.est.count(kept, provider, model), 0)
        return HandleStore.footer(handle, omitted_lines, omitted_tokens)

    def _truncate_limit(self, provider: str) -> tuple[int, int]:
        t = self.cfg.thresholds
        if provider == "ollama":
            return t.truncate_lines, t.local_truncate_tokens
        return t.truncate_lines, t.truncate_tokens

    # --- the transform decision, made once per unique original ---
    def _transform(self, norm: NormalizedRequest, msg_index: int, block, orig: str,
                   sha: str, key: str, orig_tokens: int, ref, rr) -> TransformRow:
        provider, model = norm.provider, norm.model
        path = dedup.path_of(norm, block)
        reach = self.cfg.reach_preserving

        # 1. lossless cleanup first, so ANSI colour codes are not mistaken for binary content
        text = canonical.canonicalize(orig)

        # 2. junk files never earn their tokens
        label = junk.detect(path, text)
        if label and reach:
            handle, ok = self._store(orig)
            summary = junk.summary(label, path, text, handle if ok else "unavailable")
            return TransformRow(key, f"junk:{label}", summary, orig_tokens,
                                self.est.count(summary, provider, model), handle if ok else "", "")

        # 3. an identical earlier result needs only a pointer, but only when the pointer
        #    is genuinely cheaper than the thing it replaces
        if ref:
            idx, ref_sha = ref
            handle, ok = self._store(orig)
            rtext = dedup.reference_text(idx, handle if ok else "unavailable")
            rtokens = self.est.count(rtext, provider, model)
            if rtokens < self.est.count(text, provider, model):
                return TransformRow(key, "dedup_ref", rtext, orig_tokens, rtokens,
                                    handle if ok else "", ref_sha)

        # 4. a re-read after an edit needs only the diff
        if rr and path:
            idx, ref_sha, earlier = rr
            handle, ok = self._store(orig)
            d = dedup.make_diff(earlier, text, path, idx, handle if ok else "unavailable")
            if d:
                return TransformRow(key, "diff_ref", d, orig_tokens,
                                    self.est.count(d, provider, model), handle if ok else "", ref_sha)

        # 5. structural summary of program output, with a handle to the rest
        if reach:
            tool_name = None
            command = None
            tu = norm.tool_use_index.get(block.tool_use_id) if block.tool_use_id else None
            if tu:
                tool_name = tu.tool_name
                if isinstance(tu.tool_input, dict):
                    c = tu.tool_input.get("command")
                    command = c if isinstance(c, str) else None
            kind_label, _conf = summarize.detect_type(text, tool_name, command)
            kept, omitted = summarize.summarize(kind_label, text)
            if omitted > 0:
                kept = kept.rstrip("\n") + "\n" + self._footer(text, kept, provider, model)
                return TransformRow(key, f"summary:{kind_label}", kept, orig_tokens,
                                    self.est.count(kept, provider, model), self._handle_of(text), "")

        # 6. a cheaper encoding, only if the tokenizer agrees it is cheaper
        encoded, ekind = encodings.best(text, lambda s: self.est.count(s, provider, model))
        if ekind != "none":
            return TransformRow(key, f"encoding:{ekind}", encoded, orig_tokens,
                                self.est.count(encoded, provider, model), "", "")

        # 7. last resort: keep the head and the tail, defer the middle
        max_lines, max_tokens = self._truncate_limit(provider)
        cur_tokens = self.est.count(text, provider, model)
        lines = text.split("\n")
        if reach and (cur_tokens > max_tokens or len(lines) > max_lines):
            head_n = int(max_lines * 0.6)
            tail_n = max_lines - head_n
            kept = "\n".join(lines[:head_n]) + "\n{FOOTER}\n" + "\n".join(lines[-tail_n:])
            footer = self._footer(text, kept.replace("{FOOTER}", ""), provider, model)
            kept = kept.replace("{FOOTER}", footer)
            return TransformRow(key, "truncate", kept, orig_tokens,
                                self.est.count(kept, provider, model), self._handle_of(text), "")

        kind = "canonical" if text != orig else "passthrough"
        return TransformRow(key, kind, text, orig_tokens, self.est.count(text, provider, model), "", "")

    def _handle_of(self, text: str) -> str:
        if not self.pre_store(text):
            return ""
        return self.handles.put(text)

    def _materialize(self, norm: NormalizedRequest, msg_index: int, row: TransformRow, orig: str) -> str:
        """A stored reference is only valid while the thing it points at is still in this request."""
        if row.kind in ("dedup_ref", "diff_ref") and row.ref_sha:
            if dedup.find_reference(norm, msg_index, row.ref_sha) is None:
                self.ledger.record_event("ref_dangling", {"kind": row.kind, "ref_sha": row.ref_sha[:12]})
                return canonical.canonicalize(orig)
        return row.transformed

    # --- entry point ---
    def _key(self, sha: str, ref, rr) -> str:
        """Content addresses the transform, but a reference also depends on what it points at.

        Including the referenced position keeps the key stable across turns (history is
        append-only) while stopping two copies of the same bytes from colliding.
        """
        if ref:
            return f"{sha}@same{ref[0]}"
        if rr:
            return f"{sha}@diff{rr[0]}"
        return sha

    def apply(self, norm: NormalizedRequest, body: dict, delta_start: int,
              session_id: str, request_id: str) -> PipelineResult:
        res = PipelineResult(body=body)
        if not self.cfg.lossless:
            return res
        for i, msg in enumerate(norm.messages):
            for blk in msg.blocks:
                if blk.kind != "tool_result" or not blk.text:
                    continue
                orig = blk.text
                sha = sha256_text(orig)
                ob = self.est.count(orig, norm.provider, norm.model)
                res.tokens_before += ob
                ref = dedup.find_reference(norm, i, sha)
                rr = None if ref else dedup.find_reread(norm, i, blk)
                key = self._key(sha, ref, rr)
                row = self.table.get(key)
                if row is None:
                    if i < delta_start:
                        # already sent in an earlier turn: never rewrite history, never
                        # record it either, or a later identical block would inherit it
                        res.tokens_after += ob
                        continue
                    row = self._transform(norm, i, blk, orig, sha, key, ob, ref, rr)
                    row = self.table.put(row)
                text = self._materialize(norm, i, row, orig)
                if text != orig:
                    json_set(body, blk.path, text)
                    res.applied.append(Applied(str(blk.path), row.kind, row.orig_tokens,
                                               row.new_tokens, row.handle))
                    self.ledger.link_transform(request_id, key, str(blk.path),
                                               max(row.orig_tokens - row.new_tokens, 0))
                res.tokens_after += self.est.count(text, norm.provider, norm.model)
        return res
