"""Is tokunseba actually in the path?

This is the failure mode that matters most and is hardest to notice. A tool that is not
routed through the proxy produces no error, no warning and no traffic: the ledger simply
stays empty and every number reads zero, which looks identical to "nothing was compressible".
Every command that shows numbers asks this first and says so plainly.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

BASE_VARS = (
    "ANTHROPIC_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE", "OLLAMA_HOST",
)


#: Appended wherever "configured but silent" is the symptom, because a GUI-launched
#: application is by far the most common reason for it and the least visible.
GUI_HINT = ("An application you open from the Dock or Spotlight never reads your shell "
            "profile, so it needs one more step: tokunseba apps on")


@dataclass
class Routing:
    proxy_running: bool
    port: int
    routed_tools: list[str]
    unrouted_installed: list[str]
    requests_last_hour: int
    requests_ever: int
    overriding_env: dict[str, str] | None = None

    @property
    def in_the_path(self) -> bool:
        return bool(self.routed_tools)

    @property
    def problem(self) -> str | None:
        """The single most useful sentence, or None when everything is fine."""
        if self.overriding_env:
            names = ", ".join(sorted(self.overriding_env))
            first = sorted(self.overriding_env)[0]
            return (f"{names} is already exported in your environment, pointing somewhere "
                    f"other than tokunseba ({self.overriding_env[first]}). An exported "
                    f"variable beats the settings file, so your tool bypasses the proxy no "
                    f"matter what `tokunseba init` writes. Unset it and start your tool from a "
                    f"new shell. If you open that tool from the Dock rather than by "
                    f"typing its name, it never reads your shell profile at all: "
                    f"tokunseba apps on")
        if not self.proxy_running:
            return ("The proxy is not running, so nothing is being routed through it. "
                    "Start it with: tokunseba start")
        if not self.routed_tools:
            n = len(self.unrouted_installed)
            if n == 1:
                who = f"{self.unrouted_installed[0]} is installed but goes"
            elif n > 1:
                who = f"{', '.join(self.unrouted_installed)} are installed but go"
            else:
                who = "Your tools go"
            return (f"No tool is routed through tokunseba, so it sees none of your traffic and "
                    f"every number below is zero for that reason. {who} straight to the "
                    f"provider. Fix it with: tokunseba init")
        if self.requests_ever == 0:
            return ("Configured, but nothing has come through yet. Open a NEW terminal so the "
                    "settings take effect, then use your tool as normal. " + GUI_HINT)
        if self.requests_last_hour == 0:
            return ("Configured, but nothing has come through in the last hour. If you have "
                    "been working, check that the tool was started from a shell opened after "
                    "`tokunseba init`. " + GUI_HINT)
        return None


def check(cfg, ledger) -> Routing:
    from .detect import registry
    from .service import running

    routed, unrouted = [], []
    try:
        for t in registry.detect_all():
            if t.configured:
                routed.append(t.name)
            elif t.installed and t.name not in ("shell-env", "gui-apps"):
                unrouted.append(t.name)
    except Exception:  # noqa: BLE001 - never let a health check break a report
        pass
    try:
        hour = ledger.stats(time.time() - 3600)["requests"]
        ever = ledger.stats(0)["requests"]
    except Exception:  # noqa: BLE001
        hour = ever = 0
    return Routing(proxy_running=running(cfg.port), port=cfg.port, routed_tools=routed,
                   unrouted_installed=unrouted, requests_last_hour=hour, requests_ever=ever,
                   overriding_env=conflicting_env(cfg.port))


def conflicting_env(port: int) -> dict[str, str]:
    """Exported base URLs that point away from tokunseba.

    This is the trap that wastes the most time. Claude Code and friends read a base URL from
    their settings file, but an exported environment variable wins. The Claude desktop app
    exports ANTHROPIC_BASE_URL for the terminals it spawns, so a perfectly correct `init` is
    silently overridden and the proxy sees nothing at all.
    """
    mine = f"127.0.0.1:{port}"
    out = {}
    for name in BASE_VARS:
        val = os.environ.get(name)
        if val and mine not in val and "localhost:" not in val:
            out[name] = val
    return out
