"""Request and response models for billing and analytics."""

import re
import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class PlanOut(BaseModel):
    code: str
    name: str
    monthly_fee_cents: int
    included_systems: int
    included_requests: int
    extra_system_cents: int
    extra_request_cents: int


class SubscriptionOut(BaseModel):
    id: uuid.UUID
    plan: str
    plan_name: str
    status: str
    base_fee_cents: int
    started_at: date
    ended_at: date | None
    is_simulated: bool


class SubscriptionIn(BaseModel):
    plan: str = Field(min_length=1, max_length=40)


class InvoiceLineOut(BaseModel):
    kind: str
    description: str
    quantity: int
    unit_cents: int
    amount_cents: int


class InvoiceOut(BaseModel):
    id: uuid.UUID
    number: str
    period_start: date
    period_end: date
    status: str
    total_cents: int
    paid_at: datetime | None
    is_simulated: bool
    lines: list[InvoiceLineOut]


class InvoiceSummaryOut(BaseModel):
    id: uuid.UUID
    number: str
    period_start: date
    period_end: date
    status: str
    total_cents: int
    is_simulated: bool


class InvoiceRunIn(BaseModel):
    month: str | None = Field(default=None, description="YYYY-MM; the previous month if omitted")

    @field_validator("month")
    @classmethod
    def _month(cls, value: str | None) -> str | None:
        if value is not None and not MONTH.match(value):
            raise ValueError("Use the form YYYY-MM")
        return value


class InvoiceRunOut(BaseModel):
    created: bool
    reason: str
    invoice: InvoiceOut | None


class UsageOut(BaseModel):
    period_start: date
    period_end: date
    complete: bool
    plan: str | None
    active_systems: int
    requests: int
    assessments: int
    tokens: int
    tokens_by_provider: dict[str, int]
    included_systems: int | None
    included_requests: int | None
    projected_cents: int | None
    note: str


class SeriesOut(BaseModel):
    start: date
    end: date
    granularity: str
    simulated: bool
    series: list[dict[str, Any]]
    totals: dict[str, Any]
    previous: dict[str, Any] | None
    change: dict[str, Any] | None
    note: str
