"""Token budgets: a cap per request, a budget per job (for example one system onboarding), and
daily budgets per system and per organisation, counted from the call log."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import LlmCall


@dataclass(frozen=True)
class BudgetPolicy:
    request_cap: int = 5000
    org_daily: int = 200_000
    system_daily: int = 20_000


class JobBudget:
    """Tokens one job (an onboarding, an assessment, a chat answer) may spend in total."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def consume(self, tokens: int) -> None:
        self.used += tokens


def start_of_day() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def tokens_used_today(db: Session, system_id: uuid.UUID | None = None) -> int:
    """Tokens in and out of every logged call today (UTC). Row Level Security limits the sum to
    the organisation of the session."""
    stmt = select(func.coalesce(func.sum(LlmCall.tokens_in + LlmCall.tokens_out), 0)).where(
        LlmCall.created_at >= start_of_day()
    )
    if system_id is not None:
        stmt = stmt.where(LlmCall.system_id == system_id)
    return int(db.scalar(stmt) or 0)
