"""Helpers for tests that use the real REA runner."""

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

RUNNER_DIR = Path(__file__).resolve().parents[2] / "rea-runner"
REQUIRED_NODE = (24, 15)


@lru_cache
def rea_unavailable_reason() -> str | None:
    """None when the pinned REA release can run here, else the reason it cannot."""
    node = shutil.which("node")
    if not node:
        return "node is not installed"
    version = subprocess.run(
        [node, "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()  # noqa: S603
    try:
        major, minor = (int(p) for p in version.lstrip("v").split(".")[:2])
    except ValueError:
        return f"cannot read the node version ({version!r})"
    if (major, minor) < REQUIRED_NODE:
        return f"node {version} is older than 24.15, which REA's SQLite inspection needs"
    if not (RUNNER_DIR / "node_modules" / "rea-agents").exists():
        return "run `npm ci` in rea-runner to install the pinned rea-agents"
    return None


def browser_available() -> bool:
    import os

    candidates = [
        os.environ.get("CHROME_PATH"),
        "/usr/bin/chromium",
        "/usr/bin/google-chrome",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    return any(c and Path(c).exists() for c in candidates)
