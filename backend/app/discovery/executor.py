"""Run the extractors for one evidence item.

REA is the primary extractor. A deterministic fallback parser runs when REA is unavailable,
when a REA call fails, or when the pinned release does not provide a capability (form input
names for websites). Every extractor run yields its own `Extraction`, which records the
extractor, the command, the REA version and the duration.
"""

import json
import shutil
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.uploads import safe_filename
from app.db.enums import EvidenceKind, Extractor
from app.discovery import masking
from app.discovery.candidates import Extraction
from app.discovery.extractors import har, javascript, sqlite, website
from app.discovery.rea_adapter import (
    CANONICAL_COMMANDS,
    HttpTransport,
    LocalProcessTransport,
    ReaAdapter,
    ReaError,
)

SUPPORTED_KINDS = (
    EvidenceKind.HAR,
    EvidenceKind.WEBSITE,
    EvidenceKind.JAVASCRIPT_BUNDLE,
    EvidenceKind.SQLITE_SNAPSHOT,
)
FALLBACK_COMMANDS = {
    EvidenceKind.HAR: "fallback: python json parser over HAR log.entries",
    EvidenceKind.WEBSITE: "fallback: beautifulsoup html.parser over the saved page",
    EvidenceKind.JAVASCRIPT_BUNDLE: "fallback: regular expression scan of the script source",
    EvidenceKind.SQLITE_SNAPSHOT: "fallback: python sqlite3 (read only, immutable) schema and bounded row sample",
}


@dataclass
class ReaClients:
    offline: ReaAdapter
    browser: ReaAdapter


def build_rea_clients(settings: Settings) -> ReaClients | None:
    if not settings.rea_enabled:
        return None
    token = settings.rea_runner_token.get_secret_value() if settings.rea_runner_token else None
    if settings.rea_transport == "http":
        offline = ReaAdapter(
            HttpTransport(settings.rea_offline_url, token), settings.rea_timeout_seconds
        )
        browser = ReaAdapter(
            HttpTransport(settings.rea_browser_url, token), settings.rea_timeout_seconds
        )
    else:
        local = LocalProcessTransport(
            settings.rea_local_command, Path(settings.rea_input_dir).resolve()
        )
        offline = browser = ReaAdapter(local, settings.rea_timeout_seconds)
    return ReaClients(offline, browser)


class Executor:
    def __init__(self, settings: Settings, clients: ReaClients | None) -> None:
        self.settings = settings
        self.clients = clients
        self.input_dir = Path(settings.rea_input_dir).resolve()

    @contextmanager
    def staged(self, data: bytes, filename: str) -> Iterator[str]:
        """Write plaintext evidence where the runner can read it, and remove it afterwards."""
        token = uuid.uuid4().hex
        directory = self.input_dir / token
        directory.mkdir(parents=True, exist_ok=True)
        (directory / safe_filename(filename)).write_bytes(data)
        try:
            yield f"{token}/{safe_filename(filename)}"
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    # -- REA ----------------------------------------------------------------------------------
    def _rea(self, kind: EvidenceKind) -> ReaAdapter | None:
        if self.clients is None:
            return None
        adapter = self.clients.browser if kind is EvidenceKind.WEBSITE else self.clients.offline
        return adapter if adapter.available() else None

    @staticmethod
    def _failed(
        kind: EvidenceKind,
        extractor: Extractor,
        command: str,
        error: ReaError | Exception,
        duration_ms: int = 0,
    ) -> Extraction:
        message = str(error) if isinstance(error, ReaError) else f"{type(error).__name__}: {error}"
        return Extraction(
            kind, extractor, command, status="error", error=message[:2000], duration_ms=duration_ms
        )

    def process(
        self, kind: EvidenceKind, filename: str, data: bytes, own_host: str | None
    ) -> list[Extraction]:
        """All extractor runs for one stored file."""
        if kind is EvidenceKind.HAR:
            return self._har(filename, data, own_host)
        if kind is EvidenceKind.SQLITE_SNAPSHOT:
            return self._sqlite(filename, data)
        if kind is EvidenceKind.JAVASCRIPT_BUNDLE:
            return self._javascript(filename, data, own_host)
        if kind is EvidenceKind.WEBSITE:
            return self._website(filename, data, own_host)
        raise ValueError(f"unsupported evidence kind {kind}")

    # -- network capture ----------------------------------------------------------------------
    def _har(self, filename: str, data: bytes, own_host: str | None) -> list[Extraction]:
        kind = EvidenceKind.HAR
        runs: list[Extraction] = []
        adapter = self._rea(kind)
        if adapter:
            try:
                with self.staged(data, filename) as rel:
                    response = adapter.run("inspect-web-network-capture", path=rel)
                entries = har.entries_from_rea(response.result)
                elements, recipients, own = har.extract_entries(entries, own_host)
                raw, truncated = masking.finalize_raw(masking.mask_har_rea(response.result))
                runs.append(
                    Extraction(kind, Extractor.REA, response.canonical_command, response.rea_version, response.duration_ms,
                               raw_output=raw, raw_sha256=masking.sha256_of(response.result), raw_truncated=truncated,
                               elements=elements, recipients=recipients, notes=[f"own_host={own}"])
                )  # fmt: skip
                return runs
            except (ReaError, KeyError, TypeError, ValueError) as exc:
                runs.append(
                    self._failed(
                        kind, Extractor.REA, CANONICAL_COMMANDS["inspect-web-network-capture"], exc
                    )
                )
        started = time.monotonic()
        try:
            entries = har.entries_from_fallback(data)
            elements, recipients, own = har.extract_entries(entries, own_host)
            document = json.loads(data.decode("utf-8-sig"))
            raw, truncated = masking.finalize_raw(
                masking.mask_har_fallback(entries, document["log"].get("creator"))
            )
            runs.append(
                Extraction(kind, Extractor.FALLBACK, FALLBACK_COMMANDS[kind], None, int((time.monotonic() - started) * 1000),
                           raw_output=raw, raw_sha256=masking.sha256_of(document), raw_truncated=truncated,
                           elements=elements, recipients=recipients, notes=[f"own_host={own}"])
            )  # fmt: skip
        except (KeyError, TypeError, ValueError) as exc:
            runs.append(self._failed(kind, Extractor.FALLBACK, FALLBACK_COMMANDS[kind], exc))
        return runs

    # -- sqlite snapshot ----------------------------------------------------------------------
    def _sqlite(self, filename: str, data: bytes) -> list[Extraction]:
        kind = EvidenceKind.SQLITE_SNAPSHOT
        runs: list[Extraction] = []
        adapter = self._rea(kind)
        if adapter:
            try:
                with self.staged(data, filename) as rel:
                    response = adapter.run(
                        "inspect-sqlite-database",
                        path=rel,
                        options={"row_limit": self.settings.sqlite_row_sample},
                    )
                tables = sqlite.tables_from_rea(response.result)
                raw, truncated = masking.finalize_raw(masking.mask_sqlite_rea(response.result))
                runs.append(
                    Extraction(kind, Extractor.REA, response.canonical_command, response.rea_version, response.duration_ms,
                               raw_output=raw, raw_sha256=masking.sha256_of(response.result), raw_truncated=truncated,
                               elements=sqlite.extract_tables(tables))
                )  # fmt: skip
                return runs
            except (ReaError, KeyError, TypeError, ValueError) as exc:
                runs.append(
                    self._failed(
                        kind, Extractor.REA, CANONICAL_COMMANDS["inspect-sqlite-database"], exc
                    )
                )
        started = time.monotonic()
        try:
            with self.staged(data, filename) as rel:
                tables = sqlite.tables_from_file(
                    self.input_dir / rel, self.settings.sqlite_row_sample
                )
            raw, truncated = masking.finalize_raw(masking.mask_sqlite_fallback(tables))
            runs.append(
                Extraction(kind, Extractor.FALLBACK, FALLBACK_COMMANDS[kind], None, int((time.monotonic() - started) * 1000),
                           raw_output=raw, raw_sha256=masking.sha256_of(raw), raw_truncated=truncated,
                           elements=sqlite.extract_tables(tables))
            )  # fmt: skip
        except Exception as exc:  # sqlite3 raises several unrelated error types on bad input
            runs.append(self._failed(kind, Extractor.FALLBACK, FALLBACK_COMMANDS[kind], exc))
        return runs

    # -- javascript bundle --------------------------------------------------------------------
    def _javascript(self, filename: str, data: bytes, own_host: str | None) -> list[Extraction]:
        kind = EvidenceKind.JAVASCRIPT_BUNDLE
        runs: list[Extraction] = []
        adapter = self._rea(kind)
        if adapter:
            try:
                with self.staged(data, filename) as rel:
                    response = adapter.run("analyze-javascript-application", path=rel)
                technologies, recipients = javascript.extract_rea(response.result, own_host)
                trimmed, was_trimmed = masking.trim_js_rea(response.result)
                raw, truncated = masking.finalize_raw(trimmed, was_trimmed)
                runs.append(
                    Extraction(kind, Extractor.REA, response.canonical_command, response.rea_version, response.duration_ms,
                               raw_output=raw, raw_sha256=masking.sha256_of(response.result), raw_truncated=truncated,
                               recipients=recipients, technologies=technologies)
                )  # fmt: skip
                return runs
            except (ReaError, KeyError, TypeError, ValueError) as exc:
                runs.append(
                    self._failed(
                        kind,
                        Extractor.REA,
                        CANONICAL_COMMANDS["analyze-javascript-application"],
                        exc,
                    )
                )
        started = time.monotonic()
        try:
            source = data.decode("utf-8", errors="replace")
            technologies, recipients = javascript.extract_fallback(source, own_host)
            raw = {"parser": "regex", "bytes": len(data), "packages": sum(t.kind == "package" for t in technologies),
                   "routes": sum(t.kind == "route" for t in technologies), "ipc_channels": sum(t.kind == "ipc_channel" for t in technologies),
                   "hosts": [r.host for r in recipients]}  # fmt: skip
            runs.append(
                Extraction(kind, Extractor.FALLBACK, FALLBACK_COMMANDS[kind], None, int((time.monotonic() - started) * 1000),
                           raw_output=raw, raw_sha256=masking.sha256_of(source), recipients=recipients, technologies=technologies)
            )  # fmt: skip
        except Exception as exc:
            runs.append(self._failed(kind, Extractor.FALLBACK, FALLBACK_COMMANDS[kind], exc))
        return runs

    # -- website ------------------------------------------------------------------------------
    def _website(self, filename: str, data: bytes, own_host: str | None) -> list[Extraction]:
        """Static parse of the saved page (always) plus REA's browser observation (when available)."""
        kind = EvidenceKind.WEBSITE
        runs: list[Extraction] = []
        started = time.monotonic()
        html = data.decode("utf-8", errors="replace")
        parsed = website.parse_html(html, own_host)
        runs.append(
            Extraction(
                kind, Extractor.FALLBACK, FALLBACK_COMMANDS[kind], None, int((time.monotonic() - started) * 1000),
                raw_output={"parser": "html.parser", "controls": parsed.controls, "hosts": [r.host for r in parsed.recipients]},
                raw_sha256=masking.sha256_of(html), elements=parsed.elements, recipients=parsed.recipients,
                notes=["REA's page inspection keeps attribute names but not values, so input names come from this parser"],
            )
        )  # fmt: skip
        adapter = self._rea(kind)
        if adapter:
            try:
                with self.staged(data, filename) as rel:
                    response = adapter.run(
                        "observe-website", path=rel,
                        options={"allowed_origins": sorted(parsed.origins), "observation_ms": self.settings.rea_observation_ms},
                    )  # fmt: skip
                recipients, controls = website.observed_hosts_rea(response.result, own_host)
                raw, truncated = masking.finalize_raw({"page_origin": response.result["page_origin"], "allowed_origins": response.result["allowed_origins"],
                                                       "observation": response.result["evidence"], "controls": controls})  # fmt: skip
                runs.append(
                    Extraction(kind, Extractor.REA, response.canonical_command, response.rea_version, response.duration_ms,
                               raw_output=raw, raw_sha256=masking.sha256_of(response.result), raw_truncated=truncated,
                               recipients=recipients)
                )  # fmt: skip
            except (ReaError, KeyError, TypeError, ValueError) as exc:
                runs.append(
                    self._failed(kind, Extractor.REA, CANONICAL_COMMANDS["observe-website"], exc)
                )
        return runs

    def observe_url(self, url: str, own_host: str | None) -> list[Extraction]:
        """A registered URL can only be observed by the browser runner. The API never fetches it."""
        kind = EvidenceKind.WEBSITE
        adapter = self._rea(kind)
        if adapter is None:
            return [
                self._failed(
                    kind,
                    Extractor.REA,
                    CANONICAL_COMMANDS["observe-website"],
                    ReaError(
                        "runner_unavailable",
                        "the browser runner is not available; a registered URL cannot be read without it",
                    ),
                )
            ]
        try:
            response = adapter.run(
                "observe-website",
                url=url,
                options={"observation_ms": self.settings.rea_observation_ms},
            )
            recipients, controls = website.observed_hosts_rea(response.result, own_host)
            raw, truncated = masking.finalize_raw(
                {
                    "page_origin": response.result["page_origin"],
                    "observation": response.result["evidence"],
                    "controls": controls,
                }
            )
            return [Extraction(kind, Extractor.REA, response.canonical_command, response.rea_version, response.duration_ms,
                               raw_output=raw, raw_sha256=masking.sha256_of(response.result), raw_truncated=truncated, recipients=recipients)]  # fmt: skip
        except (ReaError, KeyError, TypeError, ValueError) as exc:
            return [self._failed(kind, Extractor.REA, CANONICAL_COMMANDS["observe-website"], exc)]


def raw_summary(extraction: Extraction) -> dict[str, Any]:
    return {
        "extractor": extraction.extractor.value,
        "status": extraction.status,
        "error": extraction.error,
        "elements": len(extraction.elements),
        "recipients": len(extraction.recipients),
        "technologies": len(extraction.technologies),
        "duration_ms": extraction.duration_ms,
        "rea_version": extraction.rea_version,
    }
