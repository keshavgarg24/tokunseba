from .base import Answer, Judge, JudgeChain, gate
from .laya_judge import LayaJudge
from .questions import guard as guard_questions
from .questions import router as router_questions
from .rules import RulesJudge

# The chain answers a question with the first backend that will take it, so order is a
# policy, not a detail. The rules backend can answer every router question, which is what
# makes prompt-aware routing work with nothing installed; but when somebody has enabled the
# local model and is paying 2.2 GB for it, the model should get first refusal and the rules
# should be what catches whatever it declines or times out on.
_ORDER = {"laya": 0, "rules": 1}


def build_chain(cfg, ledger=None) -> JudgeChain:
    """Assemble the judge backends this config asks for.

    The laya backend is left out entirely unless the user enabled it. That matters beyond
    tidiness: merely asking a LayaJudge whether it is available imports torch, which costs
    about 65 MB and a noticeable pause, so a disabled judge must never be constructed.
    """
    made = []
    for name in cfg.judge.backends:
        if name == "rules":
            made.append(RulesJudge())
        elif name == "laya" and cfg.judge.enabled:
            made.append(LayaJudge(cfg.judge.laya_model, cfg.judge.laya_device))
    made.sort(key=lambda b: _ORDER.get(b.name, 99))
    return JudgeChain(made, threshold=cfg.judge.gate_threshold, ledger=ledger,
                      timeout=cfg.judge.timeout)


__all__ = ["Answer", "Judge", "JudgeChain", "LayaJudge", "RulesJudge", "build_chain", "gate",
           "guard_questions", "router_questions"]
