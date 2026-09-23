"""Environment for applications launched outside a shell: the Dock, Spotlight, a desktop menu.

This is the single most confusing way for tokunseba to be installed correctly and still see
nothing. `tokunseba init` writes an env block into your shell profile, which is the right
place for it: a terminal reads that file every time it opens. A GUI application does not.
macOS starts it from launchd and Linux from the desktop session, and neither runs .zshrc, so
the application inherits an environment in which tokunseba was never mentioned. It then falls
back to the provider's own default and goes straight out to the internet. Nothing errors. The
report simply reads zero, which looks exactly like "there was nothing to save".

The fix is a per-user session variable that the session hands to every application it
launches afterwards. That is a change outside this project's own directory and outside the
files `init` touches, so it is a separate command that says what it will do before doing it,
and `tokunseba apps off` takes it back out.

Scope of the change, stated plainly because the whole point of this module is disclosure:

  macOS   `launchctl setenv` writes four variables into the current GUI login session, and a
          small launch agent at ~/Library/LaunchAgents/dev.tokunseba.appenv.plist re-applies
          them at the next login. Every application you open after that inherits them, not
          only AI tools. Applications already open keep the environment they started with.
  Linux   ~/.config/environment.d/tokunseba.conf, which systemd reads when the user session
          starts. It takes effect at the next login and not before.
  Windows Not automated. The command prints the two `setx` lines to run instead.
"""
from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

LABEL = "dev.tokunseba.appenv"

#: The variables an AI tool reads to decide where its API lives. Same set as the shell block,
#: deliberately: if the two ever disagree, whichever the tool happened to inherit wins and the
#: difference is invisible.
VARS = ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE", "OLLAMA_HOST")


def values(port: int) -> dict[str, str]:
    root = f"http://127.0.0.1:{port}"
    return {"ANTHROPIC_BASE_URL": f"{root}/anthropic",
            "OPENAI_BASE_URL": f"{root}/openai/v1",
            "OPENAI_API_BASE": f"{root}/openai/v1",
            "OLLAMA_HOST": f"{root}/ollama"}


SEAL = "TOKUNSEBA_NO_SESSION_ENV"


def sealed() -> bool:
    """True when tokunseba must not read or write the login session at all.

    The test suite sets this: a suite that ran `launchctl unsetenv` against the machine it
    happens to be running on would be a very unpleasant surprise. It doubles as the escape
    hatch for anyone who wants every other part of tokunseba but not this one.
    """
    return bool(os.environ.get(SEAL))


def system() -> str:
    """macos, linux or other. Split out so tests can drive both paths on one machine."""
    s = platform.system()
    return {"Darwin": "macos", "Linux": "linux"}.get(s, "other")


def agent_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def env_conf() -> Path:
    return Path.home() / ".config" / "environment.d" / "tokunseba.conf"


def supported() -> bool:
    return not sealed() and system() in ("macos", "linux")


# ----------------------------------------------------------------- what it would change
def plan(port: int) -> list[str]:
    """Every change `apply` would make, in the order it would make them.

    Printed before asking. A user who reads this and says no has lost nothing, which is the
    only reason it is safe to offer a command that edits the login session at all.
    """
    vals = values(port)
    kind = system()
    if kind == "macos":
        lines = [f"launchctl setenv {name} {vals[name]}" for name in VARS]
        lines.append(f"write {agent_plist()} so the four survive a restart")
        return lines
    if kind == "linux":
        return [f"write {env_conf()} containing:"] + [f"    {n}={vals[n]}" for n in VARS]
    return []


def manual(port: int) -> list[str]:
    """What to run by hand where this cannot be automated."""
    vals = values(port)
    if system() == "other":
        return [f'setx {name} "{vals[name]}"' for name in VARS]
    return []


# ----------------------------------------------------------------------------- applying
def _plist_xml(port: int) -> str:
    vals = values(port)
    script = "; ".join(f"launchctl setenv {n} {vals[n]}" for n in VARS)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>-c</string>
    <string>{script}</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
"""


def _launchctl(*args: str) -> tuple[bool, str]:
    try:
        p = subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=10)
        return p.returncode == 0, (p.stderr or p.stdout).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def apply(port: int) -> list[str]:
    """Make GUI applications route through the proxy. Idempotent.

    Returns one line per change, for printing. Never raises: a machine where launchctl is
    missing or refuses should say so and leave everything else working.
    """
    if sealed():
        return [f"{SEAL} is set, so the login session was not touched"]
    vals = values(port)
    kind = system()
    out: list[str] = []
    if kind == "macos":
        for name in VARS:
            ok, msg = _launchctl("setenv", name, vals[name])
            out.append(f"set {name}" if ok else f"could not set {name}: {msg}")
        path = agent_plist()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_plist_xml(port))
            _launchctl("unload", str(path))
            _launchctl("load", str(path))
            out.append(f"wrote {path}")
        except OSError as exc:
            out.append(f"could not write {path}: {exc}")
        return out
    if kind == "linux":
        path = env_conf()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(f"{n}={vals[n]}\n" for n in VARS))
            out.append(f"wrote {path}")
        except OSError as exc:
            out.append(f"could not write {path}: {exc}")
        return out
    return ["this platform has no per-session environment tokunseba can set"]


def restore(port: int | None = None) -> list[str]:
    """Take the variables back out. Safe to run when nothing was ever applied.

    Only clears a variable that currently points at a tokunseba proxy. Somebody who set
    ANTHROPIC_BASE_URL in their login session for their own reasons should not lose it
    because they ran `tokunseba off`.
    """
    if sealed():
        return [f"{SEAL} is set, so the login session was not touched"]
    kind = system()
    out: list[str] = []
    if kind == "macos":
        have = current()
        mine = f"127.0.0.1:{port}" if port else "127.0.0.1:"
        cleared = 0
        for name in VARS:
            got = have.get(name) or ""
            if not got:
                continue
            if mine not in got:
                out.append(f"left {name} alone: it points at {got}, not at tokunseba")
                continue
            ok, msg = _launchctl("unsetenv", name)
            if ok:
                cleared += 1
            elif msg:
                out.append(f"could not unset {name}: {msg}")
        if cleared:
            out.append(f"unset {cleared} variable{'s' if cleared != 1 else ''} "
                       f"in this login session")
        path = agent_plist()
        if path.exists():
            _launchctl("unload", str(path))
            try:
                path.unlink()
                out.append(f"removed {path}")
            except OSError as exc:
                out.append(f"could not remove {path}: {exc}")
        return out or ["nothing to remove"]
    if kind == "linux":
        path = env_conf()
        if path.exists():
            try:
                path.unlink()
                out.append(f"removed {path}")
            except OSError as exc:
                out.append(f"could not remove {path}: {exc}")
        return out or ["nothing to remove"]
    return ["nothing to remove"]


# ------------------------------------------------------------------------------- status
def current() -> dict[str, str]:
    """What a GUI application launched right now would actually see.

    On macOS this asks launchd rather than reading os.environ, because os.environ here is
    the environment of whatever shell started tokunseba, which is exactly the environment
    the GUI application does not have.
    """
    if sealed():
        return dict.fromkeys(VARS, "")
    kind = system()
    if kind == "macos":
        out = {}
        for name in VARS:
            ok, msg = _launchctl("getenv", name)
            out[name] = msg if ok and msg else ""
        return out
    if kind == "linux":
        text = ""
        try:
            text = env_conf().read_text()
        except OSError:
            pass
        out = dict.fromkeys(VARS, "")
        for line in text.splitlines():
            key, _, val = line.partition("=")
            if key.strip() in out:
                out[key.strip()] = val.strip()
        return out
    return {name: os.environ.get(name, "") for name in VARS}


def configured(port: int) -> bool:
    """True when every variable a GUI application reads points at this proxy."""
    want = values(port)
    have = current()
    return all(have.get(name) == want[name] for name in VARS)


def status(port: int) -> tuple[bool, bool, str]:
    """(installed, configured, note), matching the shape the tool registry uses."""
    if sealed():
        return False, False, f"{SEAL} is set; tokunseba leaves the login session alone"
    if not supported():
        return False, False, "no per-session environment on this platform"
    on = configured(port)
    where = agent_plist() if system() == "macos" else env_conf()
    if on:
        return True, True, f"GUI applications route through the proxy ({where.name})"
    have = [n for n, v in current().items() if v]
    if have:
        return True, False, f"partly set: {', '.join(have)} but not all four"
    return True, False, "GUI applications go straight to the provider (tokunseba apps on)"


def likely_gui_parent() -> bool:
    """Is this process descended from something the Dock started rather than a terminal?

    A heuristic and only ever used to make a message more specific, never to change
    behaviour. A login shell exports SHLVL and a terminal sets TERM; an application launched
    by launchd has neither, and macOS stamps it with an app bundle path in __CFBundleIdentifier.
    """
    if system() != "macos":
        return False
    return bool(os.environ.get("__CFBundleIdentifier")) and not os.environ.get("TERM_PROGRAM")
