"""Ollama native API. A local model has no quota to protect, so the win here is fitting the
context window: a silently truncated prompt changes the answer."""
from __future__ import annotations

from .base import Block, Message, NormalizedRequest, Usage, canonical_json, sha256_text


class OllamaAdapter:
    kind = "ollama"

    def matches(self, path: str) -> bool:
        return path.endswith("/api/chat") or path.endswith("/api/generate")

    def parse(self, body: dict) -> NormalizedRequest:
        msgs: list[Message] = []
        tool_index: dict[str, Block] = {}
        system_parts: list[str] = []
        if "prompt" in body and "messages" not in body:
            msgs.append(Message("user", [Block("text", body.get("prompt") or "", ("prompt",))],
                                sha256_text(str(body.get("prompt")))))
            if body.get("system"):
                system_parts.append(body["system"])
        for i, m in enumerate(body.get("messages", []) or []):
            role = m.get("role", "")
            blocks: list[Block] = []
            content = m.get("content")
            if role == "tool":
                blocks.append(Block("tool_result", content or "", ("messages", i, "content"),
                                    tool_use_id=m.get("tool_call_id") or f"ollama-{i}"))
            else:
                if role == "system" and isinstance(content, str):
                    system_parts.append(content)
                if isinstance(content, str):
                    blocks.append(Block("text", content, ("messages", i, "content")))
                for j, tc in enumerate(m.get("tool_calls") or []):
                    fn = tc.get("function") or {}
                    tid = tc.get("id") or f"ollama-tc-{i}-{j}"
                    blk = Block("tool_use", None, ("messages", i, "tool_calls", j),
                                fn.get("name"), fn.get("arguments") if isinstance(fn.get("arguments"), dict) else {},
                                tid)
                    blocks.append(blk)
                    tool_index[tid] = blk
            msgs.append(Message(role, blocks, sha256_text(canonical_json(m))))
        stream = body.get("stream")
        return NormalizedRequest(
            provider="ollama", model=body.get("model", ""),
            stream=True if stream is None else bool(stream),
            system_text="\n".join(system_parts), tools_json=canonical_json(body.get("tools", [])),
            messages=msgs, raw=body, has_cache_control=False, tool_use_index=tool_index,
        )

    def _from(self, o: dict) -> Usage:
        return Usage(int(o.get("prompt_eval_count") or 0), 0, 0, int(o.get("eval_count") or 0))

    def usage_from_json(self, body: dict) -> Usage:
        return self._from(body)

    def usage_from_ndjson(self, objects: list[dict]) -> Usage:
        for o in reversed(objects):
            if o.get("done") or "prompt_eval_count" in o:
                return self._from(o)
        return Usage()

    def usage_from_sse(self, events: list[tuple[str, dict]]) -> Usage:
        return self.usage_from_ndjson([d for _n, d in events])

    def ensure_stream_usage(self, body: dict) -> None:
        return None
