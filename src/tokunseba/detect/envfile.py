"""Shell env block: ~/.tokunseba/env.sh sourced from the user's shell profile."""
from __future__ import annotations

import os
from pathlib import Path

from ..config import home

START = "# >>> tokunseba >>>"
END = "# <<< tokunseba <<<"
SOURCE_LINE = '[ -f "$HOME/.tokunseba/env.sh" ] && source "$HOME/.tokunseba/env.sh"'
BLOCK = f"{START}\n{SOURCE_LINE}\n{END}"

#: Tests point this at a temporary profile file.
PROFILE_OVERRIDE: Path | None = None


def env_sh() -> Path:
    """Path to env.sh. Computed lazily: home() reads TOKUNSEBA_HOME at call time."""
    return home() / "env.sh"


def profile_path() -> Path:
    if PROFILE_OVERRIDE is not None:
        return Path(PROFILE_OVERRIDE)
    shell = os.environ.get("SHELL", "")
    return Path.home() / (".zshrc" if shell.endswith("zsh") else ".bashrc")


def _exports(port: int) -> str:
    root = f"http://127.0.0.1:{port}"
    return (
        f'export ANTHROPIC_BASE_URL="{root}/anthropic"\n'
        f'export OPENAI_BASE_URL="{root}/openai/v1"\n'
        f'export OPENAI_API_BASE="{root}/openai/v1"\n'
        f'export OLLAMA_HOST="{root}/ollama"\n'
    )


def _read(path: Path) -> str:
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return ""


def _span(text: str) -> tuple[int, int] | None:
    """Byte span of the marker block, excluding any trailing newline."""
    i = text.find(START)
    if i == -1:
        return None
    j = text.find(END, i)
    if j == -1:
        return None
    return i, j + len(END)


def apply(port: int) -> str:
    """Write env.sh and source it from the profile exactly once. Idempotent."""
    path = env_sh()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_exports(port))

    profile = profile_path()
    text = _read(profile) if profile.exists() else ""
    span = _span(text)
    if span is not None:
        start, end = span
        new = text[:start] + BLOCK + text[end:]
    else:
        new = (text + "\n" if text else "") + BLOCK + "\n"
    if new != text or not profile.exists():
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_text(new)
    return str(path)


def restore() -> bool:
    """Remove the marker block and env.sh; the rest of the profile is untouched."""
    changed = False
    profile = profile_path()
    if profile.exists():
        text = _read(profile)
        span = _span(text)
        if span is not None:
            start, end = span
            if text[end:end + 1] == "\n":
                end += 1
            if start > 0 and text[start - 1] == "\n":
                start -= 1
            profile.write_text(text[:start] + text[end:])
            changed = True
    path = env_sh()
    if path.exists():
        path.unlink()
        changed = True
    return changed


def status() -> tuple[bool, bool, str]:
    profile = profile_path()
    configured = _span(_read(profile)) is not None if profile.exists() else False
    note = f"env block {'present in' if configured else 'missing from'} {profile}"
    return True, configured, note
