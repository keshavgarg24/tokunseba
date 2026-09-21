from tokunseba.pricing import counterfactual, cost, price_for
from tokunseba.protocols.base import Usage


def test_known_anthropic_price():
    p = price_for("anthropic", "claude-opus-5", {})
    assert p.input == 5.0 and p.output == 25.0 and p.cache_read == 0.5 and p.cache_write == 6.25


def test_cost_and_counterfactual():
    p = price_for("anthropic", "claude-opus-5", {})
    u = Usage(input_tokens=1000, cache_read=10000, cache_write=0, output_tokens=100)
    c = cost(u, p)
    assert round(c, 6) == round(1000 * 5 / 1e6 + 10000 * 0.5 / 1e6 + 100 * 25 / 1e6, 6)
    cf = counterfactual(u, p, saved_input_tokens=2000, injected_cache_read=10000)
    assert cf > c


def test_override_and_unknown():
    assert price_for("openai", "mystery-model", {}) is None
    p = price_for("openai", "mystery-model", {"openai/mystery-model": {"input": 1, "output": 2}})
    assert p.cache_read == 0.1 and p.cache_write == 1.25


def test_ollama_is_free():
    p = price_for("ollama", "llama3.1:8b", {})
    assert p.input == 0.0 and cost(Usage(9999, 9999, 9999, 9999), p) == 0.0


def test_date_suffix_falls_back_to_base():
    assert price_for("anthropic", "claude-opus-5-20260401", {}).input == 5.0


def test_usage_total_input():
    assert Usage(1, 2, 3, 4).total_input == 6
