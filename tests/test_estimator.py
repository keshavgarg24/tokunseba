from tokunseba.ledger import Ledger
from tokunseba.tokens.estimator import Estimator


def test_ratio_learning(home):
    est = Estimator(Ledger(home / "l.sqlite"))
    assert est.count("a" * 1000, "anthropic", "claude-opus-5") == 280
    est.learn("anthropic", "claude-opus-5", chars=1000, tokens=400)
    assert est.count("a" * 1000, "anthropic", "claude-opus-5") == 304


def test_learn_ignores_small_and_absurd_samples(home):
    est = Estimator(Ledger(home / "l.sqlite"))
    est.learn("anthropic", "m", chars=10, tokens=500)
    est.learn("anthropic", "m", chars=5000, tokens=100)
    est.learn("anthropic", "m", chars=1000, tokens=9000)
    assert est.ratio("anthropic", "m") == 0.28


def test_ratio_persists_via_ledger(home):
    led = Ledger(home / "l.sqlite")
    Estimator(led).learn("anthropic", "m", chars=2000, tokens=800)
    assert abs(Estimator(led).ratio("anthropic", "m") - 0.304) < 1e-9


def test_openai_uses_real_tokenizer(home):
    est = Estimator(Ledger(home / "l.sqlite"))
    n = est.count("hello world, this is a test of the tokenizer", "openai", "gpt-4o")
    assert 5 < n < 20


def test_empty_and_zero(home):
    est = Estimator(Ledger(home / "l.sqlite"))
    assert est.count("", "anthropic", "m") == 0


def test_works_without_ledger():
    assert Estimator(None).count("a" * 100, "anthropic", "m") == 28


def test_never_reaches_the_network_for_a_tokenizer(home, monkeypatch):
    """tokunseba must work offline. A tokenizer download on every local request would
    also add seconds of latency for a repo that is gated and always fails."""
    import tokenizers
    from tokunseba.ledger import Ledger

    def explode(*a, **k):
        raise AssertionError("from_pretrained would hit the network")
    monkeypatch.setattr(tokenizers.Tokenizer, "from_pretrained", explode)
    est = Estimator(Ledger(home / "l.sqlite"))
    n = est.count("some local model prompt text here", "ollama", "llama3.1:8b")
    assert n > 0


def test_uncached_tokenizer_falls_back_to_the_ratio(home):
    from tokunseba.ledger import Ledger
    est = Estimator(Ledger(home / "l.sqlite"))
    assert est._load_cached("definitely/not-a-real-repo-xyz") is False
    assert est.count("a" * 1000, "ollama", "llama3.1") == 280


def test_local_model_counting_is_fast(home):
    import time
    from tokunseba.ledger import Ledger
    est = Estimator(Ledger(home / "l.sqlite"))
    t0 = time.monotonic()
    for _ in range(50):
        est.count("word " * 200, "ollama", "llama3.1")
    assert (time.monotonic() - t0) < 0.5
