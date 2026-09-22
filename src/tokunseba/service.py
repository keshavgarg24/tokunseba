"""Run the proxy in the background: launchd on macOS, systemd user units on Linux."""
from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from .config import home

LABEL = "dev.tokunseba.proxy"


TRANSIENT = ("/.cache/uv/builds-v0/", "/.tmp", "/pytest-of-", "/T/tmp")


def executable() -> str:
    """A path that will still exist tomorrow.

    `which` can resolve to a uv build sandbox that is deleted the moment the build finishes.
    Baking that into a launch agent produces a service that silently never starts again.
    """
    exe = shutil.which("tokunseba")
    if exe and not any(bit in exe for bit in TRANSIENT):
        return exe
    for candidate in (Path.home() / ".local/bin/tokunseba",
                      Path("/usr/local/bin/tokunseba"),
                      Path("/opt/homebrew/bin/tokunseba")):
        if candidate.exists():
            return str(candidate)
    return f"{sys.executable} -m tokunseba.cli"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "tokunseba.service"


def running(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _logs() -> Path:
    d = home() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "proxy.log"


def _plist_xml() -> str:
    exe = executable()
    parts = exe.split(" ") + ["start", "--foreground"]
    args = "\n".join(f"    <string>{p}</string>" for p in parts)
    log = _logs()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
{args}
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
  <key>EnvironmentVariables</key>
  <dict><key>TOKUNSEBA_HOME</key><string>{home()}</string></dict>
</dict>
</plist>
"""


def _unit_text() -> str:
    return f"""[Unit]
Description=tokunseba local token-optimising proxy

[Service]
ExecStart={executable()} start --foreground
Restart=always
RestartSec=2
Environment=TOKUNSEBA_HOME={home()}
StandardOutput=append:{_logs()}
StandardError=append:{_logs()}

[Install]
WantedBy=default.target
"""


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def install(port: int | None = None) -> tuple[Path, str]:
    """Write and load the background service.

    A proxy already listening on the port is the common case, not an error: the user very
    likely started one by hand. Say that instead of surfacing a raw launchctl code.
    """
    if platform.system() == "Darwin":
        p = plist_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_plist_xml())
        _run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"])
        code, out = _run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(p)])
        if code == 0:
            return p, "loaded"
        if port is not None and running(port):
            return p, (f"written; a proxy is already listening on {port}. Stop it and run "
                       f"`tokunseba start` to hand over to the service.")
        return p, f"written, load failed: {out[:160]}"
    p = unit_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_unit_text())
    _run(["systemctl", "--user", "daemon-reload"])
    code, out = _run(["systemctl", "--user", "enable", "--now", "tokunseba"])
    if code == 0:
        return p, "started"
    if port is not None and running(port):
        return p, (f"written; a proxy is already listening on {port}. Stop it and run "
                   f"`tokunseba start` to hand over to the service.")
    return p, f"written, start failed: {out[:160]}"


def uninstall() -> str:
    if platform.system() == "Darwin":
        _run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"])
        plist_path().unlink(missing_ok=True)
        return "launchd agent removed"
    _run(["systemctl", "--user", "disable", "--now", "tokunseba"])
    unit_path().unlink(missing_ok=True)
    return "systemd unit removed"


def stop() -> str:
    if platform.system() == "Darwin":
        code, out = _run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"])
        return "stopped" if code == 0 else f"not running ({out[:80]})"
    code, out = _run(["systemctl", "--user", "stop", "tokunseba"])
    return "stopped" if code == 0 else f"not running ({out[:80]})"
