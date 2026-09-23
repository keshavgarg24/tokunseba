"""Configuration: dataclasses, load, save. Everything local, no accounts, no telemetry."""
from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomli_w


def home() -> Path:
    p = Path(os.environ.get("TOKUNSEBA_HOME", Path.home() / ".tokunseba"))
    p.mkdir(parents=True, exist_ok=True)
    try:
        p.chmod(0o700)
    except OSError:
        pass
    return p


@dataclass
class Upstream:
    base_url: str
    kind: str  # anthropic | openai | gemini | ollama


@dataclass
class Tier3Config:
    effort_routing: bool = False
    model_routing: bool = False
    local_routing: bool = False
    redact_secrets: bool = False
    annotate_injections: bool = False
    model_map: dict[str, str] = field(default_factory=dict)
    local_model: str = ""
    # Prompt-driven routing. Each entry states conditions on the judge's signals and a
    # target, and the first one that matches wins. Kept as plain dicts so the file stays
    # readable and a hand-edited rule survives a round trip.
    #   [[tier3.rules]]
    #   domain = "chitchat"      # "" matches any
    #   max_difficulty = 1.0     # -1 matches any
    #   needs_tools = false      # omit to match any
    #   upstream = "ollama"      # "" keeps the upstream the request arrived for
    #   model = "llama3.1"       # "" keeps the model the client asked for
    rules: list[dict] = field(default_factory=list)


@dataclass
class JudgeConfig:
    # The local judge is an opt-in extra. Its weights are an ~800 MB download and the loaded
    # model holds roughly 2.2 GB of RAM for as long as the proxy runs, which is real weight on
    # a small laptop. Nothing in tiers 0-2 needs it, so it stays off until asked for by name
    # with `tokunseba judge enable`, and `tokunseba judge disable` gives the memory back.
    # While this is False the laya backend is never constructed, so torch is never imported.
    enabled: bool = False
    backends: list[str] = field(default_factory=lambda: ["rules", "laya"])
    laya_model: str = "convaiinnovations/laya"
    laya_device: str = "auto"
    gate_threshold: float = 0.80
    timeout: float = 5.0
    # The local judge takes on the order of a second per call on a laptop, so by default it
    # runs after the response has been dispatched and only feeds the ledger. Turn this on to
    # let it gate tier 3 decisions, at the cost of that latency on the first turn.
    inline: bool = False
    # Pay the load cost at startup instead of inside somebody's first request. Only ever acts
    # when the judge is enabled and the weights are already on disk; it never downloads.
    warm: bool = False


@dataclass
class Thresholds:
    truncate_lines: int = 300
    truncate_tokens: int = 6000
    cache_min_tokens: int = 1024
    local_truncate_tokens: int = 1500


@dataclass
class Retention:
    """How long to keep history. Reports can only reach as far back as this allows."""
    days: int = 90          # 0 keeps everything forever
    auto_prune: bool = True  # prune once a day when the proxy starts
    keep_bodies_days: int = 14  # request bodies are the bulkiest part; expire them sooner


@dataclass
class Budget:
    # A ceiling on tokens read and written in a day, counted from the ledger. Tokens are the
    # one unit every kind of access has in common, so this means the same thing everywhere.
    # 0 is off.
    daily_tokens: int = 0
    hard_stop: bool = False


@dataclass
class Failover:
    enabled: bool = False
    routes: dict[str, dict[str, str]] = field(default_factory=dict)


DEFAULT_UPSTREAMS: dict[str, Upstream] = {
    "anthropic": Upstream("https://api.anthropic.com", "anthropic"),
    "openai": Upstream("https://api.openai.com", "openai"),
    "gemini": Upstream("https://generativelanguage.googleapis.com", "gemini"),
    "ollama": Upstream("http://127.0.0.1:11434", "ollama"),
}


@dataclass
class Config:
    port: int = 7777
    store_bodies: bool = True
    cache_ttl: str = ""
    lossless: bool = True
    reach_preserving: bool = True
    tier3: bool = False
    tier3_opts: Tier3Config = field(default_factory=Tier3Config)
    judge: JudgeConfig = field(default_factory=JudgeConfig)
    thresholds: Thresholds = field(default_factory=Thresholds)
    budget: Budget = field(default_factory=Budget)
    retention: Retention = field(default_factory=Retention)
    failover: Failover = field(default_factory=Failover)
    upstreams: dict[str, Upstream] = field(default_factory=lambda: dict(DEFAULT_UPSTREAMS))

    def base(self, prefix: str = "") -> str:
        root = f"http://127.0.0.1:{self.port}"
        return f"{root}/{prefix}" if prefix else root


def default_path() -> Path:
    return home() / "config.toml"


def _only_known(cls, raw: dict) -> dict:
    return {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}


def load(path: Path | None = None) -> Config:
    path = path or default_path()
    if not path.exists():
        return Config()
    raw = tomllib.loads(path.read_text())
    cfg = Config()
    proxy = raw.get("proxy", {})
    cfg.port = int(proxy.get("port", cfg.port))
    cfg.store_bodies = bool(proxy.get("store_bodies", cfg.store_bodies))
    cfg.cache_ttl = str(proxy.get("cache_ttl", cfg.cache_ttl))
    tiers = raw.get("tiers", {})
    cfg.lossless = bool(tiers.get("lossless", True))
    cfg.reach_preserving = bool(tiers.get("reach_preserving", True))
    cfg.tier3 = bool(tiers.get("tier3", False))
    cfg.tier3_opts = Tier3Config(**_only_known(Tier3Config, raw.get("tier3", {})))
    cfg.judge = JudgeConfig(**_only_known(JudgeConfig, raw.get("judge", {})))
    cfg.thresholds = Thresholds(**_only_known(Thresholds, raw.get("thresholds", {})))
    cfg.budget = Budget(**_only_known(Budget, raw.get("budget", {})))
    cfg.retention = Retention(**_only_known(Retention, raw.get("retention", {})))
    fo = raw.get("failover", {})
    cfg.failover = Failover(enabled=bool(fo.get("enabled", False)), routes=fo.get("routes", {}) or {})
    for name, u in (raw.get("upstreams", {}) or {}).items():
        if isinstance(u, dict) and "base_url" in u:
            cfg.upstreams[name] = Upstream(base_url=u["base_url"], kind=u.get("kind", "openai"))
    return cfg


def save(cfg: Config, path: Path | None = None) -> Path:
    path = path or default_path()
    doc = {
        "proxy": {
            "port": cfg.port,
            "store_bodies": cfg.store_bodies,
            "cache_ttl": cfg.cache_ttl,
        },
        "tiers": {
            "lossless": cfg.lossless,
            "reach_preserving": cfg.reach_preserving,
            "tier3": cfg.tier3,
        },
        "tier3": asdict(cfg.tier3_opts),
        "judge": asdict(cfg.judge),
        "thresholds": asdict(cfg.thresholds),
        "budget": asdict(cfg.budget),
        "retention": asdict(cfg.retention),
        "failover": asdict(cfg.failover),
        "upstreams": {k: asdict(v) for k, v in cfg.upstreams.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(doc))
    return path
