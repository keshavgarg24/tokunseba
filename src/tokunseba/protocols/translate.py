"""Translate a request from one provider's wire format into another's, and the reply back.

Everything else in tokunseba rewrites a body in place: the same protocol goes in and comes
out. This is the one module that changes shape, and it exists for one reason. What people
actually want is to run Claude Code against whatever model suits the turn, a local one for a
throwaway question and a cheaper API for a summary, and Claude Code speaks the Anthropic
Messages API to every one of them. Without a translator such a request can only ever reach
an Anthropic endpoint, which makes routing by prompt content a demo rather than a feature.

Only the pairs in `PAIRS` are supported. The direction that matters is Anthropic out to
anything OpenAI-shaped, which covers OpenAI, DeepSeek, Groq, Together, Mistral, vLLM, LM
Studio, llama.cpp and Ollama's compatibility route. Anything else is refused up front by
`tier3.routing.compatible` rather than attempted and 400'd.

Two rules hold throughout:

- Dropping a field is allowed, inventing one is not. Anthropic's thinking blocks have no
  OpenAI equivalent so they are dropped; nothing is fabricated to fill a gap.
- The client must not be able to tell the reply was assembled here, beyond the plain fact
  that a different model answered. That means a complete, correctly ordered event stream
  with every event the Anthropic SDK expects, not a best effort.
"""
from __future__ import annotations

import json
import uuid

# Ollama's OpenAI-compatible route takes an OpenAI body, so the two are one target here.
PAIRS: set[tuple[str, str]] = {("anthropic", "openai"), ("anthropic", "ollama")}

# Where a translated request has to be sent, which is not where it arrived.
SUB_PATH: dict[str, str] = {"openai": "/v1/chat/completions", "ollama": "/v1/chat/completions"}

_STOP_REASON = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use",
                "function_call": "tool_use", "content_filter": "end_turn"}


def can(src: str, dst: str) -> bool:
    """Whether a request arriving as `src` can be rewritten for an upstream speaking `dst`."""
    return (src, dst) in PAIRS


def targets(src: str) -> set[str]:
    return {dst for s, dst in PAIRS if s == src}


# ---------------------------------------------------------------- request

def _system_text(system) -> str:
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "\n".join(b.get("text", "") for b in system
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return "" if content is None else json.dumps(content)


def _image_part(block: dict) -> dict | None:
    src = block.get("source") or {}
    if src.get("type") == "base64" and src.get("data"):
        media = src.get("media_type") or "image/png"
        return {"type": "image_url", "image_url": {"url": f"data:{media};base64,{src['data']}"}}
    if src.get("type") == "url" and src.get("url"):
        return {"type": "image_url", "image_url": {"url": src["url"]}}
    return None


def _content(parts: list[dict]):
    """Collapse to a plain string when it can be.

    Every OpenAI-compatible server accepts a string. Not all of the small ones accept the
    array form, and a local model is exactly where this ends up most often.
    """
    if not parts:
        return ""
    if all(p.get("type") == "text" for p in parts):
        return "\n".join(p["text"] for p in parts)
    return parts


def _tool_choice(tc):
    if not isinstance(tc, dict):
        return None
    kind = tc.get("type")
    if kind == "auto":
        return "auto"
    if kind == "any":
        return "required"
    if kind == "none":
        return "none"
    if kind == "tool" and tc.get("name"):
        return {"type": "function", "function": {"name": tc["name"]}}
    return None


def anthropic_to_openai(body: dict) -> dict:
    """An Anthropic Messages body as an OpenAI chat-completions body."""
    msgs: list[dict] = []
    system = _system_text(body.get("system"))
    if system:
        msgs.append({"role": "system", "content": system})

    for m in body.get("messages") or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role") or "user"
        content = m.get("content")
        if isinstance(content, str):
            msgs.append({"role": role, "content": content})
            continue
        parts: list[dict] = []
        calls: list[dict] = []
        for b in content or []:
            if not isinstance(b, dict):
                continue
            kind = b.get("type")
            if kind == "text":
                parts.append({"type": "text", "text": b.get("text", "")})
            elif kind == "image":
                part = _image_part(b)
                if part is not None:
                    parts.append(part)
            elif kind == "tool_use":
                calls.append({"id": b.get("id") or _tool_id(), "type": "function",
                              "function": {"name": b.get("name", ""),
                                           "arguments": json.dumps(b.get("input") or {})}})
            elif kind == "tool_result":
                # Anthropic carries results inside the following user message. OpenAI wants
                # each one as a message of its own, ahead of whatever the user said with it.
                msgs.append({"role": "tool", "tool_call_id": b.get("tool_use_id", ""),
                             "content": _result_text(b.get("content"))})
            # thinking and redacted_thinking have no equivalent, and forwarding them is a 400.
        if parts or calls:
            msg: dict = {"role": role, "content": _content(parts) if parts else None}
            if calls:
                msg["tool_calls"] = calls
            msgs.append(msg)

    out: dict = {"model": body.get("model", ""), "messages": msgs}
    if body.get("max_tokens"):
        out["max_tokens"] = body["max_tokens"]
    for src_key, dst_key in (("temperature", "temperature"), ("top_p", "top_p"),
                             ("stop_sequences", "stop")):
        if body.get(src_key) is not None:
            out[dst_key] = body[src_key]

    # Only custom tools carry an input_schema. Anthropic's server-side tools do not, and the
    # far end could not run them anyway, so they are left behind rather than sent as stubs.
    tools = [{"type": "function",
              "function": {"name": t["name"], "description": t.get("description", ""),
                           "parameters": t.get("input_schema")}}
             for t in (body.get("tools") or [])
             if isinstance(t, dict) and t.get("name") and isinstance(t.get("input_schema"), dict)]
    if tools:
        out["tools"] = tools
        choice = _tool_choice(body.get("tool_choice"))
        if choice is not None:
            out["tool_choice"] = choice

    if body.get("stream"):
        out["stream"] = True
        # Without this an OpenAI-compatible stream carries no usage at all, and the ledger
        # would be recording a turn it could not count.
        out["stream_options"] = {"include_usage": True}
    return out


# ---------------------------------------------------------------- response

def _msg_id(raw=None) -> str:
    text = "".join(c for c in str(raw or "") if c.isalnum())
    return "msg_" + (text or uuid.uuid4().hex)[:32]


def _tool_id() -> str:
    return "toolu_" + uuid.uuid4().hex[:24]


def _args(raw) -> dict:
    try:
        value = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _usage(u: dict, fallback_input: int = 0) -> dict:
    u = u or {}
    cached = int(((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
    prompt = int(u.get("prompt_tokens") or 0)
    return {"input_tokens": max(prompt - cached, 0) if prompt else fallback_input,
            "cache_read_input_tokens": cached, "cache_creation_input_tokens": 0,
            "output_tokens": int(u.get("completion_tokens") or 0)}


def openai_to_anthropic(resp: dict, model: str = "") -> dict:
    """A non-streaming chat-completions reply as an Anthropic Messages reply."""
    choice = ((resp.get("choices") or [{}])[0]) or {}
    message = choice.get("message") or {}
    blocks: list[dict] = []
    text = message.get("content")
    if isinstance(text, list):
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    if text:
        blocks.append({"type": "text", "text": text})
    for tc in message.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        # The upstream id goes through untouched. The client hands it straight back as
        # tool_use_id on the next turn, that turn is translated the other way, and the far
        # end has to recognise it. Prettifying the prefix here would break the round trip.
        blocks.append({"type": "tool_use", "id": tc.get("id") or _tool_id(),
                       "name": fn.get("name", ""), "input": _args(fn.get("arguments"))})
    if not blocks:
        blocks.append({"type": "text", "text": ""})
    return {"id": _msg_id(resp.get("id")), "type": "message", "role": "assistant",
            "model": resp.get("model") or model, "content": blocks,
            "stop_reason": _STOP_REASON.get(choice.get("finish_reason") or "", "end_turn"),
            "stop_sequence": None, "usage": _usage(resp.get("usage") or {})}


def error_to_anthropic(obj, status: int = 500) -> dict:
    """An upstream failure in the shape the client's own SDK knows how to raise.

    A rerouted request that fails is the moment a user most needs to understand what
    happened. Handing Claude Code an OpenAI error envelope gets them a parse error instead
    of a message.
    """
    err = obj.get("error") if isinstance(obj, dict) else None
    if isinstance(err, dict):
        message = str(err.get("message") or err.get("type") or "")
    elif isinstance(err, str):
        message = err
    else:
        message = json.dumps(obj)[:400] if obj else f"upstream returned HTTP {status}"
    kind = {400: "invalid_request_error", 401: "authentication_error",
            403: "permission_error", 404: "not_found_error", 429: "rate_limit_error"}.get(
                status, "api_error")
    return {"type": "error", "error": {"type": kind, "message": message}}


class SSEToAnthropic:
    """An OpenAI chat-completions stream, re-emitted as an Anthropic Messages stream.

    Stateful and single use. Two things make this more than a rename. Anthropic numbers its
    content blocks and requires each to be opened and closed in order, while OpenAI emits
    bare deltas and lets the client work it out. And OpenAI reports usage in a final chunk,
    long after Anthropic's `message_start` has had to state an input count: `message_start`
    therefore carries the estimate tokunseba made of the request it sent, and `message_delta`
    carries the real figures once they arrive.
    """

    def __init__(self, model: str = "", input_tokens: int = 0):
        self.model = model
        self.input_tokens = max(int(input_tokens or 0), 0)
        self._buf = b""
        self._started = False
        self._done = False
        self._open: int | None = None
        self._open_kind = ""
        self._next = 0
        self._tools: dict[int, int] = {}
        self._stop = "end_turn"
        self._usage = {"input_tokens": self.input_tokens, "cache_read_input_tokens": 0,
                       "cache_creation_input_tokens": 0, "output_tokens": 0}

    @staticmethod
    def _event(name: str, data: dict) -> bytes:
        return f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()

    # --- input ---
    def feed(self, chunk: bytes) -> bytes:
        self._buf += chunk
        out = bytearray()
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            out += self._line(line.strip())
        return bytes(out)

    def _line(self, line: bytes) -> bytes:
        if not line.startswith(b"data:"):
            return b""
        payload = line[5:].strip()
        if payload == b"[DONE]":
            return self.close()
        try:
            obj = json.loads(payload)
        except ValueError:
            return b""
        return self._chunk(obj) if isinstance(obj, dict) else b""

    def _chunk(self, obj: dict) -> bytes:
        if self._done:
            return b""
        out = bytearray()
        if not self._started:
            out += self._start(obj)
        if isinstance(obj.get("usage"), dict):
            got = _usage(obj["usage"], self.input_tokens)
            if got["input_tokens"] or got["output_tokens"] or got["cache_read_input_tokens"]:
                self._usage = got
        choice = ((obj.get("choices") or [{}])[0]) or {}
        delta = choice.get("delta") or {}
        text = delta.get("content")
        if isinstance(text, list):
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        if text:
            out += self._text(text)
        for tc in delta.get("tool_calls") or []:
            if isinstance(tc, dict):
                out += self._tool(tc)
        if choice.get("finish_reason"):
            self._stop = _STOP_REASON.get(choice["finish_reason"], "end_turn")
        return bytes(out)

    # --- blocks ---
    def _start(self, obj: dict) -> bytes:
        self._started = True
        return self._event("message_start", {
            "type": "message_start",
            "message": {"id": _msg_id(obj.get("id")), "type": "message", "role": "assistant",
                        "model": obj.get("model") or self.model, "content": [],
                        "stop_reason": None, "stop_sequence": None,
                        "usage": {"input_tokens": self.input_tokens,
                                  "cache_read_input_tokens": 0,
                                  "cache_creation_input_tokens": 0, "output_tokens": 0}}})

    def _close_open(self) -> bytes:
        if self._open is None:
            return b""
        index, self._open, self._open_kind = self._open, None, ""
        return self._event("content_block_stop", {"type": "content_block_stop", "index": index})

    def _text(self, text: str) -> bytes:
        out = bytearray()
        if self._open is None or self._open_kind != "text":
            out += self._close_open()
            self._open, self._open_kind = self._next, "text"
            self._next += 1
            out += self._event("content_block_start",
                               {"type": "content_block_start", "index": self._open,
                                "content_block": {"type": "text", "text": ""}})
        out += self._event("content_block_delta",
                           {"type": "content_block_delta", "index": self._open,
                            "delta": {"type": "text_delta", "text": text}})
        return bytes(out)

    def _tool(self, tc: dict) -> bytes:
        slot = int(tc.get("index") or 0)
        fn = tc.get("function") or {}
        out = bytearray()
        if slot not in self._tools:
            out += self._close_open()
            self._tools[slot] = self._next
            self._open, self._open_kind = self._next, "tool"
            self._next += 1
            out += self._event("content_block_start",
                               {"type": "content_block_start", "index": self._open,
                                "content_block": {"type": "tool_use",
                                                  "id": tc.get("id") or _tool_id(),
                                                  "name": fn.get("name", ""), "input": {}}})
        args = fn.get("arguments")
        if args:
            out += self._event("content_block_delta",
                               {"type": "content_block_delta", "index": self._tools[slot],
                                "delta": {"type": "input_json_delta", "partial_json": args}})
        return bytes(out)

    def close(self) -> bytes:
        """The tail of the stream. Safe to call twice; the second call writes nothing."""
        if self._done:
            return b""
        self._done = True
        out = bytearray()
        if not self._started:
            out += self._start({})
        out += self._close_open()
        out += self._event("message_delta",
                           {"type": "message_delta",
                            "delta": {"stop_reason": self._stop, "stop_sequence": None},
                            "usage": self._usage})
        out += self._event("message_stop", {"type": "message_stop"})
        return bytes(out)


# ---------------------------------------------------------------- dispatch
# One pair is supported today, so these three are thin. They are still the seam: a second
# pair is added by extending PAIRS and branching here, and nothing outside this module has
# to learn the name of a protocol it does not speak.

def request(src: str, dst: str, body: dict) -> dict:
    """Rewrite an outbound body for an upstream speaking `dst`. Guard with `can` first."""
    return anthropic_to_openai(body)


def response(src: str, dst: str, obj: dict, model: str = "") -> dict:
    """Rewrite a non-streaming reply back into the protocol the client is expecting."""
    return openai_to_anthropic(obj, model)


def stream(src: str, dst: str, model: str = "", input_tokens: int = 0) -> SSEToAnthropic:
    """A stateful re-framer for one streamed reply."""
    return SSEToAnthropic(model, input_tokens)
