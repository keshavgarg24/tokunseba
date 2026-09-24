"""tokunseba as a library, for code that is not behind the proxy.

The proxy is the easy path: point a tool at it and nothing else changes. But plenty of
things are not a tool with a base URL -- a LangChain callback, a LiteLLM hook, an ASGI
middleware, a script that assembles its own request, a harness that wants to shrink one
blob before pasting it into a prompt. Those get the same three functions the proxy uses:

    from tokunseba import compress, shrink, expand

    out = compress(body, protocol="anthropic")   # a whole request, either wire shape
    text = shrink(log, path="server.log")        # one piece of text
    original = expand("h_4b91c07e")              # whatever was folded, byte for byte

This is the same pipeline the proxy runs, against the same ledger and the same handle
store under `~/.tokunseba`. That is the point: a handle minted by a library call expands
from the command line, a library call shows up in `tokunseba stats`, and what the library
does to a request is by construction what the proxy would have done to it.

Nothing here starts a server, opens a socket, or sends anything anywhere.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Change", "Result", "compress", "expand", "shrink"]


@dataclass(frozen=True)
class Change:
    """One substitution the pipeline made, and where."""
    position: str
    kind: str
    tokens_before: int
    tokens_after: int
    handle: str

    @property
    def saved(self) -> int:
        return max(self.tokens_before - self.tokens_after, 0)


@dataclass
class Result:
    """A request as it should go out, and an account of what happened to it."""
    body: dict
    changes: list[Change] = field(default_factory=list)
    tokens_before: int = 0
    tokens_after: int = 0

    @property
    def saved(self) -> int:
        return max(self.tokens_before - self.tokens_after, 0)

    @property
    def ratio(self) -> float:
        """Share of the countable tokens that did not have to be sent. 0.0 to 1.0."""
        return (self.saved / self.tokens_before) if self.tokens_before else 0.0

    def __bool__(self) -> bool:
        return bool(self.changes)


def _parts(cfg=None, home: str | Path | None = None):
    """The pieces the pipeline needs, sharing the CLI's config, ledger and blob store."""
    from . import config as _config
    from .ledger import Ledger
    from .tokens.estimator import Estimator
    from .transform.handles import HandleStore
    from .transform.pipeline import Pipeline
    root = Path(home) if home else _config.home()
    cfg = cfg or _config.load()
    ledger = Ledger(root / "ledger.sqlite")
    handles = HandleStore(root / "blobs")
    return cfg, ledger, Pipeline(cfg, ledger, handles, Estimator(None)), handles


def compress(body: dict, *, protocol: str = "anthropic", session_id: str = "",
             request_id: str = "", cfg=None, home: str | Path | None = None) -> Result:
    """Shrink a request body in place of sending it, and say what was done to it.

    `protocol` names the wire shape `body` is in: "anthropic", "openai", "ollama" or
    "gemini". The returned `body` is in that same shape and can be sent as it stands.

    Only tool results are ever rewritten. A prompt someone typed, a system prompt, and an
    assistant's own replies are forwarded exactly as they arrived, whatever is in them.

    `session_id` is worth passing when you have one. The deduplicator is per request as
    far as correctness goes, but the ledger groups by session, so without one every call
    looks like a separate conversation in `tokunseba stats`.
    """
    from .protocols import ADAPTERS
    adapter = ADAPTERS.get(protocol)
    if adapter is None:
        raise ValueError(f"unknown protocol {protocol!r}; "
                         f"expected one of {', '.join(sorted(ADAPTERS))}")
    cfg, ledger, pipe, _handles = _parts(cfg, home)
    try:
        res = pipe.apply(adapter.parse(body), body, 0,
                         session_id or f"lib-{uuid.uuid4().hex[:8]}",
                         request_id or uuid.uuid4().hex[:12])
    finally:
        ledger.close()
    return Result(
        body=res.body,
        changes=[Change(a.position, a.kind, a.before, a.after, a.handle) for a in res.applied],
        tokens_before=res.tokens_before,
        tokens_after=res.tokens_after,
    )


def shrink(text: str, *, path: str | None = None, tool: str | None = None,
           command: str | None = None, cfg=None,
           home: str | Path | None = None) -> str:
    """Shrink one piece of text the way a tool result would be shrunk, and return it.

    `path` is what makes a source file get outlined rather than truncated, and what lets a
    lock file be recognised, so pass it when you have it. `command` does the same job for
    program output: "pytest -q" is recognised where the same text on its own is not.

    The returned text carries its own recovery instruction when anything was left out.
    """
    if not text:
        return text
    cfg, ledger, pipe, _handles = _parts(cfg, home)
    tool_use_id = f"lib_{uuid.uuid4().hex[:10]}"
    body = {
        "model": "claude-sonnet-5",
        "messages": [
            {"role": "assistant", "content": [{
                "type": "tool_use", "id": tool_use_id, "name": tool or ("Read" if path else "Bash"),
                "input": ({"file_path": path} if path else {"command": command or ""}),
            }]},
            {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": tool_use_id,
                "content": [{"type": "text", "text": text}],
            }]},
        ],
    }
    from .protocols import ADAPTERS
    try:
        res = pipe.apply(ADAPTERS["anthropic"].parse(body), body, 0,
                         f"lib-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:12])
    finally:
        ledger.close()
    return res.body["messages"][1]["content"][0]["content"][0]["text"]


def expand(handle: str, *, home: str | Path | None = None) -> str | None:
    """The full original behind a handle, exactly as it arrived. None if it is not there.

    None rather than an exception because the usual reason is ordinary: the retention
    window passed and the blob was pruned, or the text held something that looked like a
    credential and was therefore never written down in the first place.
    """
    from . import config as _config
    from .transform.handles import HandleStore
    root = Path(home) if home else _config.home()
    return HandleStore(root / "blobs").get(handle)
