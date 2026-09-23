"""Cross-protocol routing: an Anthropic client reaching an OpenAI-shaped model.

This is the feature the whole routing tier was for. Claude Code speaks one protocol to
every model it talks to, so without translation "send the easy turns to a local model"
could never be more than a slide. The tests below are split between the conversion itself
and one end-to-end pass through the proxy, because a translator that is correct in
isolation and never reached is worth nothing.
"""
import json

import pytest

from tokunseba.protocols import translate


def sse_events(blob: bytes) -> list[tuple[str, dict]]:
    """Parse an Anthropic event stream back into (name, data) pairs."""
    out = []
    for block in blob.decode().split("\n\n"):
        name = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name is not None and data is not None:
            out.append((name, data))
    return out


# --- what can be translated at all ------------------------------------------------------

def test_only_the_pairs_that_are_implemented_are_offered():
    assert translate.can("anthropic", "openai")
    assert translate.can("anthropic", "ollama")
    assert not translate.can("anthropic", "gemini")
    assert not translate.can("gemini", "openai")


def test_routing_lets_an_anthropic_client_reach_an_openai_model():
    """The gate this feature exists to open."""
    from tokunseba.tier3.routing import compatible
    assert compatible("anthropic", "openai")
    assert compatible("anthropic", "ollama")
    assert not compatible("anthropic", "gemini")


# --- request ----------------------------------------------------------------------------

def test_the_system_prompt_becomes_the_first_message():
    out = translate.anthropic_to_openai({
        "model": "m", "max_tokens": 64, "system": [{"type": "text", "text": "be brief"}],
        "messages": [{"role": "user", "content": "hello"}]})
    assert out["messages"][0] == {"role": "system", "content": "be brief"}
    assert out["messages"][1] == {"role": "user", "content": "hello"}
    assert out["max_tokens"] == 64


def test_a_tool_result_becomes_its_own_message_before_the_user_text():
    """Anthropic packs results into the next user turn; OpenAI wants them standing alone,
    and in front of anything the user said alongside them."""
    out = translate.anthropic_to_openai({"model": "m", "messages": [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "call_7", "name": "read", "input": {"path": "a.py"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call_7", "content": "file body"},
            {"type": "text", "text": "now explain it"}]},
    ]})
    assistant, result, user = out["messages"]
    assert assistant["tool_calls"][0]["id"] == "call_7"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"path": "a.py"}
    assert assistant["content"] is None
    assert result == {"role": "tool", "tool_call_id": "call_7", "content": "file body"}
    assert user == {"role": "user", "content": "now explain it"}


def test_a_tool_call_id_is_never_rewritten():
    """It comes back next turn as tool_use_id and the far end has to recognise it. A
    prettier prefix here would break every multi-step tool conversation."""
    reply = translate.openai_to_anthropic({"choices": [{"message": {"tool_calls": [
        {"id": "call_abc123", "function": {"name": "grep", "arguments": '{"q":"x"}'}}]}}]})
    block = reply["content"][0]
    assert block["id"] == "call_abc123"
    back = translate.anthropic_to_openai({"model": "m", "messages": [
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": block["id"],
                                      "content": "ok"}]}]})
    assert back["messages"][0]["tool_call_id"] == "call_abc123"


def test_tool_definitions_are_converted_and_server_tools_left_behind():
    out = translate.anthropic_to_openai({"model": "m", "messages": [], "tools": [
        {"name": "read", "description": "read a file",
         "input_schema": {"type": "object", "properties": {"p": {"type": "string"}}}},
        {"type": "web_search_20250305", "name": "web_search"},
    ], "tool_choice": {"type": "any"}})
    assert len(out["tools"]) == 1
    fn = out["tools"][0]["function"]
    assert out["tools"][0]["type"] == "function" and fn["name"] == "read"
    assert fn["parameters"]["properties"]["p"]["type"] == "string"
    assert out["tool_choice"] == "required"


@pytest.mark.parametrize("given,want", [
    ({"type": "auto"}, "auto"), ({"type": "none"}, "none"),
    ({"type": "tool", "name": "read"}, {"type": "function", "function": {"name": "read"}}),
])
def test_tool_choice_mapping(given, want):
    out = translate.anthropic_to_openai({"model": "m", "messages": [], "tool_choice": given,
                                         "tools": [{"name": "read", "input_schema": {}}]})
    assert out["tool_choice"] == want


def test_thinking_blocks_are_dropped_rather_than_forwarded():
    """There is no OpenAI equivalent and sending one is a 400."""
    out = translate.anthropic_to_openai({"model": "m", "messages": [
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "hmm",
                                           "signature": "sig"},
                                          {"type": "text", "text": "done"}]}]})
    assert out["messages"] == [{"role": "assistant", "content": "done"}]


def test_an_image_travels_as_a_data_url():
    out = translate.anthropic_to_openai({"model": "m", "messages": [
        {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": "AAAA"}},
            {"type": "text", "text": "what is this"}]}]})
    parts = out["messages"][0]["content"]
    assert parts[0]["image_url"]["url"] == "data:image/png;base64,AAAA"
    assert parts[1] == {"type": "text", "text": "what is this"}


def test_a_streaming_request_asks_for_usage():
    """Otherwise an OpenAI-compatible stream reports nothing and the ledger records a turn
    it could not count."""
    out = translate.anthropic_to_openai({"model": "m", "messages": [], "stream": True,
                                         "stop_sequences": ["END"], "temperature": 0.2})
    assert out["stream"] is True
    assert out["stream_options"] == {"include_usage": True}
    assert out["stop"] == ["END"] and out["temperature"] == 0.2


# --- non-streaming reply ----------------------------------------------------------------

def test_a_reply_comes_back_in_the_shape_the_client_expects():
    reply = translate.openai_to_anthropic({
        "id": "chatcmpl-9", "model": "gpt-4o-mini",
        "choices": [{"message": {"role": "assistant", "content": "sure"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 7,
                  "prompt_tokens_details": {"cached_tokens": 60}}})
    assert reply["type"] == "message" and reply["role"] == "assistant"
    assert reply["id"].startswith("msg_")
    assert reply["content"] == [{"type": "text", "text": "sure"}]
    assert reply["stop_reason"] == "end_turn"
    assert reply["usage"]["input_tokens"] == 40
    assert reply["usage"]["cache_read_input_tokens"] == 60
    assert reply["usage"]["output_tokens"] == 7


@pytest.mark.parametrize("finish,stop_reason", [
    ("stop", "end_turn"), ("length", "max_tokens"), ("tool_calls", "tool_use"),
    ("content_filter", "end_turn"), (None, "end_turn"), ("unheard-of", "end_turn"),
])
def test_stop_reason_mapping(finish, stop_reason):
    reply = translate.openai_to_anthropic({"choices": [{"message": {"content": "x"},
                                                        "finish_reason": finish}]})
    assert reply["stop_reason"] == stop_reason


def test_an_empty_reply_still_has_a_content_block():
    """An Anthropic client iterating content would raise on an empty list."""
    reply = translate.openai_to_anthropic({"choices": [{"message": {"content": None}}]})
    assert reply["content"] == [{"type": "text", "text": ""}]


def test_an_upstream_failure_is_readable_by_the_client_sdk():
    out = translate.error_to_anthropic({"error": {"message": "no such model",
                                                  "type": "invalid_request_error"}}, 400)
    assert out == {"type": "error", "error": {"type": "invalid_request_error",
                                              "message": "no such model"}}
    assert translate.error_to_anthropic({}, 429)["error"]["type"] == "rate_limit_error"


# --- streamed reply ---------------------------------------------------------------------

OPENAI_STREAM = [
    b'data: {"id":"chatcmpl-1","model":"gpt-4o-mini","choices":[{"delta":{"role":"assistant"}}]}\n\n',
    b'data: {"id":"chatcmpl-1","choices":[{"delta":{"content":"Hel"}}]}\n\n',
    b'data: {"id":"chatcmpl-1","choices":[{"delta":{"content":"lo"}}]}\n\n',
    b'data: {"id":"chatcmpl-1","choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
    b'data: {"choices":[],"usage":{"prompt_tokens":30,"completion_tokens":2}}\n\n',
    b'data: [DONE]\n\n',
]


def test_a_text_stream_is_rebuilt_with_every_event_the_sdk_needs():
    framer = translate.stream("anthropic", "openai", "claude-opus-5", input_tokens=29)
    blob = b"".join(framer.feed(c) for c in OPENAI_STREAM) + framer.close()
    events = sse_events(blob)
    assert [name for name, _ in events] == [
        "message_start", "content_block_start", "content_block_delta",
        "content_block_delta", "content_block_stop", "message_delta", "message_stop"]
    start = events[0][1]["message"]
    assert start["role"] == "assistant" and start["model"] == "gpt-4o-mini"
    assert start["usage"]["input_tokens"] == 29          # the estimate, until the truth lands
    assert "".join(e[1]["delta"]["text"] for e in events if e[0] == "content_block_delta") == "Hello"
    delta = events[-2][1]
    assert delta["delta"]["stop_reason"] == "end_turn"
    assert delta["usage"] == {"input_tokens": 30, "cache_read_input_tokens": 0,
                              "cache_creation_input_tokens": 0, "output_tokens": 2}


def test_the_stream_survives_chunks_that_split_a_line():
    """httpx hands over network-sized chunks, not tidy events."""
    whole = b"".join(OPENAI_STREAM)
    framer = translate.stream("anthropic", "openai")
    blob = b"".join(framer.feed(whole[i:i + 7]) for i in range(0, len(whole), 7))
    blob += framer.close()
    text = "".join(d["delta"]["text"] for n, d in sse_events(blob)
                   if n == "content_block_delta")
    assert text == "Hello"


def test_a_streamed_tool_call_is_reassembled_as_a_tool_use_block():
    chunks = [
        b'data: {"id":"c","choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
        b'"function":{"name":"read","arguments":""}}]}}]}\n\n',
        b'data: {"id":"c","choices":[{"delta":{"tool_calls":[{"index":0,'
        b'"function":{"arguments":"{\\"path\\":"}}]}}]}\n\n',
        b'data: {"id":"c","choices":[{"delta":{"tool_calls":[{"index":0,'
        b'"function":{"arguments":"\\"a.py\\"}"}}]}}]}\n\n',
        b'data: {"id":"c","choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n',
        b'data: [DONE]\n\n',
    ]
    framer = translate.stream("anthropic", "openai")
    events = sse_events(b"".join(framer.feed(c) for c in chunks) + framer.close())
    block = next(d for n, d in events if n == "content_block_start")["content_block"]
    assert block == {"type": "tool_use", "id": "call_1", "name": "read", "input": {}}
    partial = "".join(d["delta"]["partial_json"] for n, d in events
                      if n == "content_block_delta")
    assert json.loads(partial) == {"path": "a.py"}
    assert next(d for n, d in events if n == "message_delta")["delta"]["stop_reason"] == "tool_use"


def test_text_and_a_tool_call_get_separate_numbered_blocks():
    chunks = [
        b'data: {"id":"c","choices":[{"delta":{"content":"working"}}]}\n\n',
        b'data: {"id":"c","choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
        b'"function":{"name":"read","arguments":"{}"}}]}}]}\n\n',
        b'data: [DONE]\n\n',
    ]
    framer = translate.stream("anthropic", "openai")
    events = sse_events(b"".join(framer.feed(c) for c in chunks))
    indexes = [(n, d.get("index")) for n, d in events if n.startswith("content_block")]
    assert indexes == [("content_block_start", 0), ("content_block_delta", 0),
                       ("content_block_stop", 0), ("content_block_start", 1),
                       ("content_block_delta", 1), ("content_block_stop", 1)]


def test_closing_twice_writes_nothing_the_second_time():
    """`[DONE]` closes the stream and so does the proxy when the body ends."""
    framer = translate.stream("anthropic", "openai")
    framer.feed(b"".join(OPENAI_STREAM))
    assert framer.close() == b""


def test_a_stream_that_dies_before_it_starts_still_terminates():
    framer = translate.stream("anthropic", "openai", "m")
    names = [n for n, _ in sse_events(framer.close())]
    assert names == ["message_start", "message_delta", "message_stop"]


# --- through the proxy ------------------------------------------------------------------

def _first_turn(text="hey there", stream=False):
    body = {"model": "claude-opus-5", "max_tokens": 50,
            "messages": [{"role": "user", "content": text}]}
    if stream:
        body["stream"] = True
    return body


def _route_to_openai(cfg, monkeypatch):
    cfg.tier3 = True
    cfg.tier3_opts.rules = [{"max_difficulty": 1.0, "upstream": "openai",
                             "model": "gpt-4o-mini"}]
    monkeypatch.setattr("random.choice", lambda seq: "treatment")


async def test_claude_code_reaches_an_openai_model_and_never_sees_the_difference(
        client, proxy_app, monkeypatch):
    """The headline case, end to end: an Anthropic request goes out as OpenAI and the
    reply arrives back as Anthropic."""
    _app, cfg, led, up = proxy_app
    _route_to_openai(cfg, monkeypatch)
    r = await client.post("/anthropic/v1/messages", json=_first_turn(),
                          headers={"x-api-key": "k"})

    assert up.last["path"] == "/v1/chat/completions"
    sent = up.last["body"]
    assert sent["model"] == "gpt-4o-mini"
    assert sent["messages"] == [{"role": "user", "content": "hey there"}]
    assert "system" not in sent and "stop_sequences" not in sent

    assert r.status_code == 200
    got = r.json()
    assert got["type"] == "message" and got["role"] == "assistant"
    assert got["content"][0]["text"] == "hi"
    assert got["stop_reason"] == "end_turn"

    kinds = [e["kind"] for e in led.events()]
    assert "protocol_translated" in kinds
    # usage is read from what the upstream actually said, not from the rewritten reply
    assert led.stats(0)["cache_read"] == 80


async def test_a_translated_stream_arrives_as_anthropic_events(client, proxy_app, monkeypatch):
    _app, cfg, led, up = proxy_app
    _route_to_openai(cfg, monkeypatch)
    r = await client.post("/anthropic/v1/messages", json=_first_turn(stream=True),
                          headers={"x-api-key": "k"})
    assert up.last["body"]["stream_options"] == {"include_usage": True}
    names = [n for n, _ in sse_events(r.content)]
    assert names[0] == "message_start" and names[-1] == "message_stop"
    assert "content_block_delta" in names
    assert "data: [DONE]" not in r.text
    assert led.stats(0)["output_tokens"] == 5


async def test_the_opening_event_carries_a_size_so_the_context_meter_is_not_blank(
        client, proxy_app, monkeypatch):
    """OpenAI reports usage only at the end of a stream, so message_start has to carry
    tokunseba's own count or the client's context indicator opens at zero."""
    _app, cfg, led, up = proxy_app
    _route_to_openai(cfg, monkeypatch)
    r = await client.post("/anthropic/v1/messages", json=_first_turn(stream=True),
                          headers={"x-api-key": "k"})
    start = dict(sse_events(r.content))["message_start"]
    assert start["message"]["usage"]["input_tokens"] > 0
    # and the real figure still wins once the upstream reports it
    delta = dict(sse_events(r.content))["message_delta"]
    assert delta["usage"] == {"input_tokens": 20, "cache_read_input_tokens": 80,
                              "cache_creation_input_tokens": 0, "output_tokens": 5}


async def test_a_target_with_no_translator_is_refused_not_attempted(client, proxy_app,
                                                                    monkeypatch):
    _app, cfg, led, up = proxy_app
    cfg.tier3 = True
    cfg.tier3_opts.rules = [{"max_difficulty": 1.0, "upstream": "gemini"}]
    monkeypatch.setattr("random.choice", lambda seq: "treatment")
    await client.post("/anthropic/v1/messages", json=_first_turn(), headers={"x-api-key": "k"})
    assert up.last["path"] == "/v1/messages"
    assert "route_refused" in [e["kind"] for e in led.events()]
