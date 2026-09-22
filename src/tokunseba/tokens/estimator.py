"""Token counting. Exact where a tokenizer exists, learned from real usage where it does not."""
from __future__ import annotations

import threading

DEFAULT_RATIO = 0.28  # tokens per character, refined from observed usage
TOKENIZER_MAP = {
    "llama": "meta-llama/Llama-3.1-8B",
    "qwen": "Qwen/Qwen3-8B",
    "mistral": "mistralai/Mistral-7B-v0.3",
}
_ALPHA = 0.2


class Estimator:
    def __init__(self, ledger=None):
        self.ledger = ledger
        self._lock = threading.Lock()
        self._ratios: dict[str, float] = {}
        self._tiktoken = None
        self._hf: dict[str, object] = {}

    # --- ratios ---
    def _ratio_key(self, provider: str, model: str) -> str:
        return f"ratio/{provider}/{model}"

    def ratio(self, provider: str, model: str) -> float:
        key = self._ratio_key(provider, model)
        if key in self._ratios:
            return self._ratios[key]
        val = DEFAULT_RATIO
        if self.ledger is not None:
            try:
                val = float(self.ledger.kv_get(key, DEFAULT_RATIO))
            except (TypeError, ValueError):
                val = DEFAULT_RATIO
        self._ratios[key] = val
        return val

    def learn(self, provider: str, model: str, chars: int, tokens: int) -> None:
        if chars <= 800 or tokens <= 200:
            return
        observed = tokens / chars
        if not (0.05 <= observed <= 2.0):
            return
        key = self._ratio_key(provider, model)
        with self._lock:
            new = (1 - _ALPHA) * self.ratio(provider, model) + _ALPHA * observed
            self._ratios[key] = new
            if self.ledger is not None:
                self.ledger.kv_set(key, new)

    # --- counting ---
    def _tik(self):
        if self._tiktoken is None:
            import tiktoken
            self._tiktoken = tiktoken.get_encoding("o200k_base")
        return self._tiktoken

    def _hf_for(self, model: str):
        """An exact tokenizer, but only if it is already on disk.

        tokunseba must work offline and cost nothing, so it never downloads a tokenizer.
        Several of these repos are gated anyway, and reaching for the network on every
        local-model request added seconds of latency for a result that always failed.
        When nothing is cached the learned character ratio is used instead, which is
        accurate enough for deciding what to compress.
        """
        low = model.lower()
        for prefix, repo in TOKENIZER_MAP.items():
            if prefix not in low:
                continue
            if repo not in self._hf:
                self._hf[repo] = self._load_cached(repo)
            tok = self._hf[repo]
            return tok if tok is not False else None
        return None

    @staticmethod
    def _load_cached(repo: str):
        try:
            from huggingface_hub import try_to_load_from_cache
        except ImportError:
            return False
        path = None
        for filename in ("tokenizer.json", "tokenizer_config.json"):
            hit = try_to_load_from_cache(repo, filename)
            if isinstance(hit, str):
                path = hit if filename == "tokenizer.json" else path
        if not path:
            return False
        try:
            from tokenizers import Tokenizer
            return Tokenizer.from_file(path)
        except Exception:
            return False

    def count(self, text: str, provider: str, model: str) -> int:
        if not text:
            return 0
        if provider == "openai":
            try:
                return len(self._tik().encode(text, disallowed_special=()))
            except Exception:
                pass
        elif provider in ("ollama", "custom"):
            tok = self._hf_for(model)
            if tok is not None:
                try:
                    return len(tok.encode(text).ids)
                except Exception:
                    pass
        return int(len(text) * self.ratio(provider, model))
