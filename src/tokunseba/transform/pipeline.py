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
from . import canonical, dedup, encodings, junk, outline, summarize
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

    def _footer(self, orig: str, text: str, kept: str, provider: str, model: str) -> str:
        """Describe what `kept` left out of `text`, behind a handle holding `orig`.

        The handle stores the untouched original, not the canonicalized `text`:
        canonicalization drops whatever a carriage return overwrote, and that is
        only a safe bet as long as the dropped bytes stay reachable.
        """
        handle, ok = self._store(orig)
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
        #    is genuinely smaller than the thing it replaces
        if ref:
            _idx, ref_sha = ref
            handle, ok = self._store(orig)
            rtext = dedup.reference_text(handle if ok else "unavailable")
            rtokens = self.est.count(rtext, provider, model)
            if rtokens < self.est.count(text, provider, model):
                return TransformRow(key, "dedup_ref", rtext, orig_tokens, rtokens,
                                    handle if ok else "", ref_sha)

        # 4. a re-read after an edit needs only the diff
        if rr and path:
            _idx, ref_sha, earlier = rr
            handle, ok = self._store(orig)
            d = dedup.make_diff(earlier, text, path, handle if ok else "unavailable")
            if d:
                return TransformRow(key, "diff_ref", d, orig_tokens,
                                    self.est.count(d, provider, model), handle if ok else "", ref_sha)

        # 5. a whole source file: keep everything that names something, fold the bodies.
        #    Before the summariser, because a summariser that does not know this is code
        #    keeps the first N lines -- which is the imports and nothing the question was
        #    about. An outline keeps every signature in the file instead, at a similar size.
        if reach:
            lang = outline.language(path, text)
            if lang:
                handle, ok = self._store(orig)
                shown, folded, bodies = outline.outline(lang, text, handle if ok else "")
                if folded:
                    shown = shown.rstrip("\n") + "\n" + outline.footer(
                        lang, folded, bodies, handle if ok else "")
                    new_tokens = self.est.count(shown, provider, model)
                    if new_tokens < self.est.count(text, provider, model):
                        return TransformRow(key, f"outline:{lang}", shown, orig_tokens,
                                            new_tokens, handle if ok else "", "")

        # 6. structural summary of program output, with a handle to the rest
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
                kept = kept.rstrip("\n") + "\n" + self._footer(orig, text, kept, provider, model)
                return TransformRow(key, f"summary:{kind_label}", kept, orig_tokens,
                                    self.est.count(kept, provider, model), self._handle_of(orig), "")

        # 7. a smaller encoding, only if the tokenizer agrees it is smaller.
        #    A table loses JSON types: null and "" both render empty, true and "true" both
        #    render true. So it carries a handle like every other shortening branch, and the
        #    saving must still clear the bar after paying for that line.
        encoded, ekind = encodings.best(text, lambda s: self.est.count(s, provider, model))
        if ekind != "none":
            handle, ok = self._store(orig)
            pointer = (f"[tokunseba: exact JSON: run `tokunseba expand {handle}`]"
                       if ok else HandleStore.blocked_footer())
            encoded = encoded + "\n" + pointer
            new_tokens = self.est.count(encoded, provider, model)
            if new_tokens < self.est.count(text, provider, model):
                return TransformRow(key, f"encoding:{ekind}", encoded, orig_tokens,
                                    new_tokens, handle if ok else "", "")

        # 8. last resort: keep the head and the tail, defer the middle
        max_lines, max_tokens = self._truncate_limit(provider)
        cur_tokens = self.est.count(text, provider, model)
        lines = text.split("\n")
        if reach and (cur_tokens > max_tokens or len(lines) > max_lines):
            kept = self._head_and_tail(text, lines, max_lines, max_tokens, cur_tokens)
            footer = self._footer(orig, text, kept.replace("{FOOTER}", ""), provider, model)
            kept = kept.replace("{FOOTER}", footer)
            return TransformRow(key, "truncate", kept, orig_tokens,
                                self.est.count(kept, provider, model), self._handle_of(orig), "")

        kind = "canonical" if text != orig else "passthrough"
        return TransformRow(key, kind, text, orig_tokens, self.est.count(text, provider, model), "", "")

    @staticmethod
    def _head_and_tail(text: str, lines: list[str], max_lines: int,
                       max_tokens: int, cur_tokens: int) -> str:
        """Keep the head and the tail of `text` with a `{FOOTER}` slot between them.

        Line indices only work when there are more lines than the budget. One
        enormous line can blow the token budget on its own, and slicing that by
        line index returns the whole payload twice, so it is cut by character
        count scaled to the measured tokens-per-character of this very text.
        """
        if len(lines) > max_lines:
            head_n = int(max_lines * 0.6)
            return ("\n".join(lines[:head_n]) + "\n{FOOTER}\n"
                    + "\n".join(lines[max(head_n, len(lines) - (max_lines - head_n)):]))
        budget = max(int(len(text) * max_tokens / max(cur_tokens, 1)), 1)
        head_c = int(budget * 0.6)
        tail_c = budget - head_c
        return text[:head_c] + "\n{FOOTER}\n" + (text[-tail_c:] if tail_c > 0 else "")

    def _handle_of(self, text: str) -> str:
        if not self.pre_store(text):
            return ""
        return self.handles.put(text)

    def _materialize(self, norm: NormalizedRequest, msg_index: int, row: TransformRow,
                     orig: str, block_index: int | None = None) -> str:
        """A stored reference is only valid while the thing it points at is still in this request."""
        if row.kind in ("dedup_ref", "diff_ref") and row.ref_sha:
            if dedup.find_reference(norm, msg_index, row.ref_sha, block_index) is None:
                self.ledger.record_event("ref_dangling", {"kind": row.kind, "ref_sha": row.ref_sha[:12]})
                return canonical.canonicalize(orig)
        return row.transformed

    # --- entry point ---
    def _key(self, sha: str, ref, rr) -> str:
        """Content addresses the transform, but a reference also depends on what it points at.

        The key names the referenced *content*, never its position. Position would be stable
        only while history grows by appending; compaction renumbers messages, and the same
        bytes would then key differently and get a second replacement, which is exactly the
        cache break this table exists to prevent.
        """
        if ref:
            return f"{sha}@same{ref[1][:12]}"
        if rr:
            return f"{sha}@diff{rr[1][:12]}"
        return sha

    def apply(self, norm: NormalizedRequest, body: dict, delta_start: int,
              session_id: str, request_id: str) -> PipelineResult:
        res = PipelineResult(body=body)
        if not self.cfg.lossless:
            return res
        for i, msg in enumerate(norm.messages):
            for j, blk in enumerate(msg.blocks):
                # An adapter that hands back a non-string body (a list of content
                # parts, say) must cost a transform, never the whole request.
                if blk.kind != "tool_result" or not isinstance(blk.text, str) or not blk.text:
                    continue
                orig = blk.text
                sha = sha256_text(orig)
                ob = self.est.count(orig, norm.provider, norm.model)
                res.tokens_before += ob
                ref = dedup.find_reference(norm, i, sha, j)
                rr = None if ref else dedup.find_reread(norm, i, blk, j)
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
                text = self._materialize(norm, i, row, orig, j)
                if text != orig:
                    json_set(body, blk.path, text)
                    res.applied.append(Applied(str(blk.path), row.kind, row.orig_tokens,
                                               row.new_tokens, row.handle))
                    self.ledger.link_transform(request_id, key, str(blk.path),
                                               max(row.orig_tokens - row.new_tokens, 0))
                res.tokens_after += self.est.count(text, norm.provider, norm.model)
        return res
