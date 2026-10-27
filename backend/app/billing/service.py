"""Subscriptions and monthly invoices for one organisation (run inside its tenant session)."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing import pricing, usage
from app.db.enums import InvoiceStatus, SubscriptionStatus
from app.db.models import Invoice, InvoiceLine, Plan, Subscription

OVERDUE_AFTER_DAYS = 30


class BillingError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def terms_of(plan: Plan) -> pricing.PlanTerms:
    return pricing.PlanTerms(
        plan.code, plan.monthly_fee_cents, plan.included_systems, plan.included_requests,
        plan.extra_system_cents, plan.extra_request_cents,
    )  # fmt: skip


def plan_by_code(db: Session, code: str) -> Plan:
    plan = db.scalars(select(Plan).where(Plan.code == code, Plan.is_active.is_(True))).first()
    if plan is None:
        raise BillingError("Unknown plan", 404)
    return plan


def active_subscription(db: Session, on: date) -> Subscription | None:
    """The subscription in force on a day: started on or before it and not yet ended."""
    return db.scalars(
        select(Subscription)
        .where(
            Subscription.started_at <= on,
            (Subscription.ended_at.is_(None)) | (Subscription.ended_at > on),
        )
        .order_by(Subscription.started_at.desc())
    ).first()


def subscribe(db: Session, plan_code: str, on: date, simulated: bool = False) -> Subscription:
    """Start a plan, or change to another one. A change ends the old subscription the same day and
    starts a new row (so the history shows upgrades and downgrades); a change on the day the old one
    started just replaces it."""
    plan = plan_by_code(db, plan_code)
    current = active_subscription(db, on)
    if current is not None:
        if current.plan_id == plan.id:
            raise BillingError("The organisation is already on this plan")
        if current.started_at == on:
            current.plan_id, current.base_fee_cents = plan.id, plan.monthly_fee_cents
            db.flush()
            return current
        current.ended_at = on
        current.status = SubscriptionStatus.CANCELED
    sub = Subscription(
        plan_id=plan.id, base_fee_cents=plan.monthly_fee_cents, started_at=on,
        status=SubscriptionStatus.ACTIVE, is_simulated=simulated,
    )  # fmt: skip
    db.add(sub)
    db.flush()
    return sub


def cancel(db: Session, on: date) -> Subscription:
    current = active_subscription(db, on)
    if current is None:
        raise BillingError("There is no active subscription")
    current.ended_at, current.status = on, SubscriptionStatus.CANCELED
    db.flush()
    return current


@dataclass
class InvoiceResult:
    invoice: Invoice | None
    created: bool
    reason: str = ""


def run_invoice(
    db: Session, period_start: date, period_end: date, today: date, simulated: bool = False
) -> InvoiceResult:
    """Invoice one calendar month for the plan in force on its last day. Running it again returns
    the same invoice. Systems are the count at the end of the month, requests the month's total."""
    if period_end >= today:
        raise BillingError("The month is not over yet")
    existing = db.scalars(
        select(Invoice).where(
            Invoice.period_start == period_start, Invoice.status != InvoiceStatus.VOID
        )
    ).first()
    if existing is not None:
        return InvoiceResult(existing, False)
    sub = active_subscription(db, period_end)
    if sub is None:
        return InvoiceResult(None, False, "no subscription in force at the end of the month")
    plan = db.get(Plan, sub.plan_id)
    assert plan is not None  # noqa: S101
    if not simulated:
        usage.snapshot_active_systems(db, period_end)
        usage.aggregate_tokens(db, period_start, period_end)
    measured = usage.usage_in_period(db, period_start, period_end)
    lines = pricing.price_invoice(
        terms_of(plan),
        sub.base_fee_cents,
        measured.active_systems,
        measured.requests,
        f"{period_start:%B %Y}",
    )
    sequence = (
        int(
            db.scalar(
                select(func.count())
                .select_from(Invoice)
                .where(Invoice.period_start == period_start)
            )
            or 0
        )
        + 1
    )
    invoice = Invoice(
        subscription_id=sub.id, number=pricing.invoice_number(period_start, sequence),
        period_start=period_start, period_end=period_end, status=InvoiceStatus.OPEN,
        total_cents=pricing.total_cents(lines), is_simulated=simulated or sub.is_simulated,
    )  # fmt: skip
    db.add(invoice)
    db.flush()
    db.add_all(
        InvoiceLine(
            invoice_id=invoice.id,
            kind=l.kind,
            description=l.description,
            quantity=l.quantity,
            unit_cents=l.unit_cents,
            amount_cents=l.amount_cents,
        )
        for l in lines  # noqa: E741
    )
    db.flush()
    return InvoiceResult(invoice, True)


def mark_paid(invoice: Invoice, when: datetime | None = None) -> None:
    if invoice.status is InvoiceStatus.VOID:
        raise BillingError("A void invoice cannot be paid")
    if invoice.status is InvoiceStatus.PAID:
        raise BillingError("The invoice is already paid")
    invoice.status, invoice.paid_at = InvoiceStatus.PAID, when or datetime.now(UTC)


def void(invoice: Invoice) -> None:
    if invoice.status is InvoiceStatus.PAID:
        raise BillingError("A paid invoice cannot be voided")
    invoice.status = InvoiceStatus.VOID


def simulated_outcome(
    number: str, period_end: date, today: date
) -> tuple[InvoiceStatus, datetime | None]:
    """A simple, deterministic stand-in for payments: about 90 percent of invoices are paid 3 to 25
    days after the month ends, a few stay unpaid. Used by the seed and the nightly job; there is no
    payment processor."""
    draw = int(hashlib.sha256(number.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    due = period_end + timedelta(days=OVERDUE_AFTER_DAYS)
    if draw < 0.90:
        paid_on = period_end + timedelta(days=3 + int(draw / 0.90 * 22))
        if paid_on <= today:
            return InvoiceStatus.PAID, datetime.combine(paid_on, time(12, 0), tzinfo=UTC)
        return InvoiceStatus.OPEN, None
    if draw < 0.98 and today > due:
        return InvoiceStatus.OVERDUE, None
    if draw >= 0.98 and today > due:
        return InvoiceStatus.VOID, None
    return InvoiceStatus.OPEN, None


def settle_simulated(db: Session, today: date) -> int:
    """Apply the stand-in payment outcome to the invoices still open or overdue."""
    changed = 0
    for invoice in db.scalars(
        select(Invoice).where(Invoice.status.in_([InvoiceStatus.OPEN, InvoiceStatus.OVERDUE]))
    ):
        status, paid_at = simulated_outcome(
            invoice.number + str(invoice.org_id)[:8], invoice.period_end, today
        )
        if status is not invoice.status:
            invoice.status, invoice.paid_at = status, paid_at
            changed += 1
    db.flush()
    return changed
