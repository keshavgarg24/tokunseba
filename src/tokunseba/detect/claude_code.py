"""Detect and configure Claude Code via ~/.claude/settings.json."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ..config import home

SETTINGS = Path.home() / ".claude" / "settings.json"

HOOK_COMMAND = "tokunseba hook claude-code"
HOOK_EVENTS = ("SessionStart", "UserPromptSubmit")
STATUSLINE_COMMAND = "tokunseba statusline"
LOCAL_PREFIX = "http://127.0.0.1:"


def _backup_path() -> Path:
    return home() / "backups" / "claude-settings.json"


def _read(path: Path) -> dict[str, Any]:
    """Load the settings JSON; a missing or corrupt file reads as {}."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def status() -> tuple[bool, bool, str]:
    installed = SETTINGS.exists()
    env = _read(SETTINGS).get("env") if installed else None
    url = env.get("ANTHROPIC_BASE_URL", "") if isinstance(env, dict) else ""
    configured = isinstance(url, str) and url.startswith(LOCAL_PREFIX)
    if not installed:
        note = "not installed"
    elif configured:
        note = f"ANTHROPIC_BASE_URL -> {url}"
    else:
        note = "ANTHROPIC_BASE_URL does not point at the local proxy"
    return installed, configured, note


def _has_command(entries: list[Any], command: str) -> bool:
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        inner = entry.get("hooks")
        if not isinstance(inner, list):
            continue
        for hook in inner:
            if isinstance(hook, dict) and hook.get("command") == command:
                return True
    return False


def apply(base: str, hooks: bool = True, statusline: bool = True) -> str:
    """Point Claude Code at the proxy. Idempotent; backs up once."""
    data = _read(SETTINGS)

    backup = _backup_path()
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not SETTINGS.exists():
            # nothing of the user's to preserve; remember that so restore can undo cleanly
            backup.with_suffix(backup.suffix + ".absent").write_text("")
        if SETTINGS.exists():
            shutil.copyfile(SETTINGS, backup)

    env = data.get("env")
    if not isinstance(env, dict):
        env = {}
    env["ANTHROPIC_BASE_URL"] = base
    data["env"] = env

    if statusline and "statusLine" not in data:
        data["statusLine"] = {"type": "command", "command": STATUSLINE_COMMAND}

    if hooks:
        table = data.get("hooks")
        if not isinstance(table, dict):
            table = {}
        for event in HOOK_EVENTS:
            entries = table.get(event)
            if not isinstance(entries, list):
                entries = []
            if not _has_command(entries, HOOK_COMMAND):
                entries.append({"hooks": [{"type": "command", "command": HOOK_COMMAND}]})
            table[event] = entries
        data["hooks"] = table

    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(data, indent=2))
    return str(SETTINGS)


def restore() -> bool:
    """Put the pre-apply settings file back byte-for-byte."""
    backup = _backup_path()
    absent = backup.with_suffix(backup.suffix + ".absent")
    if absent.exists():
        # tokunseba created this file; removing it is the faithful restore
        SETTINGS.unlink(missing_ok=True)
        absent.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)
        return True
    if not backup.exists():
        return False
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(backup, SETTINGS)
    backup.unlink()
    return True
