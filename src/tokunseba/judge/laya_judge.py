"""Laya backend: open weights, Apache 2.0, runs locally on CPU or Apple MPS, costs nothing.

Laya is an encoder with a small state budget, so every state is trimmed before it is asked.
Its own documentation reports that base checkpoints score near chance on unfamiliar custom
questions, which is exactly why the chain only ever acts on a high-confidence answer.
"""
from __future__ import annotations

STATE_CHARS = 1200  # the English checkpoint leaves roughly 320 tokens for state


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

    def available(self) -> bool:
        if self._failed:
            return False
        try:
            import laya  # noqa: F401
            return True
        except Exception:
            return False

    def load(self) -> None:
        """Load the checkpoint, quietly.

        The upstream library prints a download progress bar and a calibration warning to
        stderr. Neither is actionable for someone running a CLI command, and both wreck the
        layout of a rendered table, so they are suppressed here rather than shown.
        """
        if self._agent is not None:
            return
        import os
        import warnings
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="laya.*")
        import laya
        if self.device and self.device != "auto":
            self._agent = laya.Agent(self.model_id, device=self.device)
        else:
            self._agent = laya.load(self.model_id)

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
