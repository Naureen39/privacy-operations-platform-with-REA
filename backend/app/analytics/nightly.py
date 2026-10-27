"""The nightly job and the monthly invoice run, as plain functions over an owner engine (which can
list every organisation) and the application's session factory (which acts as one organisation at a
time, so row level security still applies to everything written for a tenant)."""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.analytics import compliance, daily
from app.billing import pricing, service
from app.db.session import TenantContext, TenantSession, tenant_session


@dataclass
class NightlySummary:
    organisations: int
    days: int
    metric_rows: int


@dataclass
class InvoiceRunSummary:
    organisations: int
    created: int
    skipped: int
    settled: int


def organisations(owner: Engine) -> list[uuid.UUID]:
    with owner.connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT id FROM organizations ORDER BY id"))]


def run_nightly(
    owner: Engine, factory: sessionmaker[TenantSession], today: date, days: int = 3
) -> NightlySummary:
    """Refresh the compliance snapshot of every organisation and the platform snapshot for the last
    `days` days (a few days, so a late event is picked up)."""
    window = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    orgs = organisations(owner)
    for org_id in orgs:
        with tenant_session(factory, TenantContext(org_id=org_id)) as db:
            for day in window:
                compliance.store(db, day)
    rows = daily.rebuild(owner, window[0], window[-1])
    return NightlySummary(len(orgs), len(window), rows)


def run_invoices(
    owner: Engine, factory: sessionmaker[TenantSession], today: date
) -> InvoiceRunSummary:
    """Invoice the month that just ended for every organisation, then apply the stand-in payment
    outcome to older open invoices."""
    start, end = pricing.previous_month(today)
    orgs = organisations(owner)
    created = skipped = settled = 0
    for org_id in orgs:
        with tenant_session(factory, TenantContext(org_id=org_id)) as db:
            result = service.run_invoice(db, start, end, today)
            created += int(result.created)
            skipped += int(not result.created)
            settled += service.settle_simulated(db, today)
    return InvoiceRunSummary(len(orgs), created, skipped, settled)
