"""Usage metering: events for requests and assessments as they happen, active systems at the end of
a month, and tokens summed from the call log. All of it is written inside the organisation's own
tenant session."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.enums import LlmCallStatus, UsageKind
from app.db.models import LlmCall, System, UsageEvent


def event_time(reference: date | None) -> datetime | None:
    """When an event happens: now, or the same time of day on the configured reference date (a
    demonstration or test that pins the calendar)."""
    if reference is None:
        return None
    return datetime.combine(reference, datetime.now(UTC).time(), tzinfo=UTC)


def record_usage(
    db: Session,
    kind: UsageKind,
    quantity: int = 1,
    *,
    system_id: uuid.UUID | None = None,
    provider: str | None = None,
    at: datetime | None = None,
    simulated: bool = False,
) -> UsageEvent:
    event = UsageEvent(
        kind=kind,
        quantity=quantity,
        occurred_at=at or datetime.now(UTC),
        system_id=system_id,
        provider=provider,
        is_simulated=simulated,
    )
    db.add(event)
    db.flush()
    return event


def day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def day_end(day: date) -> datetime:
    return day_start(day + timedelta(days=1))


def snapshot_active_systems(db: Session, day: date, simulated: bool = False) -> int:
    """The number of systems at the end of `day`, recorded once per day (asking again replaces it)."""
    count = int(
        db.scalar(select(func.count()).select_from(System).where(System.created_at < day_end(day)))
        or 0
    )
    db.execute(
        delete(UsageEvent).where(
            UsageEvent.kind == UsageKind.ACTIVE_SYSTEMS,
            UsageEvent.occurred_at >= day_start(day),
            UsageEvent.occurred_at < day_end(day),
        )
    )
    record_usage(
        db,
        UsageKind.ACTIVE_SYSTEMS,
        count,
        at=day_end(day) - timedelta(seconds=1),
        simulated=simulated,
    )
    return count


def aggregate_tokens(db: Session, start: date, end: date) -> dict[str, int]:
    """Tokens in and out per provider for a period, written as one usage event per provider at the
    end of the period. Running it again replaces the events, so the numbers never double."""
    rows = db.execute(
        select(LlmCall.provider, func.coalesce(func.sum(LlmCall.tokens_in + LlmCall.tokens_out), 0))
        .where(
            LlmCall.created_at >= day_start(start),
            LlmCall.created_at < day_end(end),
            LlmCall.status == LlmCallStatus.OK,
            LlmCall.cache_hit.is_(False),
        )
        .group_by(LlmCall.provider)
    ).all()
    stamp = day_end(end) - timedelta(seconds=1)
    db.execute(
        delete(UsageEvent).where(
            UsageEvent.kind == UsageKind.TOKENS_USED,
            UsageEvent.occurred_at == stamp,
            UsageEvent.is_simulated.is_(False),
        )
    )
    totals = {provider: int(total) for provider, total in rows if total}
    for provider, total in totals.items():
        record_usage(db, UsageKind.TOKENS_USED, total, provider=provider, at=stamp)
    return totals


@dataclass
class PeriodUsage:
    active_systems: int = 0
    requests: int = 0
    assessments: int = 0
    tokens: int = 0
    tokens_by_provider: dict[str, int] = field(default_factory=dict)


def usage_in_period(db: Session, start: date, end: date) -> PeriodUsage:
    """Active systems = the latest snapshot in the period; the other kinds are summed."""
    window = (UsageEvent.occurred_at >= day_start(start), UsageEvent.occurred_at < day_end(end))
    usage = PeriodUsage()
    latest = db.scalars(
        select(UsageEvent)
        .where(UsageEvent.kind == UsageKind.ACTIVE_SYSTEMS, *window)
        .order_by(UsageEvent.occurred_at.desc())
        .limit(1)
    ).first()
    usage.active_systems = int(latest.quantity) if latest else 0
    for kind, provider, total in db.execute(
        select(UsageEvent.kind, UsageEvent.provider, func.sum(UsageEvent.quantity))
        .where(UsageEvent.kind != UsageKind.ACTIVE_SYSTEMS, *window)
        .group_by(UsageEvent.kind, UsageEvent.provider)
    ):
        if kind is UsageKind.REQUESTS_PROCESSED:
            usage.requests += int(total)
        elif kind is UsageKind.ASSESSMENTS_GENERATED:
            usage.assessments += int(total)
        elif kind is UsageKind.TOKENS_USED:
            usage.tokens += int(total)
            usage.tokens_by_provider[provider or "unknown"] = usage.tokens_by_provider.get(
                provider or "unknown", 0
            ) + int(total)
    return usage
