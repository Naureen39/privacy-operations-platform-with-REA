import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.enums import EvidenceKind, JobState, Role


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
