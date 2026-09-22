"""Price table and cost maths. Local models cost nothing."""
from __future__ import annotations

from dataclasses import dataclass

from .protocols.base import Usage


@dataclass
class Price:
    input: float
    output: float
    cache_read: float
    cache_write: float  # USD per million tokens


# Anthropic first-party list prices. Cache read is 0.1x input and cache write 1.25x input
# unless the model publishes a different figure. Update when prices change.
TABLE: dict[str, Price] = {
    "anthropic/claude-fable-5-1": Price(10.0, 50.0, 0.25, 12.5),
    "anthropic/claude-fable-5": Price(10.0, 50.0, 1.0, 12.5),
    "anthropic/claude-opus-5": Price(5.0, 25.0, 0.5, 6.25),
    "anthropic/claude-opus-4-8": Price(5.0, 25.0, 0.5, 6.25),
    "anthropic/claude-opus-4-7": Price(5.0, 25.0, 0.5, 6.25),
    "anthropic/claude-opus-4-6": Price(5.0, 25.0, 0.5, 6.25),
    "anthropic/claude-sonnet-5": Price(2.0, 10.0, 0.2, 2.5),
    "anthropic/claude-sonnet-4-6": Price(3.0, 15.0, 0.3, 3.75),
    "anthropic/claude-haiku-4-5": Price(1.0, 5.0, 0.1, 1.25),
    "ollama/*": Price(0.0, 0.0, 0.0, 0.0),
}



def price_for(provider: str, model: str, overrides: dict[str, dict[str, float]]) -> Price | None:
    key = f"{provider}/{model}"
    if key in overrides:
        o = overrides[key]
        return Price(
            o["input"],
            o["output"],
            o.get("cache_read", o["input"] * 0.1),
            o.get("cache_write", o["input"] * 1.25),
        )
    if key in TABLE:
        return TABLE[key]
    for k, p in TABLE.items():
        if k.endswith("/*") and key.startswith(k[:-1]):
            return p
    base = model.split("-2")[0]
    return TABLE.get(f"{provider}/{base}")


def cost(u: Usage, p: Price) -> float:
    return (
        u.input_tokens * p.input
        + u.cache_read * p.cache_read
        + u.cache_write * p.cache_write
        + u.output_tokens * p.output
    ) / 1e6


def counterfactual(u: Usage, p: Price, saved_input_tokens: int, injected_cache_read: int) -> float:
    """What this request would have cost with tokunseba switched off."""
    return (
        cost(u, p)
        + saved_input_tokens * p.input / 1e6
        + injected_cache_read * (p.input - p.cache_read) / 1e6
    )
