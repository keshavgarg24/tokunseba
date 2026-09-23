"""Run a tool with tokunseba already in its environment.

This exists because pointing a tool at the proxy by writing its settings file is unreliable.
An exported base URL beats a settings file, and several launchers export one, so a correct
`init` can be silently overridden and the proxy never sees a single request.

Wrapping removes the ambiguity: the variables are set on the child process itself, so nothing
inherited can win. It also needs no configuration to undo, because it changes nothing outside
the process it starts.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Wrappable:
    name: str
    binary: str
    env: dict[str, str] = field(default_factory=dict)
    note: str = ""


def _anthropic(port: int) -> dict[str, str]:
    return {"ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}/anthropic"}


def _openai(port: int) -> dict[str, str]:
    base = f"http://127.0.0.1:{port}/openai/v1"
    return {"OPENAI_BASE_URL": base, "OPENAI_API_BASE": base}


def _ollama(port: int) -> dict[str, str]:
    return {"OLLAMA_HOST": f"http://127.0.0.1:{port}/ollama"}


def _gemini(port: int) -> dict[str, str]:
    return {"GOOGLE_GEMINI_BASE_URL": f"http://127.0.0.1:{port}/gemini"}


def registry(port: int) -> dict[str, Wrappable]:
    both = {**_anthropic(port), **_openai(port)}
    return {
        "claude": Wrappable("claude", "claude", _anthropic(port), "Claude Code"),
        "codex": Wrappable("codex", "codex", _openai(port), "OpenAI Codex CLI"),
        "aider": Wrappable("aider", "aider", both, "Aider"),
        "opencode": Wrappable("opencode", "opencode", both, "OpenCode"),
        "cline": Wrappable("cline", "cline", both, "Cline CLI"),
        "continue": Wrappable("continue", "cn", both, "Continue CLI"),
        "goose": Wrappable("goose", "goose", both, "Goose"),
        "gemini": Wrappable("gemini", "gemini", _gemini(port), "Gemini CLI"),
        "ollama": Wrappable("ollama", "ollama", _ollama(port), "Ollama client"),
        "crush": Wrappable("crush", "crush", both, "Crush"),
        "qwen": Wrappable("qwen", "qwen", both, "Qwen Code"),
    }


UNSUPPORTED = {
    "cursor": "Cursor talks to its own backend over a closed protocol.",
    "copilot": "GitHub Copilot talks to its own backend over a closed protocol.",
    "windsurf": "Windsurf talks to its own backend over a closed protocol.",
}


def full_env(port: int) -> dict[str, str]:
    """Every base URL tokunseba serves, for wrapping an arbitrary command."""
    return {**_anthropic(port), **_openai(port), **_ollama(port), **_gemini(port)}


def build_env(overrides: dict[str, str], base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env.update(overrides)
    env["TOKUNSEBA_WRAPPED"] = "1"
    return env


def resolve(name: str, port: int) -> Wrappable | None:
    return registry(port).get(name.lower())


def available(port: int) -> list[tuple[Wrappable, bool]]:
    return [(w, shutil.which(w.binary) is not None) for w in registry(port).values()]


def exec_wrapped(binary: str, argv: list[str], env: dict[str, str]) -> int:
    """Replace this process with the tool. Falls back to a subprocess where exec is unavailable."""
    path = shutil.which(binary)
    if path is None:
        return 127
    try:
        os.execvpe(path, [path, *argv], env)
    except OSError:
        return subprocess.run([path, *argv], env=env).returncode
    return 0  # unreachable when exec succeeds
