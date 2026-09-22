import json

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route


def _free_port() -> int:
    """A port nothing is listening on, so tests do not depend on whether the developer
    happens to have their own proxy running."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKUNSEBA_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def dead_port(home):
    """Point the config at a port with nothing behind it."""
    from tokunseba import config
    cfg = config.load()
    cfg.port = _free_port()
    config.save(cfg)
    return cfg.port


ANTHROPIC_JSON = {
    "id": "m1", "type": "message", "role": "assistant", "model": "claude-opus-5",
    "content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn",
    "usage": {"input_tokens": 12, "cache_read_input_tokens": 300,
              "cache_creation_input_tokens": 0, "output_tokens": 3},
}

ANTHROPIC_SSE = (
    'event: message_start\n'
    'data: {"type":"message_start","message":{"id":"m1","usage":'
    '{"input_tokens":12,"cache_read_input_tokens":300,"cache_creation_input_tokens":0,'
    '"output_tokens":1}}}\n\n'
    'event: content_block_delta\n'
    'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"hi"}}\n\n'
    'event: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":3}}\n\n'
    'event: message_stop\ndata: {"type":"message_stop"}\n\n'
)


class Recorder:
    def __init__(self):
        self.requests = []
        self.status = 200

    @property
    def last(self):
        return self.requests[-1]


@pytest.fixture
def upstream():
    rec = Recorder()

    async def capture(request):
        raw = await request.body()
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = None
        rec.requests.append({"path": request.url.path, "headers": dict(request.headers),
                             "body": body, "raw": raw, "query": str(request.url.query)})
        return body

    async def messages(request):
        body = await capture(request)
        if rec.status != 200:
            code, rec.status = rec.status, 200
            return Response('{"error":"transient"}', status_code=code,
                            media_type="application/json")
        if body and body.get("metadata", {}).get("truncate"):
            return StreamingResponse(truncated_gen(), media_type="text/event-stream")
        if body and body.get("stream"):
            async def gen():
                for part in ANTHROPIC_SSE.split("\n\n"):
                    if part.strip():
                        yield (part + "\n\n").encode()
            return StreamingResponse(gen(), media_type="text/event-stream")
        return Response(json.dumps(ANTHROPIC_JSON), media_type="application/json")

    async def truncated_gen():
        """A stream that dies in the middle of an event."""
        yield (b'event: message_start\ndata: {"type":"message_start","message":'
               b'{"usage":{"input_tokens":50,"cache_read_input_tokens":0,'
               b'"cache_creation_input_tokens":0,"output_tokens":1}}}\n\n')
        yield b'event: content_block_delta\ndata: {"type":"content_bl'

    async def chat(request):
        body = await capture(request)
        if body and body.get("stream"):
            chunks = [
                'data: {"id":"c","choices":[{"delta":{"content":"hi"}}]}\n\n',
                'data: {"id":"c","choices":[],"usage":{"prompt_tokens":100,'
                '"completion_tokens":5,"prompt_tokens_details":{"cached_tokens":80}}}\n\n',
                'data: [DONE]\n\n',
            ]

            async def gen():
                for c in chunks:
                    yield c.encode()
            return StreamingResponse(gen(), media_type="text/event-stream")
        return Response(json.dumps({"id": "c", "choices": [{"message": {"content": "hi"}}],
                                    "usage": {"prompt_tokens": 100, "completion_tokens": 5,
                                              "prompt_tokens_details": {"cached_tokens": 80}}}),
                        media_type="application/json")

    async def responses(request):
        await capture(request)
        return Response(json.dumps({"id": "r", "output": [],
                                    "usage": {"input_tokens": 200, "output_tokens": 10,
                                              "input_tokens_details": {"cached_tokens": 150}}}),
                        media_type="application/json")

    async def models(request):
        await capture(request)
        return Response(json.dumps({"data": [{"id": "claude-opus-5"}]}),
                        media_type="application/json")

    async def ollama_chat(request):
        await capture(request)
        lines = ['{"model":"llama3.1","message":{"content":"hi"},"done":false}\n',
                 '{"model":"llama3.1","done":true,"prompt_eval_count":700,"eval_count":20}\n']

        async def gen():
            for line in lines:
                yield line.encode()
        return StreamingResponse(gen(), media_type="application/x-ndjson")

    async def ollama_show(request):
        await capture(request)
        return Response(json.dumps({"model_info": {"general.architecture": "llama",
                                                   "llama.context_length": 8192}}),
                        media_type="application/json")

    async def gemini(request):
        await capture(request)
        return Response(json.dumps({"candidates": [], "usageMetadata": {
            "promptTokenCount": 100, "cachedContentTokenCount": 40,
            "candidatesTokenCount": 9}}), media_type="application/json")

    app = Starlette(routes=[
        Route("/v1/messages", messages, methods=["POST"]),
        Route("/v1/chat/completions", chat, methods=["POST"]),
        Route("/v1/responses", responses, methods=["POST"]),
        Route("/v1/models", models, methods=["GET"]),
        Route("/api/chat", ollama_chat, methods=["POST"]),
        Route("/api/show", ollama_show, methods=["POST"]),
        Route("/v1beta/models/{m}:generateContent", gemini, methods=["POST"]),
    ])
    rec.transport = httpx.ASGITransport(app=app)
    return rec


@pytest.fixture
def proxy_app(home, upstream):
    from tokunseba import config
    from tokunseba.ledger import Ledger
    from tokunseba.server import build_app
    cfg = config.load()
    for u in cfg.upstreams.values():
        u.base_url = "http://up.test"
    led = Ledger(home / "ledger.sqlite")
    app = build_app(cfg, led, transport=upstream.transport)
    return app, cfg, led, upstream


@pytest.fixture
def client(proxy_app):
    app, cfg, led, up = proxy_app
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://proxy.test")
