"""Turn extractor output into the form that is stored.

The raw output of an extractor is kept so that every fact can be traced to it, but sample values
from the evidence are not: values are replaced with shape masks (letters become x, digits 9) and
bodies that are not JSON are dropped. The SHA-256 of the unmasked output is stored next to it, so
the stored record can still be tied to the exact result it was derived from.
"""

import copy
import hashlib
import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.discovery.patterns import mask_shape

RAW_SIZE_CAP = 8 * 1024 * 1024
JS_TRIM_THRESHOLD = 2 * 1024 * 1024


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_of(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def strip_query_values(url: str) -> str:
    """Keep parameter names, drop their values (they can hold identifiers and tokens)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "[malformed url]"
    if not parts.query:
        return url.split("#", 1)[0]
    names = [pair.split("=", 1)[0] for pair in parts.query.split("&") if pair]
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc.split("@")[-1],
            parts.path,
            "&".join(f"{n}=" for n in names),
            "",
        )
    )


def mask_json_leaves(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: mask_json_leaves(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_json_leaves(v) for v in value]
    if isinstance(value, bool) or value is None:
        return value
    return mask_shape(value)


def _mask_text_body(text: str | None, mime: str) -> str | None:
    if text is None:
        return None
    if "json" in mime.lower():
        try:
            return canonical_json(mask_json_leaves(json.loads(text)))
        except ValueError:
            pass
    return f"[omitted {len(text.encode('utf-8'))} bytes]"


def mask_har_entry(entry: dict[str, Any]) -> dict[str, Any]:
    masked = copy.deepcopy(entry)
    request = masked.get("request", {})
    request["url"] = strip_query_values(request.get("url", ""))
    for param in request.get("queryString", []):
        param["value"] = mask_shape(param.get("value")) if param.get("value") is not None else None
    post = request.get("postData")
    if post:
        for param in post.get("params", []) or []:
            param["value"] = (
                mask_shape(param.get("value")) if param.get("value") is not None else None
            )
        post["text"] = _mask_text_body(post.get("text"), post.get("mimeType", ""))
    for header in request.get("headers", []):
        name = header["name"].lower()
        if name in {"cookie", "authorization", "proxy-authorization"}:
            header["value"] = None
        elif name in {"referer", "origin"} and header.get("value"):
            header["value"] = strip_query_values(header["value"])
    for cookie in request.get("cookies", []):
        cookie["value"] = None
    response = masked.get("response", {})
    content = response.get("content", {})
    if "text" in content:
        content["text"] = _mask_text_body(content.get("text"), content.get("mimeType", ""))
    for header in response.get("headers", []):
        name = header["name"].lower()
        if name in {"set-cookie", "authorization"}:
            header["value"] = None
        elif name == "location" and header.get("value"):
            header["value"] = strip_query_values(header["value"])
    for cookie in response.get("cookies", []):
        cookie["value"] = None
    return masked


def mask_har_rea(output: dict[str, Any]) -> dict[str, Any]:
    masked = copy.deepcopy(output)
    for record in masked.get("normalized_result", {}).get("records", []):
        record["reported"] = mask_har_entry(record["reported"])
        record["binary_fields"] = {"count": len(record.get("binary_fields", []))}
        record["numeric_literals"] = {"count": len(record.get("numeric_literals", []))}
    return masked


def mask_har_fallback(
    entries: list[dict[str, Any]], creator: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "parser": "json",
        "log": {"creator": creator, "entries": [mask_har_entry(e) for e in entries]},
    }


def mask_sqlite_rea(output: dict[str, Any]) -> dict[str, Any]:
    masked = copy.deepcopy(output)
    for sample in masked.get("samples", {}).values():
        rows = (sample or {}).get("rows") or {}
        for row in rows.get("values", []):
            for cell in row:
                cell.pop("bytes_hex", None)
                if "value" in cell:
                    cell["value"] = mask_shape(cell["value"])
    return masked


def mask_sqlite_fallback(tables: list[Any]) -> dict[str, Any]:
    return {
        "parser": "sqlite3",
        "tables": [
            {
                "name": t.name,
                "columns": [
                    {
                        "name": c.name,
                        "declared_type": c.declared_type,
                        "primary_key": c.primary_key,
                        "not_null": c.not_null,
                    }
                    for c in t.columns
                ],
                "sampled_rows": len(t.sample_rows),
            }
            for t in tables
        ],
    }


def trim_js_rea(output: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """The semantic graph of a real bundle is huge. Keep what the facts were derived from."""
    if len(canonical_json(output)) <= JS_TRIM_THRESHOLD:
        return output, False
    trimmed = copy.deepcopy(output)
    graph = trimmed["normalized_result"].get("semantic_graph", {})
    graph["nodes"] = [n for n in graph.get("nodes", []) if n.get("kind") == "literal"]
    for key in ("relations", "fingerprints", "unknowns", "evidence_contexts"):
        graph.pop(key, None)
    return trimmed, True


def finalize_raw(raw: dict[str, Any], truncated: bool = False) -> tuple[dict[str, Any], bool]:
    """Enforce the storage cap. An oversized record keeps its identity and counts only."""
    size = len(canonical_json(raw))
    if size <= RAW_SIZE_CAP:
        return raw, truncated
    summary = {
        key: (len(value) if isinstance(value, (list, dict)) else value)
        for key, value in raw.items()
    }
    return {"truncated": True, "size_bytes": size, "summary": summary}, True
