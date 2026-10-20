"""Network capture (HAR) extraction.

Both extractors reduce a capture to a list of HAR entries and share `extract_entries`:
the REA path reads the records of `inspect-web-network-capture`, the fallback path reads the
file with the standard library. REA keeps request and response in the HAR entry shape, so the
same code serves both.

Facts: submitted field names (form and JSON keys, query parameters), response fields of the
system's own endpoints, cookies it sets, and the outbound hosts.
"""

import json
from collections import defaultdict
from typing import Any
from urllib.parse import urlsplit

from app.discovery.candidates import ElementCandidate, RecipientCandidate
from app.discovery.patterns import dominant_pattern, masked_samples

MAX_SAMPLES = 20


def entry_host(entry: dict[str, Any]) -> str:
    return (urlsplit(entry["request"]["url"]).hostname or "").lower()


def first_host(entries: list[dict[str, Any]]) -> str | None:
    """The host of the first request is the system's own (its page or API)."""
    return entry_host(entries[0]) if entries else None


def flatten_json(value: Any, prefix: str = "") -> dict[str, list[Any]]:
    """Leaf values of a JSON document keyed by dotted path; list items share their parent's path."""
    leaves: dict[str, list[Any]] = defaultdict(list)

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, inner in node.items():
                walk(inner, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for inner in node:
                walk(inner, path)
        elif path:
            leaves[path].append(node)

    walk(value, prefix)
    return leaves


def _json_type(values: list[Any]) -> str:
    kinds = {
        (
            "boolean"
            if isinstance(v, bool)
            else (
                "integer"
                if isinstance(v, int)
                else (
                    "number" if isinstance(v, float) else "string" if isinstance(v, str) else "null"
                )
            )
        )
        for v in values
    }
    kinds.discard("null")
    return kinds.pop() if len(kinds) == 1 else ("mixed" if kinds else "null")


class _Collector:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
        self.counts: dict[tuple[str, str, str], int] = defaultdict(int)
        self.cookies: dict[tuple[str, str], dict[str, Any]] = {}

    def add(self, kind: str, name: str, where: str, values: list[Any]) -> None:
        key = (kind, name, where)
        self.counts[key] += 1
        bucket = self.values[key]
        for value in values:
            if len(bucket) < MAX_SAMPLES:
                bucket.append(value)


def _body_values(request: dict[str, Any]) -> tuple[str, dict[str, list[Any]]]:
    """Returns ("form"|"json"|"", name -> values) for the request body."""
    post = request.get("postData")
    if not post:
        return "", {}
    mime = (post.get("mimeType") or "").lower()
    params = post.get("params")
    if params:
        grouped: dict[str, list[Any]] = defaultdict(list)
        for param in params:
            grouped[param["name"]].append(param.get("value"))
        return "form", dict(grouped)
    text = post.get("text")
    if text and "json" in mime:
        try:
            return "json", dict(flatten_json(json.loads(text)))
        except ValueError:
            return "", {}
    return "", {}


def extract_entries(
    entries: list[dict[str, Any]], own_host: str | None = None
) -> tuple[list[ElementCandidate], list[RecipientCandidate], str | None]:
    own = own_host or first_host(entries)
    collector = _Collector()
    hosts: dict[str, dict[str, Any]] = {}

    for entry in entries:
        request, response = entry["request"], entry.get("response", {})
        url = urlsplit(request["url"])
        host = (url.hostname or "").lower()
        method = request.get("method", "GET")
        where = f"{method} {host}{url.path or '/'}"
        third_party = host != own

        if third_party:
            info = hosts.setdefault(
                host,
                {
                    "methods": set(),
                    "requests": 0,
                    "parameters": set(),
                    "paths": [],
                    "schemes": set(),
                    "content_types": set(),
                },
            )
            info["methods"].add(method)
            info["requests"] += 1
            info["schemes"].add(url.scheme)
            if (url.path or "/") not in info["paths"] and len(info["paths"]) < 5:
                info["paths"].append(url.path or "/")

        for param in request.get("queryString", []):
            kind = "third_party_param" if third_party else "request_query_param"
            collector.add(kind, param["name"], where, [param.get("value")])
            if third_party:
                hosts[host]["parameters"].add(param["name"])

        body_kind, body = _body_values(request)
        for name, values in body.items():
            if third_party:
                kind = "third_party_param"
                hosts[host]["parameters"].add(name)
            else:
                kind = "request_json_key" if body_kind == "json" else "request_form_param"
            collector.add(kind, name, where, values)

        content = response.get("content", {})
        mime = (content.get("mimeType") or "").lower()
        if not third_party and "json" in mime and content.get("text"):
            try:
                for name, values in flatten_json(json.loads(content["text"])).items():
                    collector.add("response_json_key", name, where, values)
            except ValueError:
                pass

        if not third_party:
            for cookie in response.get("cookies", []):
                collector.cookies.setdefault(
                    (host, cookie["name"]),
                    {"http_only": cookie.get("httpOnly"), "secure": cookie.get("secure"),
                     "same_site": cookie.get("sameSite"), "max_age": cookie.get("maxAge")},
                )  # fmt: skip

    elements: list[ElementCandidate] = []
    for (kind, name, where), values in sorted(collector.values.items()):
        pattern, observed = dominant_pattern(values)
        elements.append(
            ElementCandidate(
                name=name,
                path=f"request:{where}" if kind != "response_json_key" else f"response:{where}",
                location_kind=kind,
                data_type=(
                    _json_type(values)
                    if kind == "request_json_key" or kind == "response_json_key"
                    else "string"
                ),
                pattern_class=pattern,
                context={
                    "endpoint": where,
                    "observations": collector.counts[(kind, name, where)],
                    "values_seen": observed,
                    "masked_samples": masked_samples(values),
                },
            )
        )
    for (host, name), attrs in sorted(collector.cookies.items()):
        elements.append(
            ElementCandidate(
                name=name, path=f"cookie:{host}", location_kind="cookie", data_type="string",
                context={"host": host, **attrs},
            )
        )  # fmt: skip

    recipients = [
        RecipientCandidate(
            host=host,
            context={
                "observed_via": ["har"],
                "methods": sorted(info["methods"]),
                "request_count": info["requests"],
                "parameters": sorted(info["parameters"])[:50],
                "sample_paths": info["paths"],
                "schemes": sorted(info["schemes"]),
            },
        )
        for host, info in sorted(hosts.items())
    ]
    return elements, recipients, own


def entries_from_fallback(data: bytes) -> list[dict[str, Any]]:
    document = json.loads(data.decode("utf-8-sig"))
    entries = document["log"]["entries"]
    if not isinstance(entries, list):
        raise ValueError("HAR log.entries must be a list")
    return entries


def entries_from_rea(result: dict[str, Any]) -> list[dict[str, Any]]:
    records = result["normalized_result"]["records"]
    return [record["reported"] for record in records]
