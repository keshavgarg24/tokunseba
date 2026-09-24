from tokunseba import config


def test_defaults_and_roundtrip(home):
    cfg = config.load()
    assert cfg.port == 7777
    assert cfg.lossless and cfg.reach_preserving and not cfg.tier3
    assert cfg.judge.backends == ["rules", "laya"]
    assert set(cfg.upstreams) >= {"anthropic", "openai", "gemini", "ollama"}
    cfg.port = 7800
    cfg.upstreams["openrouter"] = config.Upstream(base_url="https://openrouter.ai/api", kind="openai")
    path = config.save(cfg)
    again = config.load(path)
    assert again.port == 7800
    assert again.upstreams["openrouter"].kind == "openai"


def test_nested_sections_roundtrip(home):
    cfg = config.load()
    cfg.tier3 = True
    cfg.tier3_opts.effort_routing = True
    cfg.tier3_opts.model_map = {"claude-opus-5": "claude-sonnet-5"}
    cfg.judge.gate_threshold = 0.9
    cfg.thresholds.truncate_tokens = 1234
    cfg.budget.daily_tokens = 500_000
    cfg.failover.enabled = True
    cfg.failover.routes = {"claude-opus-5": {"upstream": "x", "api_key_env": "K", "header": "x-api-key"}}
    config.save(cfg)
    again = config.load()
    assert again.tier3 and again.tier3_opts.effort_routing
    assert again.tier3_opts.model_map["claude-opus-5"] == "claude-sonnet-5"
    assert again.judge.gate_threshold == 0.9
    assert again.thresholds.truncate_tokens == 1234
    assert again.budget.daily_tokens == 500_000
    assert again.failover.routes["claude-opus-5"]["header"] == "x-api-key"


def test_unknown_keys_ignored(home):
    p = config.default_path()
    p.write_text('[judge]\nbackends = ["rules"]\nbogus = 1\n[proxy]\nport = 9000\n')
    cfg = config.load(p)
    assert cfg.port == 9000 and cfg.judge.backends == ["rules"]


def test_base_url_helper(home):
    cfg = config.load()
    assert cfg.base("anthropic") == "http://127.0.0.1:7777/anthropic"
    assert cfg.base() == "http://127.0.0.1:7777"


def test_home_is_private(home):
    assert config.home().exists()


def test_the_package_version_and_the_build_metadata_do_not_drift():
    """Two files carry the version. The release refuses a tag that does not match pyproject,
    so if `__version__` were the one left behind, `tokunseba --version` would quietly report
    the previous release for the life of the next one."""
    import tomllib
    from pathlib import Path

    from tokunseba import __version__
    root = Path(__file__).resolve().parents[1]
    declared = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    assert __version__ == declared
