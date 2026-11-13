"""Resolve a usable Chromium executable without requiring Playwright's CDN.

Playwright's bundled browser download may be blocked in some regions/networks.
A locally installed Chromium/Chrome can be used instead by setting
STRUCTURA_CHROMIUM_EXECUTABLE or placing a supported executable on PATH.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


class BrowserUnavailableError(RuntimeError):
    """Raised when neither a system Chromium nor Playwright browser exists."""


_CANDIDATE_COMMANDS = (
    "chromium",
    "chromium-browser",
    "google-chrome-stable",
    "google-chrome",
    "chrome",
    "msedge",
    "microsoft-edge",
)


def find_system_chromium() -> str | None:
    """Return an explicitly configured or PATH-discovered Chromium executable."""
    explicit = os.environ.get("STRUCTURA_CHROMIUM_EXECUTABLE", "").strip()
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_file():
            raise BrowserUnavailableError(
                "STRUCTURA_CHROMIUM_EXECUTABLE points to a missing file: "
                f"{candidate}. Set it to the full path of Chromium/Chrome."
            )
        if os.name != "nt" and not os.access(candidate, os.X_OK):
            raise BrowserUnavailableError(
                f"The configured browser is not executable: {candidate}"
            )
        return str(candidate.resolve())

    for command in _CANDIDATE_COMMANDS:
        found = shutil.which(command)
        if found:
            return str(Path(found).resolve())

    # Common non-PATH Chrome/Edge locations on Windows and macOS.
    if os.name == "nt":
        roots = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")),
            Path(os.environ.get("LOCALAPPDATA", "")),
        ]
        relative = (
            Path("Google/Chrome/Application/chrome.exe"),
            Path("Microsoft/Edge/Application/msedge.exe"),
        )
        for root in roots:
            for rel in relative:
                candidate = root / rel
                if candidate.is_file():
                    return str(candidate)
    elif sys_platform_is_macos():
        for candidate in (
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ):
            if candidate.is_file():
                return str(candidate)

    return None


def sys_platform_is_macos() -> bool:
    # Kept as a small helper so the main resolver remains easy to test.
    import sys
    return sys.platform == "darwin"


def launch_persistent_context(chromium: Any, **kwargs: Any):
    """Launch a persistent, sandboxed browser context.

    Playwright defaults ``chromium_sandbox`` to False and silently appends
    ``--no-sandbox`` to Chromium's command line. Passing True here is required
    to keep the browser sandbox enabled for every collector, not just the web
    inspector. Root execution is rejected because a sandboxed Chromium process
    must run as an ordinary desktop user.
    """
    if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0:
        raise BrowserUnavailableError(
            "Agent Shadi cannot launch its browser collector as root. Chromium's "
            "sandbox is enabled and --no-sandbox is not permitted. Stop Agent Shadi "
            "and restart it from your normal desktop user account without sudo; "
            "verify with: id -u (the result must not be 0)."
        )
    # This is a Playwright launch option, not a Chromium CLI switch. Without it,
    # Playwright injects --no-sandbox even when our own args list omits the flag.
    kwargs["chromium_sandbox"] = True
    print("[Browser] Chromium sandbox: enabled (Playwright chromium_sandbox=True)", flush=True)
    system_browser = find_system_chromium()
    if system_browser:
        print(f"[Browser] Using system browser: {system_browser}", flush=True)
        context = chromium.launch_persistent_context(
            executable_path=system_browser,
            **kwargs,
        )
    else:
        bundled = Path(chromium.executable_path)
        if bundled.is_file():
            print(f"[Browser] Using Playwright browser: {bundled}", flush=True)
            context = chromium.launch_persistent_context(**kwargs)
        else:
            raise BrowserUnavailableError(
                "No compatible browser executable was found. Playwright's browser CDN "
                "may be blocked in your region. On Manjaro/Arch, install Chromium with:\n"
                "  sudo pacman -S --needed chromium\n"
                "Then restart Agent Shadi. If Chromium is installed outside PATH, set:\n"
                "  STRUCTURA_CHROMIUM_EXECUTABLE=/full/path/to/chromium\n"
                "The main application can still run, but Telegram/Rubika collection "
                "requires a browser."
            )

    # PWDEBUG=1 sets Playwright's default timeout to zero; restore finite
    # operational timeouts so missing locators cannot wait forever.
    if hasattr(context, "set_default_timeout"):
        context.set_default_timeout(15_000)
    if hasattr(context, "set_default_navigation_timeout"):
        context.set_default_navigation_timeout(30_000)
    return context
