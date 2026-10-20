"""Client for the REA runner (rea-runner/wrapper.mjs).

The runner is a thin wrapper around the pinned REA command line. It runs either as a local
process (development and tests) or as a container service reached over HTTP (rea-offline for
files, rea-browser for websites). This adapter hides the transport, applies time limits and
turns every failure into a structured ReaError. Raw output is persisted by the caller, with
the command, REA version and duration this module returns.
"""

import json
import os
import subprocess  # noqa: S404  (runs the project's own wrapper, no shell)
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

# The REA command lines the wrapper runs for each wrapper command, recorded with the evidence.
CANONICAL_COMMANDS = {
    "inspect-web-network-capture": "rea inspect-web-network-capture <capture.har> har --json",
    "inspect-sqlite-database": (
        "rea inspect-sqlite-database <db> --schema-scope database --json; "
        "rea inspect-sqlite-database <db> --table <name> --row-limit <n> --json (per table)"
    ),
    "analyze-javascript-application": "rea analyze-javascript-application <app> --json",
    "observe-website": (
        "rea inspect-web-page <cdp-endpoint> <target-id> --observation-ms <ms> --include-accessibility-text "
        "--include-storage-keys --allowed-origins <origin>... --json (page opened by the runner in a headless browser)"
    ),
}


class ReaError(Exception):
    """A failed REA call. `code` is stable and safe to show; `details` never holds file content."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.retryable = retryable

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class ReaUnavailableError(ReaError):
    """The runner could not be reached or timed out. Callers may fall back to the built in parsers."""


@dataclass(frozen=True)
class ReaRequest:
    command: str
    path: str | None = None
    url: str | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"command": self.command, "options": self.options}
        if self.path is not None:
            body["path"] = self.path
        if self.url is not None:
            body["url"] = self.url
        return body


@dataclass(frozen=True)
class ReaResponse:
    command: str
    canonical_command: str
    rea_version: str
    duration_ms: int
    result: dict[str, Any]


class Transport(Protocol):
    def call(self, request: ReaRequest, timeout_seconds: float) -> dict[str, Any]: ...

    def health(self) -> dict[str, Any]: ...


class LocalProcessTransport:
    """Runs `node wrapper.mjs run ...` as a child process (no shell)."""

    def __init__(self, command: list[str], input_dir: Path) -> None:
        self.command = command
        self.input_dir = input_dir

    def _env(self) -> dict[str, str]:
        keep = (
            "PATH",
            "HOME",
            "USERPROFILE",
            "TMPDIR",
            "TEMP",
            "TMP",
            "SystemRoot",
            "LANG",
            "CHROME_PATH",
        )
        env = {k: os.environ[k] for k in keep if k in os.environ}
        env["REA_INPUT_DIR"] = str(self.input_dir)
        return env

    def _run(self, args: list[str], timeout_seconds: float) -> dict[str, Any]:
        try:
            completed = subprocess.run(  # noqa: S603
                [*self.command, *args],
                capture_output=True,
                timeout=timeout_seconds,
                env=self._env(),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReaUnavailableError(
                "timeout",
                f"the runner did not answer within {int(timeout_seconds)} seconds",
                retryable=True,
            ) from exc
        except OSError as exc:
            raise ReaUnavailableError(
                "runner_not_found", f"could not start the runner: {exc.strerror}"
            ) from exc
        try:
            parsed = json.loads(completed.stdout.decode("utf-8"))
        except ValueError as exc:
            raise ReaUnavailableError(
                "invalid_runner_output",
                "the runner did not return JSON",
                details={"exit_code": completed.returncode},
            ) from exc
        if not isinstance(parsed, dict):
            raise ReaUnavailableError(
                "invalid_runner_output", "the runner returned an unexpected document"
            )
        return parsed

    def call(self, request: ReaRequest, timeout_seconds: float) -> dict[str, Any]:
        args = ["run", request.command]
        if request.path is not None:
            args += ["--path", request.path]
        if request.url is not None:
            args += ["--url", request.url]
        args += ["--options", json.dumps(request.options)]
        return self._run(args, timeout_seconds)

    def health(self) -> dict[str, Any]:
        return self._run(["health"], 30)


class HttpTransport:
    """Calls a runner container over the private runner network."""

    def __init__(self, base_url: str, token: str | None) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"x-runner-token": token} if token else {}

    def call(self, request: ReaRequest, timeout_seconds: float) -> dict[str, Any]:
        try:
            response = httpx.post(
                f"{self.base_url}/v1/run",
                json=request.body(),
                headers=self.headers,
                timeout=timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ReaUnavailableError(
                "timeout",
                f"the runner did not answer within {int(timeout_seconds)} seconds",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ReaUnavailableError(
                "runner_unreachable", "the runner could not be reached", retryable=True
            ) from exc
        if response.status_code in (401, 429):
            raise ReaUnavailableError(
                "runner_refused",
                f"the runner answered {response.status_code}",
                retryable=response.status_code == 429,
            )
        try:
            parsed = response.json()
        except ValueError as exc:
            raise ReaUnavailableError(
                "invalid_runner_output", "the runner did not return JSON"
            ) from exc
        return dict(parsed)

    def health(self) -> dict[str, Any]:
        try:
            response = httpx.get(f"{self.base_url}/v1/health", headers=self.headers, timeout=10)
            return dict(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise ReaUnavailableError(
                "runner_unreachable", "the runner could not be reached", retryable=True
            ) from exc


class ReaAdapter:
    def __init__(self, transport: Transport, timeout_seconds: float = 120) -> None:
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self._available: bool | None = None

    def available(self, refresh: bool = False) -> bool:
        if self._available is None or refresh:
            try:
                self._available = bool(self.transport.health().get("ok"))
            except ReaError:
                self._available = False
        return self._available

    def commands(self) -> list[str]:
        try:
            return list(self.transport.health().get("commands", []))
        except ReaError:
            return []

    def run(
        self,
        command: str,
        *,
        path: str | None = None,
        url: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> ReaResponse:
        request = ReaRequest(command, path, url, options or {})
        started = time.monotonic()
        # The runner enforces its own limits; the margin only covers transport and start up.
        envelope = self.transport.call(request, self.timeout_seconds + 30)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if not envelope.get("ok"):
            error = envelope.get("error") or {}
            raise ReaError(
                str(error.get("code", "unknown")),
                str(error.get("message", "REA failed")),
                details=error.get("details") or {},
                retryable=error.get("code") in {"timeout", "busy"},
            )
        return ReaResponse(
            command=command,
            canonical_command=CANONICAL_COMMANDS[command],
            rea_version=str(envelope.get("rea_version", "unknown")),
            duration_ms=int(envelope.get("duration_ms", elapsed_ms)),
            result=envelope["result"],
        )
