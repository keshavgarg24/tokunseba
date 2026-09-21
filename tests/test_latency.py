"""The proxy must not add meaningful latency, and the judge must never sit in the hot path."""
import time


def _msg(text="hi"):
    return {"model": "claude-opus-5", "max_tokens": 50, "system": "s" * 6000,
            "messages": [{"role": "user", "content": text}]}


async def test_proxy_overhead_is_small(client, proxy_app):
    _app, _cfg, _led, _up = proxy_app
    await client.post("/anthropic/v1/messages", json=_msg(), headers={"x-api-key": "k"})
    t0 = time.monotonic()
    for _ in range(10):
        await client.post("/anthropic/v1/messages", json=_msg(), headers={"x-api-key": "k"})
    per_request_ms = (time.monotonic() - t0) * 100
    assert per_request_ms < 60, f"{per_request_ms:.1f}ms per request is too slow"


async def test_judge_is_never_called_inline_by_default(client, proxy_app, monkeypatch):
    app, cfg, _led, _up = proxy_app
    cfg.tier3 = True
    calls = []

    async def spy(state, questions, timeout=None):
        calls.append(state)
        return {}
    monkeypatch.setattr(app.state.proxy.judge, "ask", spy)
    await client.post("/anthropic/v1/messages", json=_msg(), headers={"x-api-key": "k"})
    assert calls == [], "the judge must not block the request path by default"


async def test_a_slow_judge_cannot_delay_a_request(client, proxy_app, monkeypatch):
    app, cfg, _led, _up = proxy_app
    cfg.tier3 = True

    async def slow(state, questions, timeout=None):
        import asyncio
        await asyncio.sleep(3)
        return {}
    monkeypatch.setattr(app.state.proxy.judge, "ask", slow)
    t0 = time.monotonic()
    r = await client.post("/anthropic/v1/messages", json=_msg(), headers={"x-api-key": "k"})
    assert r.status_code == 200
    assert (time.monotonic() - t0) < 1.0


async def test_large_tool_output_stays_fast(client, proxy_app):
    _app, _cfg, led, _up = proxy_app
    big = "\n".join(f"{i}: some output line with content" for i in range(5000))
    body = _msg()
    body["messages"] = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "make"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": big}]}]}]
    t0 = time.monotonic()
    await client.post("/anthropic/v1/messages", json=body, headers={"x-api-key": "k"})
    assert (time.monotonic() - t0) < 1.5
    assert led.stats(0)["tokens_saved"] > 0
