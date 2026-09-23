import pytest


from tokunseba.judge.base import Answer, JudgeChain, gate
from tokunseba.judge.laya_judge import _truncate
from tokunseba.judge.rules import RulesJudge


class Stub:
    def __init__(self, name, answers, raises=False, avail=True):
        self.name, self._a, self._raises, self._avail = name, answers, raises, avail
        self.calls = []

    def available(self):
        return self._avail

    def ask(self, state, questions):
        self.calls.append(dict(questions))
        if self._raises:
            raise RuntimeError("boom")
        return {k: v for k, v in self._a.items() if k in questions}


def test_gate_abstains_below_threshold():
    assert gate(Answer("noul", 0.9, 0.5), 0.8) is None
    assert gate(Answer("noul", 0.9, 0.95), 0.8) is True
    assert gate(Answer("noul", 0.1, 0.95), 0.8) is False
    assert gate(None, 0.8) is None


async def test_chain_first_backend_wins_and_second_fills_gaps():
    a = Stub("a", {"x": Answer("noul", 1.0, 0.99)})
    b = Stub("b", {"x": Answer("noul", 0.0, 0.99), "y": Answer("noul", 1.0, 0.99)})
    chain = JudgeChain([a, b], 0.8)
    out = await chain.ask("s", {"x": {}, "y": {}})
    assert out["x"].value == 1.0 and out["y"].value == 1.0
    assert b.calls == [{"y": {}}]


async def test_failing_backend_is_skipped_not_fatal(home):
    from tokunseba.ledger import Ledger
    led = Ledger(home / "l.sqlite")
    chain = JudgeChain([Stub("bad", {}, raises=True), Stub("good", {"x": Answer("noul", 1.0, 0.99)})],
                       0.8, ledger=led)
    out = await chain.ask("s", {"x": {}})
    assert out["x"].value == 1.0
    assert led.stats(0)["events"]["judge_error"] == 1


async def test_unavailable_backend_skipped():
    chain = JudgeChain([Stub("off", {"x": Answer("noul", 1.0, 0.99)}, avail=False)], 0.8)
    assert await chain.ask("s", {"x": {}}) == {}


async def test_decide_and_value():
    chain = JudgeChain([], 0.8)
    ans = {"n": Answer("noul", 0.9, 0.99), "c": Answer("choice", "code", 0.95),
           "low": Answer("noul", 0.9, 0.1)}
    assert chain.decide(ans, "n", True) is True
    assert chain.decide(ans, "n", False) is False
    assert chain.decide(ans, "low") is None
    assert chain.decide(ans, "missing") is None
    assert chain.value(ans, "c") == "code"
    assert chain.value(ans, "low") is None


def test_rules_judge_detects_output_type():
    out = RulesJudge().ask("=== 2 failed, 3 passed in 1.0s ===\nFAILED tests/a.py::b\ncollected 5 items",
                           {"output_type": {}})
    assert out["output_type"].value == "pytest"


def test_rules_judge_abstains_on_noise():
    assert RulesJudge().ask("hello there", {"output_type": {}}) == {}


def test_rules_judge_ignores_unknown_questions():
    assert RulesJudge().ask("x", {"sentiment": {}, "is_haiku": {}}) == {}


def test_laya_state_truncation():
    s = _truncate({"request": "x" * 5000, "other": "y" * 5000})
    assert all(len(v) <= 700 for v in s.values())
    assert _truncate("z" * 5000).endswith("[...]")
    assert _truncate("short") == "short"


def test_laya_unavailable_is_graceful():
    from tokunseba.judge.laya_judge import LayaJudge
    j = LayaJudge()
    assert isinstance(j.available(), bool)


def test_laya_load_suppresses_library_noise(monkeypatch):
    """A progress bar and a calibration warning would wreck a rendered table.

    The environment is set before the library is imported, so this asserts it without
    paying the cost of actually loading an 808 MB checkpoint.
    """
    import os
    import sys
    from tokunseba.judge.laya_judge import LayaJudge
    monkeypatch.delenv("HF_HUB_DISABLE_PROGRESS_BARS", raising=False)
    monkeypatch.delenv("TRANSFORMERS_VERBOSITY", raising=False)
    monkeypatch.setitem(sys.modules, "laya", None)   # makes `import laya` raise, fast
    with pytest.raises(ImportError):
        LayaJudge().load()
    assert os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS") == "1"
    assert os.environ.get("TRANSFORMERS_VERBOSITY") == "error"
