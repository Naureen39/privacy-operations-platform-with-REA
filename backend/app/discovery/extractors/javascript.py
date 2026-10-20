"""JavaScript or Electron bundle extraction: packages and SDKs, routes, IPC channels, the
database the app opens, and the URLs (hence hosts) it contains.

The REA path reads the graph of `analyze-javascript-application` (require and import
references, route and IPC nodes, string literals of the semantic graph). The fallback path
scans the source text with regular expressions.
"""

import re
from collections import defaultdict
from typing import Any
from urllib.parse import urlsplit

from app.discovery.candidates import RecipientCandidate, TechnologyCandidate

URL_PATTERN = re.compile(r"https?://[^\s\"'`)\\<>]+")
REQUIRE_PATTERN = re.compile(r"""\brequire\(\s*["']([^"']+)["']\s*\)""")
IMPORT_PATTERN = re.compile(
    r"""\b(?:import|export)\b[^"';]*?\bfrom\s*["']([^"']+)["']|\bimport\s*["']([^"']+)["']"""
)
ROUTE_PATTERN = re.compile(r"""\bpath\s*:\s*["'](/[^"']*)["']""")
IPC_PATTERN = re.compile(
    r"""\bipc(?:Main|Renderer)\.(handle|handleOnce|on|once|invoke|send)\(\s*["']([^"']+)["']"""
)
STORAGE_PATTERN = re.compile(r"""new\s+(?:Database|sqlite3\.Database)\(\s*["']([^"']+)["']""")


def _is_package(specifier: str) -> bool:
    return not specifier.startswith((".", "/", "node:")) and "://" not in specifier


def _safe_url(url: str) -> str | None:
    """The URL without credentials, query and fragment (it may carry keys or tokens)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if not parts.hostname:
        return None
    return f"{parts.scheme}://{parts.hostname}{':' + str(parts.port) if parts.port else ''}{parts.path}"


class _Result:
    def __init__(self, own_host: str | None) -> None:
        self.own_host = (own_host or "").lower()
        self.packages: set[str] = set()
        self.routes: set[str] = set()
        self.ipc: dict[str, set[str]] = defaultdict(set)
        self.storage: set[str] = set()
        self.urls: dict[str, set[str]] = defaultdict(set)

    def add_url(self, raw: str) -> None:
        safe = _safe_url(raw)
        if not safe:
            return
        host = (urlsplit(raw).hostname or "").lower()
        self.urls[host].add(safe)

    def technologies(self) -> list[TechnologyCandidate]:
        found = [
            TechnologyCandidate(p, "package", context={"observed_via": "js_bundle"})
            for p in sorted(self.packages)
        ]
        found += [TechnologyCandidate(r, "route") for r in sorted(self.routes)]
        found += [
            TechnologyCandidate(c, "ipc_channel", context={"operations": sorted(ops)})
            for c, ops in sorted(self.ipc.items())
        ]
        found += [
            TechnologyCandidate(s, "storage", context={"engine": "sqlite"})
            for s in sorted(self.storage)
        ]
        found += [
            TechnologyCandidate(url, "endpoint", context={"host": host})
            for host, urls in sorted(self.urls.items())
            for url in sorted(urls)
        ]
        return found

    def recipients(self) -> list[RecipientCandidate]:
        return [
            RecipientCandidate(
                host=host, context={"observed_via": ["js_bundle"], "urls": sorted(urls)[:5]}
            )
            for host, urls in sorted(self.urls.items())
            if host and host != self.own_host
        ]


def extract_fallback(
    source: str, own_host: str | None = None
) -> tuple[list[TechnologyCandidate], list[RecipientCandidate]]:
    result = _Result(own_host)
    for match in REQUIRE_PATTERN.finditer(source):
        if _is_package(match.group(1)):
            result.packages.add(match.group(1))
    for match in IMPORT_PATTERN.finditer(source):
        specifier = match.group(1) or match.group(2)
        if specifier and _is_package(specifier):
            result.packages.add(specifier)
    result.routes.update(m.group(1) for m in ROUTE_PATTERN.finditer(source))
    for match in IPC_PATTERN.finditer(source):
        result.ipc[match.group(2)].add(match.group(1))
    result.storage.update(m.group(1) for m in STORAGE_PATTERN.finditer(source))
    for match in URL_PATTERN.finditer(source):
        result.add_url(match.group(0).rstrip(".,;"))
    return result.technologies(), result.recipients()


def extract_rea(
    output: dict[str, Any], own_host: str | None = None
) -> tuple[list[TechnologyCandidate], list[RecipientCandidate]]:
    result = _Result(own_host)
    normalized = output["normalized_result"]
    for node in normalized["graph"]["nodes"]:
        for observation in node["observations"]:
            props = observation.get("properties", {})
            kind = node["kind"]
            if kind == "javascript-module":
                specifier = props.get("declared_specifier") or props.get("specifier")
                if specifier and _is_package(specifier):
                    result.packages.add(specifier)
            elif kind == "endpoint" and props.get("endpoint_kind") == "route":
                result.routes.add(props["value"])
            elif kind == "ipc-channel" and props.get("channel"):
                result.ipc[props["channel"]].add(
                    f"{props.get('side', '?')}:{props.get('operation', '?')}"
                )
            elif kind == "storage" and props.get("storage_kind") == "sqlite" and props.get("name"):
                result.storage.add(props["name"])
    for node in normalized.get("semantic_graph", {}).get("nodes", []):
        if node["kind"] == "literal":
            value = node.get("properties", {}).get("value")
            if isinstance(value, str):
                for match in URL_PATTERN.finditer(value):
                    result.add_url(match.group(0).rstrip(".,;"))
    return result.technologies(), result.recipients()
