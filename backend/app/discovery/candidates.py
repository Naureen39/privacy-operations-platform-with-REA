"""Value types produced by the extractors. Candidates carry names, locations and masked
shapes only; they never carry sample values."""

from dataclasses import dataclass, field
from typing import Any

from app.db.enums import EvidenceKind, Extractor

# Where a data element was found. The estate ground truth uses the same names.
LOCATION_KINDS = (
    "form_field",
    "request_json_key",
    "request_form_param",
    "request_query_param",
    "third_party_param",
    "response_json_key",
    "cookie",
    "db_column",
)


@dataclass
class ElementCandidate:
    name: str
    path: str
    location_kind: str
    data_type: str | None = None
    pattern_class: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecipientCandidate:
    host: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class TechnologyCandidate:
    name: str
    kind: str  # package | route | ipc_channel | endpoint
    version: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class Extraction:
    """The result of one extractor run on one evidence item."""

    evidence_kind: EvidenceKind
    extractor: Extractor
    command: str
    rea_version: str | None = None
    duration_ms: int = 0
    status: str = "ok"  # ok | error
    error: str | None = None
    raw_output: dict[str, Any] | None = None
    raw_sha256: str | None = None
    raw_truncated: bool = False
    elements: list[ElementCandidate] = field(default_factory=list)
    recipients: list[RecipientCandidate] = field(default_factory=list)
    technologies: list[TechnologyCandidate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
