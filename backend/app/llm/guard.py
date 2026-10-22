"""What may be sent to a model. Metadata only: names, types, category labels and short retrieved
passages. Sample values and personal identifiers are masked or refused before the request is built.

Masking is deliberately blunt. A policy passage may contain a contact address or a phone number; it
is replaced by a placeholder, which loses nothing the model needs."""

import re
from dataclasses import dataclass
from typing import Any

from app.llm.errors import PayloadRejectedError

FORBIDDEN_KEYS = frozenset(
    {
        "sample",
        "samples",
        "sample_value",
        "sample_values",
        "value",
        "values",
        "raw",
        "raw_value",
        "row",
        "rows",
        "subject_identifier",
        "identifier",
        "subject_hash",
        "email",
        "password",
    }
)
MAX_DEPTH = 6
MAX_STRING = 1200

_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    ("hash", re.compile(r"\b[0-9a-fA-F]{32,}\b"), "[hash]"),
    (
        "iban",
        re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,4})?\b"),
        "[iban]",
    ),
    ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[ip]"),
    ("number", re.compile(r"(?<![\w.])\+?\d[\d ()./-]{7,}\d(?![\w])"), "[number]"),
)
# Kept as they are: ISO dates (a review date is a fact) and UUIDs (the passage ids a model must cite).
_KEEP = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)
_DATE_MARK = re.compile(r"zzdate(\d+)zz")
_FENCE = re.compile(r"</?\s*data\s*>", re.IGNORECASE)


@dataclass
class Sanitized:
    payload: Any
    redactions: dict[str, int]


def sanitize(payload: Any) -> Sanitized:
    """Return a copy with identifiers masked. Raises PayloadRejectedError for forbidden keys."""
    counts: dict[str, int] = {}

    def clean_string(text: str) -> str:
        text = _FENCE.sub("", text)
        dates: list[str] = []  # review dates and passage ids are not identifiers of a person

        def keep_date(match: re.Match[str]) -> str:
            dates.append(match.group(0))
            return f"zzdate{len(dates) - 1}zz"

        text = _KEEP.sub(keep_date, text)
        for name, pattern, placeholder in _PATTERNS:
            text, n = pattern.subn(placeholder, text)
            if n:
                counts[name] = counts.get(name, 0) + n
        text = _DATE_MARK.sub(lambda m: dates[int(m.group(1))], text)
        return text[:MAX_STRING]

    def walk(node: Any, path: str, depth: int) -> Any:
        if depth > MAX_DEPTH:
            raise PayloadRejectedError(f"payload nested too deeply at {path}")
        if isinstance(node, dict):
            out: dict[str, Any] = {}
            for key, value in node.items():
                if not isinstance(key, str):
                    raise PayloadRejectedError(f"non-string key at {path}")
                if key.lower() in FORBIDDEN_KEYS:
                    raise PayloadRejectedError(
                        f"field '{key}' must not be sent to a model ({path})"
                    )
                out[clean_string(key)] = walk(value, f"{path}.{key}", depth + 1)
            return out
        if isinstance(node, (list, tuple)):
            return [walk(v, f"{path}[]", depth + 1) for v in node]
        if isinstance(node, str):
            return clean_string(node)
        if node is None or isinstance(node, (bool, int, float)):
            return node
        raise PayloadRejectedError(f"unsupported value of type {type(node).__name__} at {path}")

    return Sanitized(walk(payload, "payload", 0), counts)
