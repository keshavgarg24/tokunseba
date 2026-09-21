from tokunseba.protocols.ollama import OllamaAdapter
from tokunseba.tokens.context import DEFAULT_CONTEXT, context_length, request_budget

O = OllamaAdapter()


class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p


class FakeClient:
    def __init__(self, payload, status=200, boom=False):
        self._p, self._s, self._boom, self.calls = payload, status, boom, 0

    async def post(self, *a, **k):
        self.calls += 1
        if self._boom:
            raise RuntimeError("down")
        return FakeResp(self._p, self._s)


async def test_context_length_read_and_cached(home):
    from tokunseba.ledger import Ledger
    led = Ledger(home / "l.sqlite")
    c = FakeClient({"model_info": {"general.architecture": "llama", "llama.context_length": 8192}})
    assert await context_length(c, "http://x", "llama3.1", led) == 8192
    assert await context_length(c, "http://x", "llama3.1", led) == 8192
    assert c.calls == 1


async def test_context_length_falls_back_when_probe_fails(home):
    from tokunseba.ledger import Ledger
    led = Ledger(home / "l.sqlite")
    assert await context_length(FakeClient(None, boom=True), "http://x", "m", led) == DEFAULT_CONTEXT


async def test_context_length_scans_for_any_arch(home):
    from tokunseba.ledger import Ledger
    led = Ledger(home / "l.sqlite")
    c = FakeClient({"model_info": {"qwen3.context_length": 32768}})
    assert await context_length(c, "http://x", "qwen3", led) == 32768


def test_num_ctx_overrides_the_window():
    n = O.parse({"model": "m", "messages": []})
    assert request_budget(n, {"options": {"num_ctx": 4096}}, 131072) == 4096 - 1024
    assert request_budget(n, {}, 8192) == 8192 - 1024


async def test_overflow_is_reported(client, proxy_app):
    _app, _cfg, led, _up = proxy_app
    huge = "word " * 60000
    await client.post("/ollama/api/chat",
                      json={"model": "llama3.1",
                            "messages": [{"role": "user", "content": huge}]})
    assert led.stats(0)["events"]["context_overflow_risk"] == 1


async def test_no_overflow_for_small_requests(client, proxy_app):
    _app, _cfg, led, _up = proxy_app
    await client.post("/ollama/api/chat",
                      json={"model": "llama3.1", "messages": [{"role": "user", "content": "hi"}]})
    assert "context_overflow_risk" not in led.stats(0)["events"]
