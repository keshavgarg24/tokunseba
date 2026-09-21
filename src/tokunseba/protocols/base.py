"""Provider-neutral request shape shared by every adapter."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Usage:
    input_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    output_tokens: int = 0

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_read + self.cache_write


@dataclass
class Block:
    kind: str  # text | tool_use | tool_result | image | thinking | other
    text: str | None
    path: tuple[Any, ...]
    tool_name: str | None = None
    tool_input: dict | None = None
    tool_use_id: str | None = None


@dataclass
class Message:
    role: str
    blocks: list[Block]
    raw_hash: str


@dataclass
class NormalizedRequest:
    provider: str
    model: str
    stream: bool
    system_text: str
    tools_json: str
    messages: list[Message]
    raw: dict
    has_cache_control: bool
    tool_use_index: dict[str, Block] = field(default_factory=dict)

    def chain(self) -> list[str]:
        return [m.raw_hash for m in self.messages]

    def last_user_text(self) -> str:
        for m in reversed(self.messages):
            if m.role in ("user", "human"):
                parts = [b.text for b in m.blocks if b.kind == "text" and b.text]
                if parts:
                    return "\n".join(parts)
        return ""


class Adapter(Protocol):
    kind: str

    def matches(self, path: str) -> bool: ...
    def parse(self, body: dict) -> NormalizedRequest: ...
    def usage_from_json(self, body: dict) -> Usage: ...
    def usage_from_sse(self, events: list[tuple[str, dict]]) -> Usage: ...
    def ensure_stream_usage(self, body: dict) -> None: ...


def json_get(obj: Any, path: tuple[Any, ...]) -> Any:
    for p in path:
        obj = obj[p]
    return obj


def json_set(obj: Any, path: tuple[Any, ...], value: Any) -> None:
    for p in path[:-1]:
        obj = obj[p]
    obj[path[-1]] = value


def canonical_json(o: Any) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()
