"""Detect and configure the Codex CLI via ~/.codex/config.toml.

Provider key shape (`model_provider` plus a `[model_providers.NAME]` table with
`name` / `base_url` / `env_key` / `wire_api`) verified against the official Codex
config reference at https://learn.chatgpt.com/docs/config-file/config-reference.
"""
from __future__ import annotations

import shutil
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

from ..config import home

CONFIG = Path.home() / ".codex" / "config.toml"

PROVIDER = "tokunseba"
ENV_KEY = "OPENAI_API_KEY"
WIRE_API = "responses"


def _backup_path() -> Path:
    return home() / "backups" / "codex-config.toml"


def _read(path: Path) -> dict[str, Any]:
    """Load the TOML config; a missing or corrupt file reads as {}."""
    try:
        return tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}


def status() -> tuple[bool, bool, str]:
    on_disk = CONFIG.exists()
    installed = on_disk or shutil.which("codex") is not None
    configured = _read(CONFIG).get("model_provider") == PROVIDER if on_disk else False
    if not installed:
        note = "not installed"
    elif configured:
        note = f"model_provider = {PROVIDER!r}"
    else:
        note = "model_provider not set to tokunseba"
    return installed, configured, note


def apply(base: str) -> str:
    """Route Codex through the proxy. `base` is the full .../openai/v1 URL."""
    data = _read(CONFIG)

    backup = _backup_path()
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not CONFIG.exists():
            # nothing of the user's to preserve; remember that so restore can undo cleanly
            backup.with_suffix(backup.suffix + ".absent").write_text("")
        if CONFIG.exists():
            shutil.copyfile(CONFIG, backup)

    data["model_provider"] = PROVIDER
    providers = data.get("model_providers")
    if not isinstance(providers, dict):
        providers = {}
    providers[PROVIDER] = {
        "name": PROVIDER,
        "base_url": base,
        "env_key": ENV_KEY,
        "wire_api": WIRE_API,
    }
    data["model_providers"] = providers

    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(tomli_w.dumps(data))
    return str(CONFIG)


def restore() -> bool:
    """Put the pre-apply config file back byte-for-byte."""
    backup = _backup_path()
    absent = backup.with_suffix(backup.suffix + ".absent")
    if absent.exists():
        # tokunseba created this file; removing it is the faithful restore
        CONFIG.unlink(missing_ok=True)
        absent.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)
        return True
    if not backup.exists():
        return False
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(backup, CONFIG)
    backup.unlink()
    return True
