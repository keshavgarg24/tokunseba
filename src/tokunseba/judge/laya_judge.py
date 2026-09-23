"""Laya backend: open weights, Apache 2.0, runs locally on CPU or Apple MPS, costs nothing.

Laya is an encoder with a small state budget, so every state is trimmed before it is asked.
Its own documentation reports that base checkpoints score near chance on unfamiliar custom
questions, which is exactly why the chain only ever acts on a high-confidence answer.
"""
from __future__ import annotations

import threading
from pathlib import Path

STATE_CHARS = 1200  # the English checkpoint leaves roughly 320 tokens for state

# What enabling this actually costs, quoted verbatim by the CLI so the numbers never drift
# apart from the code. RAM is resident set size measured after a real load on Apple Silicon,
# not the size of the weight file: torch's runtime is most of it.
DOWNLOAD_MB = 808
RESIDENT_MB = 2200

# One process loads one copy. Every Proxy instance builds its own LayaJudge, and the test
# suite and the launch agent can build several, so without this the same 2.2 GB is taken
# once per instance. Keyed by the checkpoint actually asked for.
_AGENTS: dict[tuple[str, str], object] = {}
_AGENT_LOCK = threading.Lock()


def installed() -> bool:
    """Whether the laya extra is importable, without importing it.

    `import laya` pulls torch in, which costs about 65 MB of resident memory and a visible
    pause. Availability is asked by status commands and by the judge chain on every request,
    so it has to be answerable without paying that.
    """
    from importlib.util import find_spec
    try:
        return find_spec("laya") is not None
    except (ImportError, ValueError):
        return False


def weights_cached(model_id: str = "convaiinnovations/laya") -> bool:
    """True when the checkpoint is already on disk, so loading needs no network."""
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    if not hub.exists():
        return False
    slug = "models--" + model_id.replace("/", "--")
    return any(hub.glob(slug + "*"))


def _truncate(state, limit: int = STATE_CHARS):
    if isinstance(state, str):
        return state[:limit] + (" [...]" if len(state) > limit else "")
    if isinstance(state, dict):
        if not state:
            return state
        per = max(limit // max(len(state), 1), 120)
        return {k: (v[:per] + " [...]" if isinstance(v, str) and len(v) > per else v)
                for k, v in state.items()}
    return state


class LayaJudge:
    name = "laya"

    def __init__(self, model_id: str = "convaiinnovations/laya", device: str = "auto"):
        self.model_id = model_id
        self.device = device
        self._agent = None
        self._failed = False

    def ready(self) -> bool:
        """Loaded and usable right now, with no download or startup cost."""
        return self._agent is not None

    def available(self) -> bool:
        if self._failed:
            return False
        return installed()

    def load(self) -> None:
        """Load the checkpoint, quietly, and at most once per process.

        The upstream library prints a download progress bar and a calibration warning to
        stderr. Neither is actionable for someone running a CLI command, and both wreck the
        layout of a rendered table, so they are suppressed here rather than shown.
        """
        if self._agent is not None:
            return
        key = (self.model_id, self.device)
        with _AGENT_LOCK:
            cached = _AGENTS.get(key)
            if cached is not None:
                self._agent = cached
                return
            import os
            import warnings
            os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
            os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
            warnings.filterwarnings("ignore", category=RuntimeWarning, module="laya.*")
            import laya
            if self.device and self.device != "auto":
                agent = laya.Agent(self.model_id, device=self.device)
            else:
                agent = laya.load(self.model_id)
            _AGENTS[key] = agent
            self._agent = agent

    def unload(self) -> None:
        """Drop this process's reference to the weights so the memory can be reclaimed."""
        with _AGENT_LOCK:
            _AGENTS.pop((self.model_id, self.device), None)
        self._agent = None

    def ask(self, state, questions: dict) -> dict[str, "Answer"]:  # noqa: F821
        from .base import Answer
        if self._agent is None:
            try:
                self.load()
            except Exception:
                self._failed = True
                raise
        res = self._agent.predict(_truncate(state), questions)
        out: dict[str, Answer] = {}
        for k, a in (res.get("answers") or {}).items():
            t = a.get("type")
            if t == "choice":
                v = a.get("choice")
            elif t == "score":
                v = a.get("score")
            else:
                v = a.get("noul")
            if v is None:
                continue
            probs = a.get("probabilities") or {}
            out[k] = Answer(t or "noul", v, float(a.get("confidence") or 0.0),
                            {str(kk): float(vv) for kk, vv in probs.items()} if isinstance(probs, dict) else {})
        return out
