"""Runs the rea-runner's own test suite (node:test) as part of the backend tests."""

import shutil
import subprocess

import pytest

from tests.rea_support import RUNNER_DIR, rea_unavailable_reason


@pytest.mark.skipif(rea_unavailable_reason() is not None, reason=rea_unavailable_reason() or "")
def test_rea_runner_node_suite_passes() -> None:
    npm = shutil.which("npm")
    assert npm, "npm is needed to run the runner tests"
    result = subprocess.run(  # noqa: S603
        [npm, "test"], cwd=RUNNER_DIR, capture_output=True, text=True, timeout=240, check=False
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1000:]
    assert "fail 0" in result.stdout


def test_runner_is_pinned_to_one_rea_release() -> None:
    import json

    package = json.loads((RUNNER_DIR / "package.json").read_text(encoding="utf-8"))
    assert package["dependencies"] == {"rea-agents": "6.7.0"}
    assert package["engines"]["node"] == ">=24.15.0"
    lock = json.loads((RUNNER_DIR / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["packages"]["node_modules/rea-agents"]["version"] == "6.7.0"
