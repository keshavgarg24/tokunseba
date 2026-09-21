"""OpenAI adapter covering both Chat Completions and the Responses API."""
from __future__ import annotations

import json

from .base import Block, Message, NormalizedRequest, Usage, canonical_json, sha256_text


def _args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except (ValueError, TypeError):
        return {}


class OpenAIAdapter:
    kind = "openai"

    def matches(self, path: str) -> bool:
        return path.endswith("/chat/completions") or path.endswith("/responses")

    def parse(self, body: dict) -> NormalizedRequest:
        if "input" in body and "messages" not in body:
            return self._parse_responses(body)
        return self._parse_chat(body)

    # --- chat completions ---
    def _parse_chat(self, body: dict) -> NormalizedRequest:
        msgs: list[Message] = []
        tool_index: dict[str, Block] = {}
        system_parts: list[str] = []
        for i, m in enumerate(body.get("messages", []) or []):
            role = m.get("role", "")
            blocks: list[Block] = []
            if role == "tool":
                blocks.append(Block("tool_result", m.get("content") or "", ("messages", i, "content"),
                                    tool_use_id=m.get("tool_call_id")))
            else:
                content = m.get("content")
                if isinstance(content, str):
                    if role == "system" or role == "developer":
                        system_parts.append(content)
                    blocks.append(Block("text", content, ("messages", i, "content")))
                elif isinstance(content, list):
                    for j, part in enumerate(content):
                        if isinstance(part, dict) and part.get("type") in ("text", "input_text", "output_text"):
                            key = "text"
                            if role in ("system", "developer"):
                                system_parts.append(part.get(key, ""))
                            blocks.append(Block("text", part.get(key, ""), ("messages", i, "content", j, key)))
                        else:
                            blocks.append(Block("other", None, ("messages", i, "content", j)))
                for j, tc in enumerate(m.get("tool_calls") or []):
                    fn = tc.get("function") or {}
                    blk = Block("tool_use", None, ("messages", i, "tool_calls", j),
                                fn.get("name"), _args(fn.get("arguments")), tc.get("id"))
                    blocks.append(blk)
                    if tc.get("id"):
                        tool_index[tc["id"]] = blk
            msgs.append(Message(role, blocks, sha256_text(canonical_json(m))))
        return NormalizedRequest(
            provider="openai", model=body.get("model", ""), stream=bool(body.get("stream")),
            system_text="\n".join(system_parts), tools_json=canonical_json(body.get("tools", [])),
            messages=msgs, raw=body, has_cache_control=False, tool_use_index=tool_index,
        )

    # --- responses api ---
    def _parse_responses(self, body: dict) -> NormalizedRequest:
        msgs: list[Message] = []
        tool_index: dict[str, Block] = {}
        items = body.get("input")
        if isinstance(items, str):
            msgs.append(Message("user", [Block("text", items, ("input",))], sha256_text(items)))
            items = []
        for i, it in enumerate(items or []):
            if not isinstance(it, dict):
                continue
            t = it.get("type")
            blocks: list[Block] = []
            role = it.get("role", "")
            if t == "function_call_output":
                blocks.append(Block("tool_result", it.get("output") or "", ("input", i, "output"),
                                    tool_use_id=it.get("call_id")))
                role = role or "tool"
            elif t == "function_call":
                blk = Block("tool_use", None, ("input", i), it.get("name"),
                            _args(it.get("arguments")), it.get("call_id"))
                blocks.append(blk)
                if it.get("call_id"):
                    tool_index[it["call_id"]] = blk
                role = role or "assistant"
            else:
                content = it.get("content")
                if isinstance(content, str):
                    blocks.append(Block("text", content, ("input", i, "content")))
                else:
                    for j, part in enumerate(content or []):
                        if isinstance(part, dict) and part.get("type") in ("input_text", "output_text", "text"):
                            blocks.append(Block("text", part.get("text", ""), ("input", i, "content", j, "text")))
                        else:
                            blocks.append(Block("other", None, ("input", i, "content", j)))
            msgs.append(Message(role, blocks, sha256_text(canonical_json(it))))
        instructions = body.get("instructions") or ""
        return NormalizedRequest(
            provider="openai", model=body.get("model", ""), stream=bool(body.get("stream")),
            system_text=instructions if isinstance(instructions, str) else "",
            tools_json=canonical_json(body.get("tools", [])),
            messages=msgs, raw=body, has_cache_control=False, tool_use_index=tool_index,
        )

    # --- usage ---
    def _usage(self, u: dict) -> Usage:
        if not u:
            return Usage()
        if "prompt_tokens" in u:
            cached = int(((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
            prompt = int(u.get("prompt_tokens") or 0)
            return Usage(max(prompt - cached, 0), cached, 0, int(u.get("completion_tokens") or 0))
        cached = int(((u.get("input_tokens_details") or {}).get("cached_tokens")) or 0)
        inp = int(u.get("input_tokens") or 0)
        return Usage(max(inp - cached, 0), cached, 0, int(u.get("output_tokens") or 0))

    def usage_from_json(self, body: dict) -> Usage:
        if "response" in body and isinstance(body["response"], dict):
            return self._usage(body["response"].get("usage") or {})
        return self._usage(body.get("usage") or {})

    def usage_from_sse(self, events: list[tuple[str, dict]]) -> Usage:
        out = Usage()
        for _name, data in events:
            if not isinstance(data, dict):
                continue
            u = data.get("usage")
            if not u and isinstance(data.get("response"), dict):
                u = data["response"].get("usage")
            if u:
                out = self._usage(u)
        return out

    def ensure_stream_usage(self, body: dict) -> None:
        if body.get("stream") and "input" not in body:
            so = body.get("stream_options")
            if not isinstance(so, dict):
                body["stream_options"] = {"include_usage": True}
            else:
                so.setdefault("include_usage", True)


ADAPTERS: dict = {}
