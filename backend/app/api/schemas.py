import re
import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.enums import (
    DocumentType,
    EvidenceKind,
    Extractor,
    JobState,
    RecipientRole,
    ReviewStatus,
    Role,
)


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)
    org_id: uuid.UUID | None = None


class MembershipOut(BaseModel):
    org_id: uuid.UUID
    role: Role


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str


class SessionOut(BaseModel):
    user: UserOut
    org_id: uuid.UUID
    role: Role
    memberships: list[MembershipOut]


class MeOut(BaseModel):
    user: UserOut
    org_id: uuid.UUID
    role: Role


class SystemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    owner_user_id: uuid.UUID | None = None


class SystemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    owner_user_id: uuid.UUID | None = None


class SystemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    owner_user_id: uuid.UUID | None
    status: JobState
    last_discovery_at: datetime | None


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    system_id: uuid.UUID
    kind: EvidenceKind
    filename: str
    checksum_sha256: str
    size_bytes: int
    encrypted: bool
    created_at: datetime


class ObservationUrlIn(BaseModel):
    url: str = Field(max_length=2048)


Provider = Literal["groq", "gemini"]


def _default_providers() -> list[Provider]:
    return ["groq", "gemini"]


class OrgSettings(BaseModel):
    llm_provider_order: list[Provider] = Field(
        default_factory=_default_providers, min_length=1, max_length=2
    )
    daily_token_budget_org: int = Field(default=200_000, ge=1_000, le=10_000_000)
    daily_token_budget_system: int = Field(default=20_000, ge=1_000, le=1_000_000)
    evidence_retention_days: int = Field(default=365, ge=1, le=3650)

    @field_validator("llm_provider_order")
    @classmethod
    def unique_providers(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("providers must be unique")
        return value


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    action: str
    actor_user_id: uuid.UUID | None
    entity_type: str | None
    entity_id: str | None
    details: dict[str, Any]


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:70]
    return slug or "system"


class DiscoveryRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    system_id: uuid.UUID
    state: JobState
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    summary: dict[str, Any] | None


class DataElementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    path: str | None
    data_type: str | None
    pattern_class: str | None
    category: str | None
    special_category: bool
    special_category_label: str | None
    confidence: float | None
    review_status: ReviewStatus
    evidence_id: uuid.UUID | None
    source_kind: str | None
    context: dict[str, Any]


class RecipientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    domain: str
    vendor: str | None
    role: RecipientRole
    country: str | None
    category: str | None
    evidence_id: uuid.UUID | None
    context: dict[str, Any]


class TechnologyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: str | None
    version: str | None
    evidence_id: uuid.UUID
    context: dict[str, Any]


class DiscoveryEvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    evidence_item_id: uuid.UUID | None
    extractor: Extractor
    command: str | None
    rea_version: str | None
    duration_ms: int | None
    status: str
    error: str | None
    raw_sha256: str | None
    raw_truncated: bool
    raw_output: dict[str, Any] | None
    created_at: datetime


class ClassificationSummaryOut(BaseModel):
    elements: int
    classified: int
    unclassified: int
    non_personal: int
    reviewed_kept: int
    special_strong: int
    special_near: int
    recipients: int
    recipients_known: int
    recipients_internal: int
    recipients_unknown: int
    findings_open: int
    methods: dict[str, int]
    thresholds_version: str
    embedding_model: str


class ElementReview(BaseModel):
    """A person's decision on a discovered element."""

    review_status: Literal["accepted", "overridden"]
    category: str | None = Field(default=None, max_length=60)
    special_category: bool | None = None
    not_personal_data: bool = False


class TaxonomyCategoryOut(BaseModel):
    id: str
    label: str
    definition: str
    sensitivity: str
    special_category: bool


KnowledgeSource = Literal["regulation", "document"]
ALL_SOURCES: tuple[KnowledgeSource, ...] = ("regulation", "document")


class KnowledgeSearchIn(BaseModel):
    query: str = Field(min_length=3, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    system_id: uuid.UUID | None = None
    doc_types: list[DocumentType] = Field(default_factory=list, max_length=4)
    articles: list[int] = Field(default_factory=list, max_length=20)
    sources: list[KnowledgeSource] = Field(default_factory=lambda: list(ALL_SOURCES))
    rerank: bool | None = None


class PassageOut(BaseModel):
    id: uuid.UUID
    source: Literal["regulation", "document"]
    citation: str
    label: str
    text: str
    score: float
    signals: dict[str, float | int | None]
    metadata: dict[str, Any]


class KnowledgeSearchOut(BaseModel):
    passages: list[PassageOut]
    reranked: bool
    timings_ms: dict[str, float]


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    system_id: uuid.UUID | None
    evidence_item_id: uuid.UUID | None
    doc_type: DocumentType
    title: str
    source_uri: str | None
    chunks: int = 0
    created_at: datetime


class IngestItemOut(BaseModel):
    document_id: uuid.UUID | None = None
    title: str | None = None
    chunks: int = 0
    status: str
    detail: str | None = None


class LlmUsageRow(BaseModel):
    key: str
    calls: int
    tokens_in: int
    tokens_out: int
    cached_tokens: int
    errors: int


class LlmProviderState(BaseModel):
    provider: str
    model: str
    configured: bool
    circuit: str


class LlmUsageOut(BaseModel):
    day: str
    calls: int
    cache_hits: int
    failed_attempts: int
    tokens_used: int
    org_daily_budget: int
    by_provider: list[LlmUsageRow]
    by_task: list[LlmUsageRow]
    providers: list[LlmProviderState]


class LlmPingOut(BaseModel):
    provider: str
    model: str
    ok: bool
    latency_ms: int | None = None
    error: str | None = None


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    system_id: uuid.UUID | None
    activity_id: uuid.UUID | None
    type: str
    severity: str
    title: str
    description: str | None
    evidence_refs: list[Any]
    suggested_fix: str | None
    status: str
    created_at: datetime


class FindingPatch(BaseModel):
    status: Literal["open", "acknowledged", "resolved", "dismissed"]


class FusionSummaryOut(BaseModel):
    findings_open: int
    by_type: dict[str, int]
    adjudicated: int
    adjudication_pending: int
    tokens_used: int
    status: str


class ActivityOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    current_version: int
    system_ids: list[uuid.UUID]
    owner_user_id: uuid.UUID | None
    purposes: list[str]
    data_subjects: list[str]
    data_categories: list[str]
    recipients: list[Any]
    transfers: list[Any]
    retention: str | None
    security_measures: str | None
    lawful_basis: str | None
    special_category_condition: str | None
    next_review_date: date | None
    citations: dict[str, Any]
    special_categories: list[str]
    missing_fields: list[str]
    summary: str


class ActivityPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purposes: list[str] | None = Field(default=None, max_length=20)
    data_subjects: list[str] | None = Field(default=None, max_length=20)
    data_categories: list[str] | None = Field(default=None, max_length=60)
    lawful_basis: str | None = Field(default=None, max_length=80)
    special_category_condition: str | None = Field(default=None, max_length=200)
    retention: str | None = Field(default=None, max_length=2000)
    security_measures: str | None = Field(default=None, max_length=4000)
    next_review_date: date | None = None


class ActivityGenerateOut(BaseModel):
    activity: ActivityOut
    created: bool
    changed: bool
    suggestion_used: bool
    tokens_used: int


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    change_summary: str | None
    created_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    created_at: datetime


class VersionDetailOut(VersionOut):
    snapshot: dict[str, Any]


class DiffOut(BaseModel):
    from_version: int
    to_version: int
    summary: str
    changes: list[dict[str, Any]]


class DecisionIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class ReviewItemOut(BaseModel):
    kind: Literal["approval", "finding", "incomplete"]
    title: str
    severity: str
    activity_id: uuid.UUID | None = None
    finding_id: uuid.UUID | None = None
    system_id: uuid.UUID | None = None
    since: datetime | None = None
    detail: str | None = None


CriterionId = Literal[
    "evaluation_scoring",
    "automated_decisions",
    "systematic_monitoring",
    "sensitive_data",
    "large_scale",
    "combining_datasets",
    "vulnerable_subjects",
    "innovative_technology",
    "prevents_exercise_of_rights",
]


class ScaleIn(BaseModel):
    """What the evidence cannot show: the number of people, the countries, and criteria an analyst
    knows to apply."""

    model_config = ConfigDict(extra="forbid")

    data_subjects_estimate: int | None = Field(default=None, ge=0, le=2_000_000_000)
    countries: int | None = Field(default=None, ge=0, le=250)
    flags: list[CriterionId] = Field(default_factory=list, max_length=9)


class CriterionOut(BaseModel):
    id: str
    label: str
    met: bool | None
    basis: str
    refs: list[Any]
    needs: str | None = None


class ScreeningOut(BaseModel):
    activity_id: uuid.UUID
    activity_name: str
    criteria: list[CriterionOut]
    criteria_met: int
    criteria_unknown: int
    threshold: int
    required: bool
    undecided: bool
    inputs: dict[str, Any]
    criteria_version: int
    screened_at: datetime


class RiskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    likelihood: int = Field(ge=1, le=5)
    severity: int = Field(ge=1, le=5)
    mitigation: str | None = Field(default=None, max_length=2000)
    residual_likelihood: int | None = Field(default=None, ge=1, le=5)
    residual_severity: int | None = Field(default=None, ge=1, le=5)
    citation: str | None = Field(default=None, max_length=200)


class RiskPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=3, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    likelihood: int | None = Field(default=None, ge=1, le=5)
    severity: int | None = Field(default=None, ge=1, le=5)
    mitigation: str | None = Field(default=None, max_length=2000)
    residual_likelihood: int | None = Field(default=None, ge=1, le=5)
    residual_severity: int | None = Field(default=None, ge=1, le=5)
    citation: str | None = Field(default=None, max_length=200)


class RiskOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    likelihood: int
    severity: int
    inherent_level: str
    mitigation: str | None
    residual_likelihood: int | None
    residual_severity: int | None
    residual_level: str | None
    citation: str | None


class DpiaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=1000)


class DpiaPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, max_length=6000)
    necessity_proportionality: str | None = Field(default=None, max_length=6000)
    officer_opinion: str | None = Field(default=None, max_length=4000)


class DpiaOut(BaseModel):
    id: uuid.UUID
    activity_id: uuid.UUID
    activity_name: str
    status: str
    criteria_met: int
    description: str | None
    necessity_proportionality: str | None
    residual_risk: str | None
    officer_opinion: str | None
    risks: list[RiskOut]
    matrix: dict[str, list[list[int]]]
    missing_fields: list[str]
    drafting: dict[str, Any]
    screening: dict[str, Any]
    created_at: datetime


class DpiaSummaryOut(BaseModel):
    id: uuid.UUID
    activity_id: uuid.UUID
    activity_name: str
    status: str
    criteria_met: int
    residual_risk: str | None
    risks: int
    created_at: datetime
