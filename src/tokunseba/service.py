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


def executable() -> str:
    exe = shutil.which("tokunseba")
    if exe:
        return exe
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


def install() -> tuple[Path, str]:
    if platform.system() == "Darwin":
        p = plist_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_plist_xml())
        _run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"])
        code, out = _run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(p)])
        return p, ("loaded" if code == 0 else f"written, load failed: {out[:160]}")
    p = unit_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_unit_text())
    _run(["systemctl", "--user", "daemon-reload"])
    code, out = _run(["systemctl", "--user", "enable", "--now", "tokunseba"])
    return p, ("started" if code == 0 else f"written, start failed: {out[:160]}")


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
