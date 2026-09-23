"""The proxy itself.

Lifecycle per request: parse, match the session, guard the delta, transform the delta,
protect the cache, optionally route, forward untouched-in-meaning, then record what it took.
The response body is always streamed back byte for byte.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import time
from dataclasses import dataclass, field
from uuid import uuid4

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from .cache import guardian, inject
from .config import Config, home
from .guards import injection, secrets
from .judge import build_chain, router_questions
from .ledger import Ledger, RequestRecord
from .protocols import ADAPTERS
from .protocols.base import json_get, json_set
from .session import SessionIndex
from .sse import NDJSONCollector, SSECollector
from .tier3 import effort as tier3_effort
from .tier3 import routing as tier3_routing
from .tokens.estimator import Estimator
from .transform.handles import HandleStore
from .transform.pipeline import Pipeline

BUDGET_BODY = {
    "type": "error",
    "error": {"type": "tokunseba_budget",
              "message": "daily token budget exceeded; "
                         "run: tokunseba config set budget.hard_stop false"},
}


@dataclass
class RequestContext:
    request_id: str
    tool_id: str
    project: str = ""
    session_id: str = ""
    arm: str = ""
    delta_start: int = 0
    turn_index: int = 0
    est_before: int = 0
    est_after: int = 0
    injected_cache_read: int = 0
    injected: int = 0
    breakpoints: list = field(default_factory=list)
    regions: dict = field(default_factory=dict)
    region_text: dict = field(default_factory=dict)
    delta_chars: int = 0
    body_path: str = ""
    signals: dict = field(default_factory=dict)
    annotate: list = field(default_factory=list)
    _lock: object = None

    async def enter_session_lock(self, lock) -> None:
        await lock.acquire()
        self._lock = lock

    def release_session_lock(self) -> None:
        if self._lock is not None:
            self._lock.release()
            self._lock = None


def tool_id_from_headers(headers, prefix: str) -> str:
    explicit = headers.get("x-tokunseba-tool")
    if explicit:
        return explicit
    ua = (headers.get("user-agent") or "").lower()
    for needle, name in (("claude-cli", "claude-code"), ("claude-code", "claude-code"),
                         ("codex", "codex"), ("aider", "aider"), ("cline", "cline"),
                         ("continue", "continue"), ("opencode", "opencode"), ("gemini", "gemini-cli"),
                         ("cursor", "cursor"), ("zed", "zed")):
        if needle in ua:
            return name
    return prefix


class Proxy:
    def __init__(self, cfg: Config, ledger: Ledger, transport=None):
        from .upstream import make_client
        self.cfg = cfg
        self.ledger = ledger
        self.client = make_client(transport)
        self.sessions = SessionIndex()
        self.est = Estimator(ledger)
        self.handles = HandleStore(home() / "blobs")
        self.judge = build_chain(cfg, ledger)
        self.pipeline = Pipeline(cfg, ledger, self.handles, self.est,
                                 pre_store=lambda t: not secrets.has_secret(t))
        self._background: set = set()
        self.bodies = home() / "bodies"
        if cfg.store_bodies:
            self.bodies.mkdir(parents=True, exist_ok=True)
        self._warm_judge()
        from .retention import maybe_run
        pruned = maybe_run(cfg, ledger, home())
        if pruned and not pruned.get("skipped"):
            ledger.record_event("pruned", pruned)

    def _warm_judge(self) -> None:
        """Load the local judge once, off the request path, and only if it is already on disk.

        Three conditions all have to hold, because the load costs about 2.2 GB of resident
        memory: the user enabled the judge, asked for it to be warmed, and already has the
        weights. Downloading is never implicit; `tokunseba judge install` fetches them.
        """
        j = self.cfg.judge
        if not (j.enabled and j.warm) or os.environ.get("TOKUNSEBA_NO_WARM"):
            return
        import threading
        from .judge.laya_judge import weights_cached
        if not weights_cached(j.laya_model):
            return

        def load() -> None:
            for b in self.judge.backends:
                if getattr(b, "name", "") == "laya" and b.available():
                    try:
                        b.load()
                    except Exception as exc:  # noqa: BLE001
                        self.ledger.record_event("judge_error", {"error": str(exc)[:200]})

        threading.Thread(target=load, daemon=True, name="tokunseba-warm-judge").start()

    # ---------- helpers ----------
    def _adapter(self, kind: str, path: str):
        if kind == "ollama" and ("/v1/chat/completions" in path or "/v1/responses" in path):
            return ADAPTERS.get("openai")
        a = ADAPTERS.get(kind)
        return a if (a and a.matches(path)) else None

    def _project_for(self, ctx: RequestContext, body: dict) -> str:
        meta = body.get("metadata") if isinstance(body, dict) else None
        uid = (meta or {}).get("user_id", "") if isinstance(meta, dict) else ""
        if uid:
            for sid in self.ledger.tool_session_ids():
                if sid and sid in str(uid):
                    cwd = self.ledger.cwd_for_session(sid)
                    if cwd:
                        return cwd
        return self.ledger.recent_cwd(ctx.tool_id)

    # Regexes answer in microseconds. A quarter of a second is far more than they need and
    # far less than anyone would notice, so it bounds the damage if a backend misbehaves.
    CHEAP_JUDGE_TIMEOUT = 0.25

    def _judge_is_cheap(self) -> bool:
        """Whether asking the judge is fast enough to do inside a request.

        The rules backend is regexes, so it always is. The local model is not, which is
        what judge.inline exists to say yes to.
        """
        return self.cfg.judge.inline or not self.cfg.judge.enabled

    async def _signals_inline(self, norm, ctx) -> dict:
        """Signals for a decision the request is waiting on, under a hard time budget.

        The budget is enforced here rather than left to the backend, because a backend that
        ignored its own timeout would hold the request open. Running out of time means no
        signals, which means no routing, which means the turn goes where it was already
        going: the request is never the thing that pays.
        """
        budget = self.cfg.judge.timeout if self.cfg.judge.inline else self.CHEAP_JUDGE_TIMEOUT
        try:
            return await asyncio.wait_for(self._signals(norm, ctx, timeout=budget), budget)
        except Exception as exc:  # noqa: BLE001 - a judge may never break or stall a request
            self.ledger.record_event("judge_error",
                                     {"error": f"inline: {str(exc)[:120]}"},
                                     ctx.session_id, ctx.request_id)
            return {}

    async def _signals(self, norm, ctx, timeout: float | None = None) -> dict:
        """Ask the judge about the newest user message.

        The question set is tokunseba's own rather than laya's, so this costs nothing and
        imports nothing when the local model is off: the rules backend answers the same
        questions from regexes. When the local model is on it takes roughly 1.5 s per call on
        an M-series laptop, which is why this only runs in the request path if the user opted
        in via judge.inline. Otherwise it is scheduled afterwards and feeds the ledger only.
        """
        text = norm.last_user_text()
        if not text:
            return {}
        answers = await self.judge.ask({"request": text[:1200]}, router_questions(),
                                       timeout=timeout)
        sig = {}
        for k, a in answers.items():
            if a.confidence >= self.cfg.judge.gate_threshold:
                sig[k] = a.value
            sig[f"{k}_confidence"] = round(a.confidence, 3)
        if sig:
            self.ledger.record_event("route_signal", sig, ctx.session_id, ctx.request_id)
        return sig

    def _schedule(self, coro) -> None:
        """Run judge work after the response is on its way. Failures only reach the ledger."""
        async def guarded():
            try:
                await coro
            except Exception as exc:  # noqa: BLE001
                self.ledger.record_event("judge_error", {"error": str(exc)[:200]})
        try:
            task = asyncio.create_task(guarded())
            self._background.add(task)
            task.add_done_callback(self._background.discard)
        except RuntimeError:
            pass

    async def _corroborate_later(self, text: str, position: str, session_id: str,
                                 request_id: str) -> None:
        agreed = await injection.corroborate(self.judge, text)
        if agreed is not None:
            self.ledger.record_event("injection_corroborated",
                                     {"position": position, "agreed": agreed},
                                     session_id, request_id)

    async def _guards(self, norm, ctx) -> None:
        """Runs on every request, so everything here is a regex and stays sub-millisecond."""
        for i in range(ctx.delta_start, len(norm.messages)):
            for blk in norm.messages[i].blocks:
                if not blk.text:
                    continue
                found = secrets.scan(blk.text)
                if found:
                    kinds = sorted({f.kind for f in found})
                    self.ledger.record_event("secret_detected",
                                             {"kinds": kinds, "position": str(blk.path)},
                                             ctx.session_id, ctx.request_id)
                    if self.cfg.tier3 and self.cfg.tier3_opts.redact_secrets:
                        json_set(norm.raw, blk.path, secrets.redact(blk.text, found))
                        blk.text = json_get(norm.raw, blk.path)
                        self.ledger.record_event("secret_redacted", {"kinds": kinds},
                                                 ctx.session_id, ctx.request_id)
                if blk.kind == "tool_result" and injection.regex_suspicious(blk.text):
                    hits = injection.regex_suspicious(blk.text)
                    self.ledger.record_event("injection_suspected",
                                             {"position": str(blk.path), "signals": hits},
                                             ctx.session_id, ctx.request_id)
                    if "laya" in self.judge.available_names():
                        self._schedule(self._corroborate_later(
                            blk.text, str(blk.path), ctx.session_id, ctx.request_id))

    def _plan_annotations(self, norm, ctx: RequestContext) -> None:
        """Decide which tool results get the data-not-commands warning.

        This looks at every message, not just the delta, on purpose. The warning is a
        deterministic function of the content, so re-deriving it for a block that has
        become history reproduces the identical bytes and keeps the cached prefix intact.
        Deciding only for new blocks would send the same block annotated on one turn and
        bare on the next, which is exactly the drift this tool exists to prevent.
        """
        if not (self.cfg.tier3 and self.cfg.tier3_opts.annotate_injections):
            return
        for msg in norm.messages:
            for blk in msg.blocks:
                if blk.kind == "tool_result" and blk.text and injection.regex_suspicious(blk.text):
                    ctx.annotate.append(blk.path)

    def _annotate(self, body: dict, ctx: RequestContext) -> None:
        """Prefix each flagged tool result with the data-not-commands warning."""
        for path in ctx.annotate:
            try:
                current = json_get(body, path)
            except (KeyError, IndexError, TypeError):
                continue
            if isinstance(current, str) and injection.ANNOTATION not in current:
                json_set(body, path, injection.ANNOTATION + "\n" + current)

    # ---------- the before-forward chain ----------
    async def before(self, adapter, norm, body: dict, ctx: RequestContext) -> tuple[dict, str | None]:
        chain = norm.chain()
        match = self.sessions.match(chain)
        ctx.session_id = match.session_id
        # from here to commit, this conversation is ours alone
        await ctx.enter_session_lock(self.sessions.lock(match.session_id))
        ctx.delta_start = match.prefix_len
        st = self.sessions.get(match.session_id)
        ctx.turn_index = st.turns if st else 0
        ctx.project = self._project_for(ctx, body)

        arm = self.ledger.session_arm(match.session_id)
        if not arm:
            arm = random.choice(["control", "treatment"]) if self.cfg.tier3 else "control"
        ctx.arm = arm
        self.ledger.upsert_session(match.session_id, ctx.tool_id, ctx.project,
                                   norm.provider, norm.model, arm)

        await self._guards(norm, ctx)
        self._plan_annotations(norm, ctx)

        # Stored after the guards, never before: with redaction on, writing first would put
        # the credential in ~/.tokunseba/bodies in plain text, which is the same exposure
        # the redaction exists to prevent. `explain` therefore shows the redacted original.
        if self.cfg.store_bodies:
            p = self.bodies / f"{ctx.request_id}.orig.json"
            p.write_text(json.dumps(body))
            try:
                p.chmod(0o600)
            except OSError:
                pass
            ctx.body_path = str(p)

        res = self.pipeline.apply(norm, body, ctx.delta_start, ctx.session_id, ctx.request_id)
        body = res.body
        ctx.est_before, ctx.est_after = res.tokens_before, res.tokens_after
        if ctx.annotate:
            self._annotate(body, ctx)
            norm = adapter.parse(body)

        # Cache protection. Injection happens first and the drift check runs on the result,
        # because the request that matters is the one actually sent. Checking beforehand would
        # see no breakpoints at all for the clients tokunseba injects for, which is most of them.
        ttl = self.cfg.cache_ttl or None
        if not ttl and st and inject.ttl_advice(st.gaps) == "1h":
            self.ledger.record_event("ttl_advice", {"suggest": "1h"}, ctx.session_id, ctx.request_id)
        ctx.injected = inject.inject(norm, body, ctx.delta_start, self.est,
                                     self.cfg.thresholds.cache_min_tokens, ttl)
        if ctx.injected:
            self.ledger.record_event("cache_injected", {"n": ctx.injected},
                                     ctx.session_id, ctx.request_id)
            norm = adapter.parse(body)

        prev_bp = st.breakpoints if st else []
        prev_regions = st.regions if st else {}
        prev_text = st.region_text if st else {}
        cur_bp = guardian.breakpoints(norm)
        if prev_bp and cur_bp:
            for ev in guardian.check(prev_bp, cur_bp, prev_regions, norm, prev_text):
                self.ledger.record_event("cache_drift", {"region": ev.region, "cause": ev.cause},
                                         ctx.session_id, ctx.request_id)

        # tier 3. Gating needs the judge's answer before the request goes out. With the
        # local model that costs about 1.5 s, so it waits for judge.inline. With the rules
        # backend it costs microseconds, and making people opt into latency they are not
        # paying would mean routing never worked for anyone who had not downloaded 800 MB.
        reroute = None
        if self.cfg.tier3 and ctx.arm == "treatment" and self._judge_is_cheap():
            ctx.signals = await self._signals_inline(norm, ctx)
            if tier3_effort.apply(norm, body, ctx.signals, self.cfg):
                self.ledger.record_event("effort_set", {"effort": "low"},
                                         ctx.session_id, ctx.request_id)
            reroute, reason = tier3_routing.apply(norm, body, ctx.signals, self.cfg)
            if reason in ("model_routed", "local_routed", "rule_routed"):
                self.ledger.record_event(reason, {"model": body.get("model"),
                                                  "upstream": reroute or ""},
                                         ctx.session_id, ctx.request_id)
            elif reason.startswith("rule-"):
                self.ledger.record_event("route_refused", {"reason": reason},
                                         ctx.session_id, ctx.request_id)
        elif match.is_new and self.judge.ready_names():
            # The judge runs by default, but only on the opening turn of a conversation, only
            # after the response has been dispatched, and only once it is already warm. A cold
            # model would mean loading 808 MB inside a request, so warming is a startup job.
            self._schedule(self._signals(norm, ctx))

        if norm.provider == "ollama":
            await self._check_local_fit(norm, body, ctx)

        ctx.breakpoints = cur_bp
        ctx.regions = guardian.regions(norm)
        ctx.region_text = {"tools": norm.tools_json, "system": norm.system_text}
        ctx.delta_chars = sum(len(b.text or "") for m in norm.messages[ctx.delta_start:] for b in m.blocks)
        self.sessions.commit(ctx.session_id, ctx.request_id, chain, cur_bp,
                             ctx.regions, ctx.region_text, 0, ctx.delta_chars)
        # released here, not after the upstream call: holding it through the response would
        # serialise every concurrent request in a conversation for no benefit
        ctx.release_session_lock()
        if self.cfg.store_bodies:
            sent_path = self.bodies / f"{ctx.request_id}.sent.json"
            sent_path.write_text(json.dumps(body))
            try:
                sent_path.chmod(0o600)
            except OSError:
                pass
        return body, reroute

    async def _check_local_fit(self, norm, body: dict, ctx: RequestContext) -> None:
        """A local server truncates a too-long prompt silently, which changes the answer."""
        from .tokens.context import context_length, request_budget
        up = self.cfg.upstreams.get("ollama")
        if up is None:
            return
        limit = await context_length(self.client, up.base_url, norm.model, self.ledger)
        budget = request_budget(norm, body, limit)
        used = self.est.count(json.dumps(body), norm.provider, norm.model)
        if used > budget:
            self.ledger.record_event("context_overflow_risk",
                                     {"estimated": used, "budget": budget, "window": limit},
                                     ctx.session_id, ctx.request_id)

    # ---------- recording ----------
    def finish(self, usage, norm, ctx: RequestContext, status: int, t0: float) -> None:
        self.ledger.record_request(RequestRecord(
            id=ctx.request_id, ts=time.time(), session_id=ctx.session_id, tool_id=ctx.tool_id,
            project=ctx.project, provider=norm.provider, model=norm.model, stream=norm.stream,
            input_tokens=usage.input_tokens, cache_read=usage.cache_read,
            cache_write=usage.cache_write, output_tokens=usage.output_tokens,
            est_tokens_before=ctx.est_before, est_tokens_after=ctx.est_after,
            arm=ctx.arm, status=status,
            latency_ms=int((time.monotonic() - t0) * 1000), body_path=ctx.body_path))
        miss = guardian.post_check(ctx.turn_index, bool(ctx.breakpoints), usage.cache_read)
        if miss:
            self.ledger.record_event(miss, {"turn": ctx.turn_index}, ctx.session_id, ctx.request_id)
        if ctx.delta_chars and usage.total_input:
            st = self.sessions.get(ctx.session_id)
            prev = st.total_input_tokens if st else 0
            delta_tokens = usage.total_input - prev
            if st:
                st.total_input_tokens = usage.total_input
            if delta_tokens > 0:
                self.est.learn(norm.provider, norm.model, ctx.delta_chars, delta_tokens)


def build_app(cfg: Config, ledger: Ledger, transport=None) -> Starlette:
    proxy = Proxy(cfg, ledger, transport)

    async def session_api(request: Request):
        data = await request.json()
        sid, tool, cwd = data.get("session_id", ""), data.get("tool", ""), data.get("cwd", "")
        if sid:
            ledger.register_tool_session(sid, tool, cwd)
        return JSONResponse({"ok": True})

    async def handle(request: Request):
        prefix = request.path_params["prefix"]
        sub = "/" + request.path_params["path"]
        up = cfg.upstreams.get(prefix)
        if up is None:
            return JSONResponse({"error": f"unknown upstream '{prefix}'"}, status_code=404)

        raw = await request.body()
        original_raw = raw
        ctx = RequestContext(request_id=uuid4().hex[:12],
                             tool_id=tool_id_from_headers(request.headers, prefix))
        adapter = proxy._adapter(up.kind, sub)
        body = None
        if adapter and raw:
            try:
                parsed = json.loads(raw)
                body = parsed if isinstance(parsed, dict) else None
            except ValueError:
                body = None

        t0 = time.monotonic()
        norm = None
        target = up
        if body is not None:
            norm = adapter.parse(body)
            if up.kind == "gemini" and not norm.model:
                norm.model = adapter.model_from_path(sub)
            adapter.ensure_stream_usage(body)
            if cfg.budget.daily_tokens > 0:
                day = time.time() - (time.time() % 86400)
                if ledger.tokens_since(day) > cfg.budget.daily_tokens:
                    ledger.record_event("budget_exceeded", {"limit": cfg.budget.daily_tokens})
                    if cfg.budget.hard_stop:
                        return JSONResponse(BUDGET_BODY, status_code=429)
            try:
                body, reroute = await proxy.before(adapter, norm, body, ctx)
                if reroute and reroute in cfg.upstreams:
                    target = cfg.upstreams[reroute]
                    sub = "/v1/chat/completions"
                model_was = norm.model
                norm = adapter.parse(body)
                if not norm.model:
                    norm.model = model_was
                raw = json.dumps(body).encode()
            except Exception as exc:  # noqa: BLE001
                # Optimising a request is never worth failing it. Forward exactly what the
                # client sent and make the bug loud in the ledger rather than in their editor.
                ctx.release_session_lock()
                ledger.record_event("passthrough_after_error",
                                    {"error": f"{type(exc).__name__}: {exc}"[:300],
                                     "model": norm.model},
                                    ctx.session_id, ctx.request_id)
                raw = original_raw
                ctx.est_before = ctx.est_after = 0
                ctx.injected = 0

        url = target.base_url.rstrip("/") + sub
        if request.url.query:
            url += "?" + request.url.query
        from .upstream import forward_headers, passthrough_headers
        req = proxy.client.build_request(request.method, url,
                                         headers=forward_headers(request.headers), content=raw)
        try:
            resp = await proxy.client.send(req, stream=True)
        except Exception as exc:  # noqa: BLE001
            ledger.record_event("upstream_error", {"error": str(exc)[:200], "url": url})
            return JSONResponse({"error": "upstream unreachable", "detail": str(exc)[:200]},
                                status_code=502)

        # opt-in failover for the same model on another endpoint
        if (cfg.failover.enabled and resp.status_code in (429, 500, 502, 503, 529)
                and body is not None and norm.model in cfg.failover.routes):
            route = cfg.failover.routes[norm.model]
            alt = cfg.upstreams.get(route.get("upstream", ""))
            if alt:
                import os
                await resp.aclose()
                headers = forward_headers(request.headers)
                key = os.environ.get(route.get("api_key_env", ""), "")
                if key and route.get("header"):
                    headers[route["header"]] = key
                alt_req = proxy.client.build_request(request.method, alt.base_url.rstrip("/") + sub,
                                                     headers=headers, content=raw)
                resp = await proxy.client.send(alt_req, stream=True)
                ledger.record_event("failover_used", {"model": norm.model}, ctx.session_id, ctx.request_id)

        ctype = resp.headers.get("content-type", "")
        streaming = body is not None and (ctype.startswith("text/event-stream")
                                          or ctype.startswith("application/x-ndjson"))
        if streaming:
            collector = SSECollector() if ctype.startswith("text/event-stream") else NDJSONCollector()

            async def tee():
                try:
                    async for chunk in resp.aiter_raw():
                        collector.feed(chunk)
                        yield chunk
                finally:
                    collector.close()
                    try:
                        if isinstance(collector, SSECollector):
                            usage = adapter.usage_from_sse(collector.events)
                        else:
                            fn = getattr(adapter, "usage_from_ndjson", None)
                            usage = fn(collector.objects) if fn else adapter.usage_from_sse(
                                [("", o) for o in collector.objects])
                        proxy.finish(usage, norm, ctx, resp.status_code, t0)
                    except Exception as exc:  # noqa: BLE001
                        ledger.record_event("record_error", {"error": str(exc)[:200]})
                    await resp.aclose()

            return StreamingResponse(tee(), status_code=resp.status_code,
                                     headers=passthrough_headers(resp.headers),
                                     media_type=ctype or None)

        content = await resp.aread()
        await resp.aclose()
        if body is not None and resp.status_code < 300:
            try:
                proxy.finish(adapter.usage_from_json(json.loads(content)), norm, ctx,
                             resp.status_code, t0)
            except (ValueError, TypeError):
                pass
        return Response(content, status_code=resp.status_code,
                        headers=passthrough_headers(resp.headers))

    routes = [
        Route("/_tokunseba/api/session", session_api, methods=["POST"]),
        Route("/{prefix}/{path:path}", handle,
              methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]),
    ]
    app = Starlette(routes=routes)
    app.state.proxy = proxy
    app.state.cfg = cfg
    app.state.ledger = ledger
    from .ui.api import mount_ui
    mount_ui(app, ledger, cfg)
    return app
