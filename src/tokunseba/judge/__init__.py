from .base import Answer, Judge, JudgeChain, gate
from .laya_judge import LayaJudge
from .rules import RulesJudge


def build_chain(cfg, ledger=None) -> JudgeChain:
    made = []
    for name in cfg.judge.backends:
        if name == "rules":
            made.append(RulesJudge())
        elif name == "laya":
            made.append(LayaJudge(cfg.judge.laya_model, cfg.judge.laya_device))
    return JudgeChain(made, threshold=cfg.judge.gate_threshold, ledger=ledger, timeout=cfg.judge.timeout)


__all__ = ["Answer", "Judge", "JudgeChain", "LayaJudge", "RulesJudge", "build_chain", "gate"]
