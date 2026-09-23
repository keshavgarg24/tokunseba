"""Registry of supported AI coding tools: detect, apply, restore, doctor."""
from __future__ import annotations

import importlib.util
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import claude_code, codex, envfile, guiapps

SHELL_NOTE = "picks up the shell env block from ~/.tokunseba/env.sh"
MCP_NAME = "tokunseba"


@dataclass
class ToolStatus:
    name: str
    installed: bool
    configured: bool
    config_path: str
    note: str = ""


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _run(cmd: list[str]) -> tuple[bool, str]:
    """Run a command, never raising. Returns (ok, stdout)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False, ""
    return proc.returncode == 0, proc.stdout or ""


def _continue_config() -> Path | None:
    for name in ("config.yaml", "config.json"):
        path = Path.home() / ".continue" / name
        if path.exists():
            return path
    return None


def cfg_port() -> int:
    """The configured port, without importing config at module import time."""
    from ..config import load
    try:
        return load().port
    except Exception:  # noqa: BLE001 - a broken config must not break detection
        return 7777


def detect_all() -> list[ToolStatus]:
    out: list[ToolStatus] = []

    installed, configured, note = claude_code.status()
    out.append(ToolStatus("claude-code", installed, configured, str(claude_code.SETTINGS), note))

    installed, configured, note = codex.status()
    out.append(ToolStatus("codex", installed, configured, str(codex.CONFIG), note))

    installed, configured, note = envfile.status()
    out.append(ToolStatus("shell-env", installed, configured, str(envfile.profile_path()), note))

    # Separate from shell-env on purpose: a terminal and a Dock-launched application get
    # their environment from two different places, and being correct in one says nothing
    # about the other.
    installed, configured, note = guiapps.status(cfg_port())
    out.append(ToolStatus("gui-apps", installed, configured, note, note))

    aider = shutil.which("aider")
    out.append(ToolStatus("aider", aider is not None, False, aider or "", SHELL_NOTE))

    gemini = shutil.which("gemini")
    out.append(ToolStatus(
        "gemini-cli", gemini is not None, False, gemini or "",
        "no base-url setting in this version; use the shell env block",
    ))

    cont = _continue_config()
    out.append(ToolStatus("continue", cont is not None, False, str(cont or ""), SHELL_NOTE))

    opencode = shutil.which("opencode")
    out.append(ToolStatus("opencode", opencode is not None, False, opencode or "", SHELL_NOTE))

    ollama = shutil.which("ollama")
    out.append(ToolStatus("ollama", ollama is not None, False, ollama or "", SHELL_NOTE))

    return out


def apply_all(cfg: Any, hooks: bool = True, mcp: bool = False) -> list[str]:
    paths = [
        claude_code.apply(cfg.base("anthropic"), hooks=hooks),
        codex.apply(cfg.base("openai") + "/v1"),
        envfile.apply(cfg.port),
    ]
    # Registering the MCP server is opt-in. Claude Code has a shell, so `tokunseba expand`
    # already works there, and registering spawns a Python process per session, which on
    # macOS surfaces as a window each time.
    if mcp and shutil.which("claude"):
        ok, stdout = _run(["claude", "mcp", "list"])
        if not ok:
            paths.append("could not list claude mcp servers; skipped mcp registration")
        elif MCP_NAME not in stdout:
            added, _ = _run(
                ["claude", "mcp", "add", "--scope", "user", MCP_NAME, "--", "tokunseba", "mcp"]
            )
            paths.append(
                f"registered mcp server {MCP_NAME}" if added
                else f"failed to register mcp server {MCP_NAME}"
            )
    return paths


def restore_all() -> list[str]:
    out: list[str] = []
    out.append(
        f"restored {claude_code.SETTINGS}" if claude_code.restore()
        else "claude-code: no backup to restore"
    )
    out.append(
        f"restored {codex.CONFIG}" if codex.restore() else "codex: no backup to restore"
    )
    out.append(
        f"removed shell env block from {envfile.profile_path()}" if envfile.restore()
        else "shell-env: nothing to remove"
    )
    # Leaving these set while the proxy is down would point every application on the
    # machine at a closed port, which fails loudly instead of quietly.
    for line in guiapps.restore(cfg_port()):
        out.append(f"gui-apps: {line}")
    if shutil.which("claude"):
        ok, _ = _run(["claude", "mcp", "remove", "--scope", "user", MCP_NAME])
        out.append(
            f"removed mcp server {MCP_NAME}" if ok else f"mcp server {MCP_NAME} not removed"
        )
    return out


def _proxy_reachable(port: int) -> Check:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return Check("proxy reachable", True, f"listening on 127.0.0.1:{port}")
    except OSError:
        return Check("proxy reachable", False, f"nothing listening on 127.0.0.1:{port}")


def _have(module: str) -> bool:
    """find_spec, but never raising."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _cache_drift(ledger: Any) -> Check:
    try:
        events = ledger.stats(time.time() - 86400).get("events", {})
        count = int(events.get("cache_drift", 0))
    except Exception:  # noqa: BLE001 - doctor checks must never raise
        return Check("cache drift (24h)", True, "ledger unavailable")
    return Check(
        "cache drift (24h)", count == 0,
        "no cache drift in the last 24h" if count == 0 else f"{count} cache drift events",
    )


def doctor(cfg: Any, ledger: Any) -> list[Check]:
    checks: list[Check] = [_proxy_reachable(cfg.port)]

    for tool in detect_all():
        checks.append(Check(
            f"tool: {tool.name}",
            tool.configured or not tool.installed,
            tool.note or tool.config_path,
        ))

    laya = _have("laya")
    checks.append(Check(
        "laya installed", laya,
        "installed" if laya else "pip install 'tokunseba[laya]'",
    ))

    weights = Path.home() / ".cache/huggingface/hub/models--convaiinnovations--laya"
    try:
        cached = weights.exists()
    except OSError:
        cached = False
    checks.append(Check(
        "laya weights cached", cached,
        "cached" if cached else "downloads on first use (~808 MB)",
    ))

    mcp = _have("mcp")
    checks.append(Check(
        "mcp installed", mcp, "installed" if mcp else "pip install 'tokunseba[mcp]'",
    ))

    checks.append(_cache_drift(ledger))

    daily = getattr(cfg.budget, "daily_usd", 0.0)
    checks.append(Check(
        "budget", True,
        f"daily budget ${daily:.2f}" if daily else "no daily budget set",
    ))

    try:
        from ..health import conflicting_env
        clash = conflicting_env(cfg.port)
    except Exception:  # noqa: BLE001
        clash = {}
    checks.insert(0, Check(
        "no conflicting base url", not clash,
        "clean" if not clash else
        ", ".join(f"{k}={v}" for k, v in clash.items()) + " overrides the settings file"))
    return checks
