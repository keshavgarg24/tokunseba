"""Google Gemini generateContent adapter."""
from __future__ import annotations

import re

from .base import Block, Message, NormalizedRequest, Usage, canonical_json, sha256_text

MODEL_RE = re.compile(r"/models/([^:/?]+)")


class GeminiAdapter:
    kind = "gemini"

    def matches(self, path: str) -> bool:
        return ":generateContent" in path or ":streamGenerateContent" in path

    def model_from_path(self, path: str) -> str:
        m = MODEL_RE.search(path)
        return m.group(1) if m else ""

    def parse(self, body: dict) -> NormalizedRequest:
        msgs: list[Message] = []
        tool_index: dict[str, Block] = {}
        for i, c in enumerate(body.get("contents", []) or []):
            blocks: list[Block] = []
            for j, part in enumerate(c.get("parts") or []):
                if not isinstance(part, dict):
                    continue
                if "text" in part:
                    blocks.append(Block("text", part.get("text") or "", ("contents", i, "parts", j, "text")))
                elif "functionCall" in part:
                    fc = part["functionCall"] or {}
                    tid = f"gem-{i}-{j}"
                    blk = Block("tool_use", None, ("contents", i, "parts", j), fc.get("name"),
                                fc.get("args") if isinstance(fc.get("args"), dict) else {}, tid)
                    blocks.append(blk)
                    tool_index[tid] = blk
                elif "functionResponse" in part:
                    fr = part["functionResponse"] or {}
                    resp = fr.get("response")
                    if isinstance(resp, dict):
                        str_keys = [k for k, v in resp.items() if isinstance(v, str)]
                        if len(str_keys) == 1:
                            k = str_keys[0]
                            blocks.append(Block(
                                "tool_result", resp[k],
                                ("contents", i, "parts", j, "functionResponse", "response", k),
                                tool_use_id=f"gem-resp-{i}-{j}"))
                            continue
                    blocks.append(Block("other", None, ("contents", i, "parts", j)))
                else:
                    blocks.append(Block("other", None, ("contents", i, "parts", j)))
            msgs.append(Message(c.get("role", ""), blocks, sha256_text(canonical_json(c))))
        si = body.get("systemInstruction") or {}
        system_text = "\n".join(p.get("text", "") for p in (si.get("parts") or []) if isinstance(p, dict))
        return NormalizedRequest(
            provider="gemini", model=body.get("model", ""), stream=False,
            system_text=system_text, tools_json=canonical_json(body.get("tools", [])),
            messages=msgs, raw=body, has_cache_control=False, tool_use_index=tool_index,
        )

    def _from(self, um: dict) -> Usage:
        cached = int(um.get("cachedContentTokenCount") or 0)
        prompt = int(um.get("promptTokenCount") or 0)
        return Usage(max(prompt - cached, 0), cached, 0, int(um.get("candidatesTokenCount") or 0))

    def usage_from_json(self, body: dict) -> Usage:
        return self._from(body.get("usageMetadata") or {})

    def usage_from_sse(self, events: list[tuple[str, dict]]) -> Usage:
        out = Usage()
        for _n, data in events:
            if isinstance(data, dict) and data.get("usageMetadata"):
                out = self._from(data["usageMetadata"])
        return out

    def ensure_stream_usage(self, body: dict) -> None:
        return None
