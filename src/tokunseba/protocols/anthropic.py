"""Anthropic Messages API adapter."""
from __future__ import annotations

from .base import Block, Message, NormalizedRequest, Usage, canonical_json, sha256_text


class AnthropicAdapter:
    kind = "anthropic"

    def matches(self, path: str) -> bool:
        return path.endswith("/v1/messages") or path.endswith("/v1/messages/count_tokens")

    def parse(self, body: dict) -> NormalizedRequest:
        msgs: list[Message] = []
        tool_index: dict[str, Block] = {}
        for i, m in enumerate(body.get("messages", []) or []):
            blocks: list[Block] = []
            content = m.get("content")
            if isinstance(content, str):
                blocks.append(Block("text", content, ("messages", i, "content")))
            else:
                for j, b in enumerate(content or []):
                    if not isinstance(b, dict):
                        continue
                    t = b.get("type")
                    if t == "text":
                        blocks.append(Block("text", b.get("text", ""), ("messages", i, "content", j, "text")))
                    elif t == "thinking":
                        blocks.append(Block("thinking", None, ("messages", i, "content", j)))
                    elif t == "tool_use":
                        blk = Block("tool_use", None, ("messages", i, "content", j),
                                    b.get("name"), b.get("input") if isinstance(b.get("input"), dict) else {},
                                    b.get("id"))
                        blocks.append(blk)
                        if b.get("id"):
                            tool_index[b["id"]] = blk
                    elif t == "tool_result":
                        c = b.get("content")
                        if isinstance(c, str):
                            blocks.append(Block("tool_result", c, ("messages", i, "content", j, "content"),
                                                tool_use_id=b.get("tool_use_id")))
                        else:
                            for k, cb in enumerate(c or []):
                                if isinstance(cb, dict) and cb.get("type") == "text":
                                    blocks.append(Block(
                                        "tool_result", cb.get("text", ""),
                                        ("messages", i, "content", j, "content", k, "text"),
                                        tool_use_id=b.get("tool_use_id")))
                    elif t == "image":
                        blocks.append(Block("image", None, ("messages", i, "content", j)))
                    else:
                        blocks.append(Block("other", None, ("messages", i, "content", j)))
            msgs.append(Message(m.get("role", ""), blocks, sha256_text(canonical_json(m))))

        system = body.get("system", "")
        if isinstance(system, str):
            system_text = system
        else:
            system_text = "\n".join(b.get("text", "") for b in (system or []) if isinstance(b, dict))
        has_cc = "cache_control" in canonical_json(body)
        return NormalizedRequest(
            provider="anthropic", model=body.get("model", ""), stream=bool(body.get("stream")),
            system_text=system_text, tools_json=canonical_json(body.get("tools", [])),
            messages=msgs, raw=body, has_cache_control=has_cc, tool_use_index=tool_index,
        )

    def usage_from_json(self, body: dict) -> Usage:
        u = body.get("usage") or {}
        return Usage(
            input_tokens=int(u.get("input_tokens") or 0),
            cache_read=int(u.get("cache_read_input_tokens") or 0),
            cache_write=int(u.get("cache_creation_input_tokens") or 0),
            output_tokens=int(u.get("output_tokens") or 0),
        )

    def usage_from_sse(self, events: list[tuple[str, dict]]) -> Usage:
        out = Usage()
        for name, data in events:
            if name == "message_start":
                u = ((data.get("message") or {}).get("usage")) or {}
                out.input_tokens = int(u.get("input_tokens") or 0)
                out.cache_read = int(u.get("cache_read_input_tokens") or 0)
                out.cache_write = int(u.get("cache_creation_input_tokens") or 0)
                out.output_tokens = int(u.get("output_tokens") or 0)
            elif name == "message_delta":
                u = data.get("usage") or {}
                if "output_tokens" in u:
                    out.output_tokens = int(u["output_tokens"] or 0)
        return out

    def ensure_stream_usage(self, body: dict) -> None:
        return None
