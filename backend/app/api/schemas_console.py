"""Request and response models added for the console: the team, organization switching."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import Role


class OrganizationChoice(BaseModel):
    org_id: uuid.UUID
    name: str
    role: Role
    current: bool


class SwitchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_id: uuid.UUID


class TeamMemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: Role
    is_active: bool
    last_login_at: datetime | None
    is_you: bool


class TeamRoleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role = Field(description="The new role of the member in this organization")
