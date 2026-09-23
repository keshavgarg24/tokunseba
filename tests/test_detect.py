"""Tests for tool detection, config writers, restore and doctor."""
import json
import shutil
import tomllib

import pytest

from tokunseba.detect import claude_code, codex, envfile, registry


@pytest.fixture
def settings(tmp_path, monkeypatch):
    path = tmp_path / "claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(claude_code, "SETTINGS", path)
    return path


@pytest.fixture
def codex_config(tmp_path, monkeypatch):
    path = tmp_path / "codex" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(codex, "CONFIG", path)
    return path


@pytest.fixture
def profile(tmp_path, monkeypatch):
    path = tmp_path / "zshrc"
    monkeypatch.setattr(envfile, "PROFILE_OVERRIDE", path)
    return path


@pytest.fixture
def no_claude_cli(monkeypatch):
    """No real `claude mcp ...` subprocess may run from the tests."""
    monkeypatch.setattr(shutil, "which", lambda name: None)


BASE = "http://127.0.0.1:7777/anthropic"
OPENAI_BASE = "http://127.0.0.1:7777/openai/v1"


# --- claude code ------------------------------------------------------------

def test_claude_code_apply_and_restore(home, tmp_path, monkeypatch):
    import json
    from tokunseba.detect import claude_code
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "opus", "env": {"FOO": "1"}}')
    monkeypatch.setattr(claude_code, "SETTINGS", settings)
    claude_code.apply("http://127.0.0.1:7777/anthropic", hooks=True)
    data = json.loads(settings.read_text())
    assert data["env"] == {"FOO": "1", "ANTHROPIC_BASE_URL": "http://127.0.0.1:7777/anthropic"}
    assert data["model"] == "opus"
    assert data["statusLine"]["command"] == "tokunseba statusline"
    assert "SessionStart" in data["hooks"]
    claude_code.restore()
    assert json.loads(settings.read_text()) == {"model": "opus", "env": {"FOO": "1"}}


def test_claude_code_restore_is_byte_for_byte(home, settings):
    original = '{\n    "model": "opus",\n  "env": {"FOO": "1"}\n}\n'
    settings.write_text(original)
    claude_code.apply(BASE)
    assert settings.read_text() != original
    assert claude_code.restore() is True
    assert settings.read_text() == original


def test_claude_code_apply_twice_is_idempotent(home, settings):
    settings.write_text('{"model": "opus"}')
    claude_code.apply(BASE)
    once = settings.read_text()
    claude_code.apply(BASE)
    assert settings.read_text() == once
    hooks = json.loads(once)["hooks"]
    assert len(hooks["SessionStart"]) == 1
    assert len(hooks["UserPromptSubmit"]) == 1


def test_claude_code_existing_statusline_not_overwritten(home, settings):
    settings.write_text('{"statusLine": {"type": "command", "command": "mine"}}')
    claude_code.apply(BASE)
    assert json.loads(settings.read_text())["statusLine"]["command"] == "mine"


def test_claude_code_existing_hook_entry_preserved(home, settings):
    mine = {"matcher": "*", "hooks": [{"type": "command", "command": "my-hook"}]}
    settings.write_text(json.dumps({"hooks": {"SessionStart": [mine]}}))
    claude_code.apply(BASE)
    entries = json.loads(settings.read_text())["hooks"]["SessionStart"]
    assert entries[0] == mine
    assert entries[1]["hooks"][0]["command"] == "tokunseba hook claude-code"


def test_claude_code_missing_and_corrupt_files(home, settings):
    assert not settings.exists()
    claude_code.apply(BASE)
    assert json.loads(settings.read_text())["env"]["ANTHROPIC_BASE_URL"] == BASE

    settings.write_text("{not json at all")
    claude_code.restore()  # drop the (absent-source) backup state
    claude_code.apply(BASE)
    assert json.loads(settings.read_text())["env"]["ANTHROPIC_BASE_URL"] == BASE


def test_claude_code_status(home, settings):
    assert claude_code.status() == (False, False, "not installed")
    settings.write_text('{"env": {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}}')
    installed, configured, _ = claude_code.status()
    assert (installed, configured) == (True, False)
    claude_code.apply(BASE)
    installed, configured, note = claude_code.status()
    assert (installed, configured) == (True, True)
    assert BASE in note


def test_claude_code_restore_without_backup_returns_false(home, settings):
    settings.write_text("{}")
    assert claude_code.restore() is False


# --- codex ------------------------------------------------------------------

def test_codex_apply_preserves_keys_and_round_trips(home, codex_config):
    codex_config.write_text('model = "gpt-5"\napproval_policy = "on-request"\n')
    original = codex_config.read_text()

    codex.apply(OPENAI_BASE)
    data = tomllib.loads(codex_config.read_text())
    assert data["model"] == "gpt-5"
    assert data["approval_policy"] == "on-request"
    assert data["model_provider"] == "tokunseba"
    assert data["model_providers"]["tokunseba"] == {
        "name": "tokunseba",
        "base_url": OPENAI_BASE,
        "env_key": "OPENAI_API_KEY",
        "wire_api": "responses",
    }

    assert codex.restore() is True
    assert codex_config.read_text() == original


def test_codex_apply_twice_is_idempotent(home, codex_config):
    codex_config.write_text('model = "gpt-5"\n')
    codex.apply(OPENAI_BASE)
    once = codex_config.read_text()
    codex.apply(OPENAI_BASE)
    assert codex_config.read_text() == once


def test_codex_preserves_other_providers(home, codex_config):
    codex_config.write_text(
        '[model_providers.other]\nname = "other"\nbase_url = "https://x.test/v1"\n'
    )
    codex.apply(OPENAI_BASE)
    providers = tomllib.loads(codex_config.read_text())["model_providers"]
    assert providers["other"]["base_url"] == "https://x.test/v1"
    assert providers["tokunseba"]["base_url"] == OPENAI_BASE


def test_codex_missing_and_corrupt_files(home, codex_config):
    assert not codex_config.exists()
    codex.apply(OPENAI_BASE)
    assert tomllib.loads(codex_config.read_text())["model_provider"] == "tokunseba"

    codex_config.write_text("this is ][ not toml")
    assert codex.status()[1] is False
    codex.restore()
    codex.apply(OPENAI_BASE)
    assert tomllib.loads(codex_config.read_text())["model_provider"] == "tokunseba"


def test_codex_status(home, codex_config, no_claude_cli):
    assert codex.status() == (False, False, "not installed")
    codex_config.write_text('model = "gpt-5"\n')
    assert codex.status()[:2] == (True, False)
    codex.apply(OPENAI_BASE)
    assert codex.status()[:2] == (True, True)


def test_codex_restore_without_backup_returns_false(home, codex_config):
    codex_config.write_text("")
    assert codex.restore() is False


# --- shell env --------------------------------------------------------------

def test_envfile_apply_writes_exports_and_block(home, profile):
    profile.write_text("export EDITOR=vim\n")
    path = envfile.apply(7777)
    assert path == str(home / "env.sh")

    body = (home / "env.sh").read_text()
    assert 'export ANTHROPIC_BASE_URL="http://127.0.0.1:7777/anthropic"' in body
    assert 'export OPENAI_BASE_URL="http://127.0.0.1:7777/openai/v1"' in body
    assert 'export OPENAI_API_BASE="http://127.0.0.1:7777/openai/v1"' in body
    assert 'export OLLAMA_HOST="http://127.0.0.1:7777/ollama"' in body

    text = profile.read_text()
    assert text.count(envfile.START) == 1
    assert text.count(envfile.END) == 1
    assert 'source "$HOME/.tokunseba/env.sh"' in text


def test_envfile_apply_twice_is_idempotent(home, profile):
    profile.write_text("export EDITOR=vim\n")
    envfile.apply(7777)
    once = profile.read_text()
    envfile.apply(7777)
    assert profile.read_text() == once
    assert profile.read_text().count(envfile.START) == 1


def test_envfile_apply_replaces_stale_block_in_place(home, profile):
    profile.write_text("before\n")
    envfile.apply(7777)
    text = profile.read_text().replace(envfile.SOURCE_LINE, "stale line")
    profile.write_text(text + "after\n")
    envfile.apply(7778)
    final = profile.read_text()
    assert final.count(envfile.START) == 1
    assert "stale line" not in final
    assert final.startswith("before\n")
    assert final.endswith("after\n")


def test_envfile_restore_is_byte_for_byte(home, profile):
    original = "export EDITOR=vim\nalias ll='ls -la'\n"
    profile.write_text(original)
    envfile.apply(7777)
    assert profile.read_text() != original
    assert (home / "env.sh").exists()

    assert envfile.restore() is True
    assert profile.read_text() == original
    assert not (home / "env.sh").exists()
    assert envfile.restore() is False


def test_envfile_handles_profile_without_trailing_newline(home, profile):
    original = "export EDITOR=vim"
    profile.write_text(original)
    envfile.apply(7777)
    envfile.restore()
    assert profile.read_text() == original


def test_envfile_creates_missing_profile(home, profile):
    assert not profile.exists()
    envfile.apply(7777)
    assert profile.exists()
    assert envfile.START in profile.read_text()


def test_envfile_status(home, profile):
    assert envfile.status()[:2] == (True, False)
    envfile.apply(7777)
    installed, configured, note = envfile.status()
    assert (installed, configured) == (True, True)
    assert str(profile) in note


def test_profile_path_follows_shell(monkeypatch):
    monkeypatch.setattr(envfile, "PROFILE_OVERRIDE", None)
    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert envfile.profile_path().name == ".zshrc"
    monkeypatch.setenv("SHELL", "/bin/bash")
    assert envfile.profile_path().name == ".bashrc"


# --- registry ---------------------------------------------------------------

def test_detect_all_covers_the_core_tools(home, settings, codex_config, profile):
    names = [t.name for t in registry.detect_all()]
    for expected in ("claude-code", "codex", "shell-env"):
        assert expected in names
    by_name = {t.name: t for t in registry.detect_all()}
    assert by_name["claude-code"].config_path == str(settings)
    assert by_name["codex"].config_path == str(codex_config)
    assert by_name["shell-env"].config_path == str(profile)
    assert by_name["gemini-cli"].note == (
        "no base-url setting in this version; use the shell env block"
    )
    assert all(isinstance(t, registry.ToolStatus) for t in registry.detect_all())


def test_detect_all_reflects_applied_config(home, settings, codex_config, profile,
                                            no_claude_cli):
    registry.apply_all(_cfg())
    by_name = {t.name: t for t in registry.detect_all()}
    assert by_name["claude-code"].configured is True
    assert by_name["codex"].configured is True
    assert by_name["shell-env"].configured is True


def _cfg():
    from tokunseba import config
    return config.load()


def test_apply_all_and_restore_all(home, settings, codex_config, profile, no_claude_cli):
    settings.write_text('{"model": "opus"}')
    profile.write_text("export EDITOR=vim\n")
    original_profile = profile.read_text()

    paths = registry.apply_all(_cfg())
    assert str(settings) in paths
    assert str(codex_config) in paths
    assert str(home / "env.sh") in paths
    assert json.loads(settings.read_text())["env"]["ANTHROPIC_BASE_URL"] == BASE
    assert tomllib.loads(codex_config.read_text())["model_providers"]["tokunseba"][
        "base_url"
    ] == OPENAI_BASE

    messages = registry.restore_all()
    assert any("gui-apps" in m for m in messages)
    assert json.loads(settings.read_text()) == {"model": "opus"}
    assert profile.read_text() == original_profile


def test_apply_all_twice_is_idempotent(home, settings, codex_config, profile, no_claude_cli):
    settings.write_text('{"model": "opus"}')
    profile.write_text("export EDITOR=vim\n")
    registry.apply_all(_cfg())
    snapshot = (settings.read_text(), codex_config.read_text(), profile.read_text())
    registry.apply_all(_cfg())
    assert (settings.read_text(), codex_config.read_text(), profile.read_text()) == snapshot


def test_doctor_returns_checks_and_never_raises(home, settings, codex_config, profile,
                                                no_claude_cli):
    from tokunseba import config
    from tokunseba.ledger import Ledger

    cfg = config.load()
    ledger = Ledger(home / "l.sqlite")
    try:
        checks = registry.doctor(cfg, ledger)
    finally:
        ledger.close()

    assert checks and all(isinstance(c, registry.Check) for c in checks)
    names = [c.name for c in checks]
    assert "proxy reachable" in names
    assert "tool: claude-code" in names
    assert "laya installed" in names
    assert "laya weights cached" in names
    assert "mcp installed" in names
    assert "cache drift (24h)" in names
    assert "budget" in names
    drift = next(c for c in checks if c.name == "cache drift (24h)")
    assert drift.ok is True
    budget = next(c for c in checks if c.name == "budget")
    assert budget.ok is True
    assert budget.detail == "no daily token ceiling set"
    assert all(c.detail for c in checks)


def test_doctor_survives_a_broken_ledger(home, settings, codex_config, profile, no_claude_cli):
    from tokunseba import config

    class Broken:
        def stats(self, since):
            raise RuntimeError("ledger is gone")

    checks = registry.doctor(config.load(), Broken())
    drift = next(c for c in checks if c.name == "cache drift (24h)")
    assert drift.ok is True


def test_restore_removes_a_file_tokunseba_created(home, tmp_path, monkeypatch):
    """If the user had no settings file, the faithful restore is to remove ours."""
    from tokunseba.detect import claude_code
    settings = tmp_path / "fresh" / "settings.json"
    monkeypatch.setattr(claude_code, "SETTINGS", settings)
    claude_code.apply("http://127.0.0.1:7777/anthropic")
    assert settings.exists()
    assert claude_code.restore() is True
    assert not settings.exists()


def test_restore_removes_a_codex_file_tokunseba_created(home, tmp_path, monkeypatch):
    from tokunseba.detect import codex
    cfg = tmp_path / "fresh" / "config.toml"
    monkeypatch.setattr(codex, "CONFIG", cfg)
    codex.apply("http://127.0.0.1:7777/openai/v1")
    assert cfg.exists()
    assert codex.restore() is True
    assert not cfg.exists()


def test_existing_file_is_still_restored_not_deleted(home, tmp_path, monkeypatch):
    from tokunseba.detect import claude_code
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "opus"}')
    monkeypatch.setattr(claude_code, "SETTINGS", settings)
    claude_code.apply("http://127.0.0.1:7777/anthropic")
    claude_code.restore()
    assert settings.exists() and settings.read_text() == '{"model": "opus"}'


def test_apply_all_accepts_the_hooks_flag(home, tmp_path, monkeypatch):
    import json

    from tokunseba import config
    from tokunseba.detect import claude_code, codex, envfile, registry
    monkeypatch.setattr(registry.shutil, "which", lambda _n: None)
    monkeypatch.setattr(claude_code, "SETTINGS", tmp_path / "s.json")
    monkeypatch.setattr(codex, "CONFIG", tmp_path / "c.toml")
    monkeypatch.setattr(envfile, "PROFILE_OVERRIDE", tmp_path / "profile")
    registry.apply_all(config.load(), hooks=False)
    assert "hooks" not in json.loads((tmp_path / "s.json").read_text())
