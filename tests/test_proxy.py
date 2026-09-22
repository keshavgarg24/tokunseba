import json


def _msg(text="hi", stream=False, system="s" * 6000, extra=None):
    body = {"model": "claude-opus-5", "max_tokens": 100, "system": system,
            "messages": [{"role": "user", "content": text}]}
    if stream:
        body["stream"] = True
    if extra:
        body.update(extra)
    return body


async def test_non_stream_passthrough_and_usage(client, proxy_app):
    _app, _cfg, led, up = proxy_app
    r = await client.post("/anthropic/v1/messages", json=_msg(),
                          headers={"x-api-key": "test", "anthropic-version": "2023-06-01",
                                   "user-agent": "claude-cli/2.0.0"})
    assert r.status_code == 200
    assert r.json()["content"][0]["text"] == "hi"
    assert up.last["headers"]["x-api-key"] == "test"
    assert up.last["headers"]["anthropic-version"] == "2023-06-01"
    s = led.stats(0)
    assert s["requests"] == 1 and s["cache_read"] == 300
    assert s["by_tool"][0]["tool"] == "claude-code"


async def test_stream_bytes_are_untouched(client, proxy_app):
    _app, _cfg, led, _up = proxy_app
    r = await client.post("/anthropic/v1/messages", json=_msg(stream=True),
                          headers={"x-api-key": "k"})
    assert r.status_code == 200
    assert "message_start" in r.text and "content_block_delta" in r.text
    assert led.stats(0)["requests"] == 1
    assert led.stats(0)["output_tokens"] == 3


async def test_unknown_path_forwarded_untouched(client, proxy_app):
    _app, _cfg, led, up = proxy_app
    r = await client.get("/anthropic/v1/models", headers={"x-api-key": "k"})
    assert r.status_code == 200 and r.json()["data"][0]["id"] == "claude-opus-5"
    assert led.stats(0)["requests"] == 0


async def test_unknown_upstream_is_404(client):
    assert (await client.post("/nope/v1/messages", json={})).status_code == 404


async def test_cache_control_is_injected(client, proxy_app):
    _app, _cfg, led, up = proxy_app
    await client.post("/anthropic/v1/messages", json=_msg(), headers={"x-api-key": "k"})
    sent = up.last["body"]
    assert sent["system"][0]["cache_control"]["type"] == "ephemeral"
    assert led.stats(0)["events"]["cache_injected"] == 1


async def test_session_continuity_and_delta(client, proxy_app):
    _app, _cfg, led, _up = proxy_app
    first = _msg("one")
    await client.post("/anthropic/v1/messages", json=first, headers={"x-api-key": "k"})
    second = _msg("one")
    second["messages"].append({"role": "assistant", "content": "ok"})
    second["messages"].append({"role": "user", "content": "two"})
    await client.post("/anthropic/v1/messages", json=second, headers={"x-api-key": "k"})
    sessions = {r["session_id"] for r in led.events(limit=100) if r["session_id"]}
    assert len(sessions) == 1
    assert led.recent_sessions()[0]["requests"] == 2


async def test_openai_stream_options_injected_and_usage(client, proxy_app):
    _app, _cfg, led, up = proxy_app
    await client.post("/openai/v1/chat/completions",
                      json={"model": "gpt-4o", "stream": True,
                            "messages": [{"role": "user", "content": "hi"}]},
                      headers={"authorization": "Bearer k"})
    assert up.last["body"]["stream_options"] == {"include_usage": True}
    s = led.stats(0)
    assert s["requests"] == 1 and s["cache_read"] == 80 and s["input_tokens"] == 100


async def test_openai_responses_usage(client, proxy_app):
    _app, _cfg, led, _up = proxy_app
    await client.post("/openai/v1/responses",
                      json={"model": "gpt-4o", "input": [
                          {"type": "message", "role": "user",
                           "content": [{"type": "input_text", "text": "hi"}]}]})
    assert led.stats(0)["cache_read"] == 150


async def test_ollama_ndjson_usage_and_free(client, proxy_app):
    _app, _cfg, led, _up = proxy_app
    r = await client.post("/ollama/api/chat",
                          json={"model": "llama3.1", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200 and "prompt_eval_count" in r.text
    s = led.stats(0)
    assert s["requests"] == 1 and s["input_tokens"] == 700 and s["usd_spent"] == 0.0


async def test_gemini_model_from_path(client, proxy_app):
    _app, _cfg, led, _up = proxy_app
    await client.post("/gemini/v1beta/models/gemini-2.5-pro:generateContent",
                      json={"contents": [{"role": "user", "parts": [{"text": "hi"}]}]})
    assert led.stats(0)["cache_read"] == 40


async def test_tool_result_is_compressed(client, proxy_app):
    _app, _cfg, led, up = proxy_app
    noisy = "\n".join(["\x1b[32mPASS\x1b[0m"] * 400)
    body = _msg()
    body["messages"] = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls -la"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": [{"type": "text", "text": noisy}]}]}]
    await client.post("/anthropic/v1/messages", json=body, headers={"x-api-key": "k"})
    sent_block = up.last["body"]["messages"][2]["content"][0]["content"][0]["text"]
    assert "\x1b[32m" not in sent_block
    assert len(sent_block) < len(noisy) / 10
    assert "repeated 399 more times" in sent_block
    assert led.stats(0)["tokens_saved"] > 0


async def test_identical_history_bytes_are_stable(client, proxy_app):
    """The frozen table must replay the same replacement, or the prompt cache dies."""
    _app, _cfg, led, up = proxy_app
    big = "\n".join(f"line {i}" for i in range(900))
    turn1 = _msg()
    turn1["messages"] = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/a.txt"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": big}]}]}]
    await client.post("/anthropic/v1/messages", json=turn1, headers={"x-api-key": "k"})
    first_sent = up.last["body"]["messages"][2]["content"][0]["content"][0]["text"]

    turn2 = json.loads(json.dumps(turn1))
    turn2["messages"].append({"role": "assistant", "content": "done"})
    turn2["messages"].append({"role": "user", "content": "next"})
    await client.post("/anthropic/v1/messages", json=turn2, headers={"x-api-key": "k"})
    second_sent = up.last["body"]["messages"][2]["content"][0]["content"][0]["text"]
    assert first_sent == second_sent


async def test_secret_is_detected_not_sent_to_blob(client, proxy_app, home):
    _app, _cfg, led, _up = proxy_app
    body = _msg("here is my key AKIAIOSFODNN7EXAMPLE ok")
    await client.post("/anthropic/v1/messages", json=body, headers={"x-api-key": "k"})
    assert led.stats(0)["events"]["secret_detected"] == 1


async def test_budget_hard_stop(client, proxy_app):
    _app, cfg, led, _up = proxy_app
    await client.post("/anthropic/v1/messages", json=_msg(), headers={"x-api-key": "k"})
    cfg.budget.daily_usd = 0.0000001
    cfg.budget.hard_stop = True
    r = await client.post("/anthropic/v1/messages", json=_msg(), headers={"x-api-key": "k"})
    assert r.status_code == 429 and r.json()["error"]["type"] == "tokunseba_budget"


async def test_budget_warn_only_by_default(client, proxy_app):
    _app, cfg, led, _up = proxy_app
    await client.post("/anthropic/v1/messages", json=_msg(), headers={"x-api-key": "k"})
    cfg.budget.daily_usd = 0.0000001
    r = await client.post("/anthropic/v1/messages", json=_msg(), headers={"x-api-key": "k"})
    assert r.status_code == 200
    assert led.stats(0)["events"]["budget_exceeded"] >= 1


async def test_upstream_error_becomes_502(client, proxy_app, monkeypatch):
    app, _cfg, led, _up = proxy_app

    async def boom(*a, **k):
        raise RuntimeError("no route to host")
    monkeypatch.setattr(app.state.proxy.client, "send", boom)
    r = await client.post("/anthropic/v1/messages", json=_msg(), headers={"x-api-key": "k"})
    assert r.status_code == 502
    assert led.stats(0)["events"]["upstream_error"] == 1


async def test_session_api_registers_cwd(client, proxy_app):
    _app, _cfg, led, _up = proxy_app
    r = await client.post("/_tokunseba/api/session",
                          json={"session_id": "s-1", "tool": "claude-code", "cwd": "/w/p"})
    assert r.json()["ok"]
    assert led.cwd_for_session("s-1") == "/w/p"


async def test_dashboard_api_endpoints(client, proxy_app):
    _app, _cfg, _led, _up = proxy_app
    await client.post("/anthropic/v1/messages", json=_msg(), headers={"x-api-key": "k"})
    for path in ("stats", "events", "sessions", "daily", "ab"):
        r = await client.get(f"/_tokunseba/api/{path}")
        assert r.status_code == 200
    assert (await client.get("/_tokunseba/api/stats")).json()["requests"] == 1


async def test_failover_retries_on_529(client, proxy_app):
    _app, cfg, led, up = proxy_app
    cfg.failover.enabled = True
    cfg.failover.routes = {"claude-opus-5": {"upstream": "anthropic", "api_key_env": "NOPE",
                                             "header": "x-api-key"}}
    up.status = 529
    r = await client.post("/anthropic/v1/messages", json=_msg(), headers={"x-api-key": "k"})
    assert r.status_code == 200
    assert led.stats(0)["events"]["failover_used"] == 1


async def test_multi_turn_conversation_keeps_history_byte_stable(client, proxy_app):
    """The core production property: a growing conversation must re-send identical bytes for
    every turn it already sent, or the prompt cache breaks and the tool costs more than it saves.
    """
    _app, _cfg, led, up = proxy_app
    outputs = ["\n".join(f"turn {t} line {i}: some output" for i in range(400)) for t in range(4)]
    messages = [{"role": "user", "content": "start"}]
    seen: list[list[str]] = []

    for turn in range(4):
        messages.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": f"t{turn}", "name": "Bash",
             "input": {"command": f"make step{turn}"}}]})
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{turn}",
             "content": [{"type": "text", "text": outputs[turn]}]}]})
        await client.post("/anthropic/v1/messages",
                          json={"model": "claude-opus-5", "max_tokens": 50,
                                "system": "s" * 6000, "messages": json.loads(json.dumps(messages))},
                          headers={"x-api-key": "k"})
        sent = up.last["body"]["messages"]
        seen.append([m["content"][0]["content"][0]["text"]
                     for m in sent if isinstance(m.get("content"), list)
                     and m["content"][0].get("type") == "tool_result"])

    for turn in range(1, 4):
        assert seen[turn][:turn] == seen[turn - 1], (
            f"turn {turn} rewrote history that turn {turn - 1} had already sent")
    assert led.stats(0)["requests"] == 4
    assert led.stats(0)["tokens_saved"] > 0


async def test_a_reordered_tool_list_is_reported_not_silently_paid_for(client, proxy_app):
    """Clients that rebuild their tool array in a different order silently kill the cache."""
    _app, _cfg, led, _up = proxy_app
    base = {"model": "claude-opus-5", "max_tokens": 50, "system": "s" * 6000,
            "messages": [{"role": "user", "content": "hi"}]}
    a = dict(base, tools=[{"name": "alpha", "input_schema": {}}, {"name": "beta", "input_schema": {}}])
    await client.post("/anthropic/v1/messages", json=a, headers={"x-api-key": "k"})
    b = dict(base, tools=[{"name": "beta", "input_schema": {}}, {"name": "alpha", "input_schema": {}}])
    await client.post("/anthropic/v1/messages", json=b, headers={"x-api-key": "k"})
    assert led.stats(0)["events"].get("cache_drift", 0) >= 1


async def test_malformed_upstream_response_does_not_break_the_client(client, proxy_app, monkeypatch):
    _app, _cfg, led, _up = proxy_app
    import httpx

    async def bad(req, **kw):
        return httpx.Response(200, content=b"not json at all",
                              headers={"content-type": "application/json"},
                              request=req)
    monkeypatch.setattr(_app.state.proxy.client, "send", bad)
    r = await client.post("/anthropic/v1/messages",
                          json={"model": "claude-opus-5", "max_tokens": 5,
                                "messages": [{"role": "user", "content": "hi"}]},
                          headers={"x-api-key": "k"})
    assert r.status_code == 200 and r.content == b"not json at all"


async def test_truncated_stream_still_records_what_it_saw(client, proxy_app):
    """A stream that dies mid-event must still deliver what arrived and record the usage."""
    _app, _cfg, led, _up = proxy_app
    r = await client.post("/anthropic/v1/messages",
                          json={"model": "claude-opus-5", "max_tokens": 5, "stream": True,
                                "metadata": {"truncate": True},
                                "messages": [{"role": "user", "content": "hi"}]},
                          headers={"x-api-key": "k"})
    assert r.status_code == 200
    assert "message_start" in r.text
    assert led.stats(0)["requests"] == 1
    assert led.stats(0)["input_tokens"] == 50
