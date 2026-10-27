"""Two years of simulated billing history for fictional organisations.

`plan_history` decides, month by month, what each organisation does (signs up on an S shaped curve
across the period, picks a plan, adds systems, upgrades when it outgrows its plan, rarely
downgrades, and churns more often on Starter than on Enterprise). `seed_billing_history` then
writes it through the same billing functions the API uses, so the invoices, lines and MRR it
produces obey the real pricing and metric rules. The generator is deterministic for a given seed.
"""

import calendar
import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.analytics import daily
from app.billing import pricing, service, usage
from app.db.enums import UsageKind
from app.db.session import TenantContext, TenantSession, tenant_session

INDUSTRIES = ("Healthcare", "Finance", "Retail", "Technology", "Education")
REGIONS = ("EU", "UK", "North America", "Asia Pacific")
PLAN_MIX = (("starter", 0.55), ("professional", 0.35), ("enterprise", 0.10))
MONTHLY_CHURN = {"starter": 0.045, "professional": 0.02, "enterprise": 0.006}
SYSTEM_GROWTH = {"starter": 0.10, "professional": 0.18, "enterprise": 0.22}
INCLUDED = {"starter": (3, 5), "professional": (25, 50), "enterprise": (150, 500)}
START_SYSTEMS = {"starter": (1, 3), "professional": (6, 22), "enterprise": (60, 130)}
PROVIDERS = (("groq", 0.7), ("gemini", 0.3))
TOKENS_PER_REQUEST = 3200

NAME_FIRST = (
    "Alder", "Birch", "Cedar", "Delta", "Ember", "Fjord", "Garnet", "Harbor", "Iris", "Juniper",
    "Keystone", "Linden", "Meridian", "Northgate", "Orchard", "Pinnacle", "Quarry", "Ridge",
    "Summit", "Tidewater", "Upland", "Vantage", "Willow", "Zephyr",
)  # fmt: skip
NAME_SECOND = (
    "Health", "Capital", "Retail", "Labs", "Learning", "Systems", "Partners", "Group", "Works",
    "Digital", "Holdings", "Services",
)  # fmt: skip


@dataclass
class MonthPlan:
    """What happens to one organisation in one calendar month."""

    month: date  # first day
    plan: str | None  # plan to be on from `change_day` (None: no change)
    change_day: date | None
    churn_day: date | None
    systems: int
    requests: int


@dataclass
class OrgPlan:
    name: str
    slug: str
    industry: str
    region: str
    signup: date
    months: list[MonthPlan] = field(default_factory=list)


def months_between(first: date, last: date) -> list[date]:
    """First days of the months from `first` to `last`, inclusive."""
    out, current = [], first.replace(day=1)
    while current <= last:
        out.append(current)
        current = (current + timedelta(days=32)).replace(day=1)
    return out


def _weighted(rng: random.Random, options: tuple[tuple[str, float], ...]) -> str:
    return rng.choices([o[0] for o in options], weights=[o[1] for o in options])[0]


def signup_months(rng: random.Random, count: int, months: int) -> list[int]:
    """Month numbers drawn from a logistic (S shaped) cumulative curve: few early, then fast, then
    levelling off."""
    midpoint, steepness = months * 0.5, 9.0 / months

    def cdf(m: float) -> float:
        return 1 / (1 + math.exp(-steepness * (m - midpoint)))

    weights = [cdf(m + 1) - cdf(m) for m in range(months)]
    return sorted(rng.choices(range(months), weights=weights, k=count))


def plan_history(rng: random.Random, count: int, first: date, as_of: date) -> list[OrgPlan]:
    """The month by month story of each organisation, up to the month containing `as_of`."""
    months = months_between(first, as_of)
    orgs: list[OrgPlan] = []
    used: set[str] = set()
    for signup_index in signup_months(rng, count, len(months)):
        name = f"{rng.choice(NAME_FIRST)} {rng.choice(NAME_SECOND)}"
        if f"sim-{name.lower().replace(' ', '-')}" in used:
            name = f"{name} {len(used) + 1}"  # the name pool is finite
        slug = "sim-" + name.lower().replace(" ", "-")
        used.add(slug)
        plan = _weighted(rng, PLAN_MIX)
        month0 = months[signup_index]
        last_day = calendar.monthrange(month0.year, month0.month)[1]
        signup = month0.replace(day=rng.randint(1, min(28, last_day)))
        if signup >= as_of:
            signup = month0
        org = OrgPlan(name, slug, rng.choice(INDUSTRIES), rng.choice(REGIONS), signup)
        systems = rng.randint(*START_SYSTEMS[plan])
        for position, month in enumerate(months[signup_index:]):
            change: str | None = plan if position == 0 else None
            change_day = signup if position == 0 else None
            churn_day = None
            if position > 0:
                if rng.random() < MONTHLY_CHURN[plan]:
                    churn_day = month.replace(day=rng.randint(2, 27))
                else:
                    if rng.random() < SYSTEM_GROWTH[plan]:
                        systems += rng.randint(1, 3 if plan != "enterprise" else 8)
                    included = INCLUDED[plan][0]
                    if plan == "starter" and systems > included and rng.random() < 0.4:
                        plan, change = "professional", "professional"
                    elif plan == "professional" and systems > included and rng.random() < 0.3:
                        plan, change = "enterprise", "enterprise"
                    elif plan == "professional" and rng.random() < 0.012:
                        plan, change = "starter", "starter"
                    change_day = month.replace(day=rng.randint(2, 27)) if change else None
            included_requests = INCLUDED[plan][1]
            requests = max(0, round(included_requests * rng.uniform(0.35, 1.25)))
            org.months.append(MonthPlan(month, change, change_day, churn_day, systems, requests))
            if churn_day is not None:
                break
        orgs.append(org)
    return orgs


@dataclass
class SeedSummary:
    organisations: int = 0
    subscriptions: int = 0
    invoices: int = 0
    usage_events: int = 0
    first_day: date | None = None
    last_day: date | None = None
    metric_rows: int = 0
    requests_by_day: dict[date, int] = field(default_factory=dict)


SIMULATED_DELETES = (
    "DELETE FROM invoice_lines WHERE invoice_id IN (SELECT id FROM invoices WHERE org_id IN "
    "(SELECT id FROM organizations WHERE is_simulated))",
    "DELETE FROM invoices WHERE org_id IN (SELECT id FROM organizations WHERE is_simulated)",
    "DELETE FROM usage_events WHERE org_id IN (SELECT id FROM organizations WHERE is_simulated)",
    "DELETE FROM subscriptions WHERE org_id IN (SELECT id FROM organizations WHERE is_simulated)",
    "DELETE FROM compliance_daily_metrics WHERE org_id IN "
    "(SELECT id FROM organizations WHERE is_simulated)",
    "DELETE FROM organizations WHERE is_simulated",
    "DELETE FROM daily_metrics",
)


def reset_simulated(owner: Engine) -> None:
    """Remove earlier simulated billing data (the owner connection is needed: it spans tenants)."""
    with owner.begin() as conn:
        for statement in SIMULATED_DELETES:
            conn.execute(text(statement))


def _create_org(owner: Engine, org: OrgPlan) -> uuid.UUID:
    with owner.begin() as conn:
        found = conn.execute(
            text(
                "INSERT INTO organizations (name, slug, industry, region, is_simulated) "
                "VALUES (:n, :s, :i, :r, true) RETURNING id"
            ),
            {"n": org.name, "s": org.slug, "i": org.industry, "r": org.region},
        ).scalar_one()
    return uuid.UUID(str(found))


def _at(day: date, hour: int = 12) -> datetime:
    return datetime.combine(day, time(hour, 0), tzinfo=UTC)


def _write_usage(
    db: TenantSession, rng: random.Random, month: MonthPlan, as_of: date, summary: SeedSummary
) -> None:
    start, end = month.month, pricing.month_bounds(month.month.year, month.month.month)[1]
    last_active = min(end, as_of - timedelta(days=1))
    if last_active < start:
        return
    # requests spread over a handful of days of the month
    days = sorted(rng.sample(range(start.day, last_active.day + 1), k=min(6, last_active.day)))
    if not days:
        return
    share, remainder = divmod(month.requests, len(days))
    for i, offset in enumerate(days):
        quantity = share + (remainder if i == 0 else 0)
        when = start.replace(day=offset)
        if quantity:
            usage.record_usage(
                db, UsageKind.REQUESTS_PROCESSED, quantity, at=_at(when), simulated=True
            )
            summary.usage_events += 1
            summary.requests_by_day[when] = summary.requests_by_day.get(when, 0) + quantity
    if end < as_of:  # a finished month: its closing system count and token total
        usage.record_usage(
            db,
            UsageKind.ACTIVE_SYSTEMS,
            month.systems,
            at=usage.day_end(end) - timedelta(seconds=1),
            simulated=True,
        )
        stamp = usage.day_end(end) - timedelta(seconds=1)
        total_tokens = month.requests * TOKENS_PER_REQUEST + month.systems * 9000
        for provider, share_of in PROVIDERS:
            usage.record_usage(
                db, UsageKind.TOKENS_USED, round(total_tokens * share_of), provider=provider,
                at=stamp, simulated=True,
            )  # fmt: skip
        summary.usage_events += 1 + len(PROVIDERS)


def seed_billing_history(
    owner: Engine,
    factory: sessionmaker[TenantSession],
    *,
    seed: int = 42,
    organisations: int = 120,
    months: int = 24,
    as_of: date,
    reset: bool = False,
) -> SeedSummary:
    """Write the history and rebuild the platform snapshot over the whole period."""
    if reset:
        reset_simulated(owner)
    with owner.connect() as conn:
        if conn.execute(text("SELECT 1 FROM organizations WHERE is_simulated LIMIT 1")).first():
            raise RuntimeError("Simulated data already exists; run again with reset=True")
    rng = random.Random(seed)
    first_month = as_of.replace(day=1)
    for _ in range(months - 1):
        first_month = (first_month - timedelta(days=1)).replace(day=1)
    plans = plan_history(rng, organisations, first_month, as_of)
    summary = SeedSummary(first_day=first_month, last_day=as_of)
    for org in plans:
        org_id = _create_org(owner, org)
        summary.organisations += 1
        with tenant_session(factory, TenantContext(org_id=org_id)) as db:
            for month in org.months:
                if month.plan and month.change_day and month.change_day <= as_of:
                    service.subscribe(db, month.plan, month.change_day, simulated=True)
                    summary.subscriptions += 1
                if month.churn_day and month.churn_day <= as_of:
                    service.cancel(db, month.churn_day)
                _write_usage(db, rng, month, as_of, summary)
                end = pricing.month_bounds(month.month.year, month.month.month)[1]
                if end < as_of:
                    result = service.run_invoice(db, month.month, end, as_of, simulated=True)
                    summary.invoices += int(result.created)
            service.settle_simulated(db, as_of)
    overlay = _operations_overlay(rng, summary.requests_by_day)
    summary.metric_rows = daily.rebuild(owner, first_month, as_of, overlay)
    return summary


def _operations_overlay(
    rng: random.Random, requests_by_day: dict[date, int]
) -> dict[date, dict[str, int]]:
    """Simulated provider failovers and cache hits, proportional to the day's requests."""
    overlay: dict[date, dict[str, int]] = {}
    for day, requests in sorted(requests_by_day.items()):
        calls = requests * 6
        overlay[day] = {
            "cache_hits": round(calls * rng.uniform(0.15, 0.30)),
            "failovers": round(calls * rng.uniform(0.002, 0.012)),
        }
    return overlay
