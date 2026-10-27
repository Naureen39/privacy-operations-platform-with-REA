import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select

from app.api.deps import ALL_ROLES, Principal, app_settings, require_role, write_audit
from app.api.pagination import Page, page_params, paged
from app.api.schemas_billing import (
    InvoiceLineOut,
    InvoiceOut,
    InvoiceRunIn,
    InvoiceRunOut,
    InvoiceSummaryOut,
    PlanOut,
    SubscriptionIn,
    SubscriptionOut,
    UsageOut,
)
from app.api.tenancy import get_tenant_db
from app.billing import pricing, service, usage
from app.core.config import Settings
from app.db.enums import Role
from app.db.models import Invoice, InvoiceLine, Plan, Subscription, System
from app.db.session import TenantSession
from app.services.pipeline import today_of

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

SIMULATED_NOTE = (
    "Billing is simulated: there is no payment processor and the figures are for demonstration."
)


def _fail(error: service.BillingError) -> HTTPException:
    return HTTPException(error.status_code, str(error))


def _subscription_out(db: TenantSession, sub: Subscription) -> SubscriptionOut:
    plan = db.get(Plan, sub.plan_id)
    assert plan is not None  # noqa: S101
    return SubscriptionOut(
        id=sub.id, plan=plan.code, plan_name=plan.name, status=sub.status.value,
        base_fee_cents=sub.base_fee_cents, started_at=sub.started_at, ended_at=sub.ended_at,
        is_simulated=sub.is_simulated,
    )  # fmt: skip


def _invoice_out(db: TenantSession, invoice: Invoice) -> InvoiceOut:
    lines = db.scalars(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id).order_by(InvoiceLine.kind)
    )
    return InvoiceOut(
        id=invoice.id, number=invoice.number, period_start=invoice.period_start,
        period_end=invoice.period_end, status=invoice.status.value,
        total_cents=invoice.total_cents, paid_at=invoice.paid_at, is_simulated=invoice.is_simulated,
        lines=[
            InvoiceLineOut(
                kind=line.kind.value, description=line.description, quantity=line.quantity,
                unit_cents=line.unit_cents, amount_cents=line.amount_cents,
            )
            for line in lines
        ],
    )  # fmt: skip


def _load_invoice(db: TenantSession, invoice_id: uuid.UUID) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    return invoice


@router.get("/plans", response_model=list[PlanOut])
def list_plans(
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[PlanOut]:
    """The price list."""
    plans = db.scalars(
        select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.monthly_fee_cents)
    )
    return [
        PlanOut(
            code=p.code, name=p.name, monthly_fee_cents=p.monthly_fee_cents,
            included_systems=p.included_systems, included_requests=p.included_requests,
            extra_system_cents=p.extra_system_cents, extra_request_cents=p.extra_request_cents,
        )
        for p in plans
    ]  # fmt: skip


@router.get("/subscription", response_model=SubscriptionOut)
def get_subscription(
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> SubscriptionOut:
    sub = service.active_subscription(db, today_of(settings))
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no active subscription")
    return _subscription_out(db, sub)


@router.put("/subscription", response_model=SubscriptionOut)
def change_subscription(
    request: Request,
    body: SubscriptionIn,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> SubscriptionOut:
    """Start a plan or move to another one; the change takes effect today."""
    try:
        sub = service.subscribe(db, body.plan, today_of(settings))
    except service.BillingError as exc:
        raise _fail(exc) from exc
    write_audit(
        db, request, "billing.subscription", principal=principal, entity_type="subscription",
        entity_id=sub.id, details={"plan": body.plan},
    )  # fmt: skip
    db.commit()
    return _subscription_out(db, sub)


@router.get("/usage", response_model=UsageOut)
def get_usage(
    month: str | None = None,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> UsageOut:
    """What the organisation used in a month (the current one by default) and what that would cost
    on its plan. The count of systems is live for a month that has not ended."""
    today = today_of(settings)
    try:
        start, end = pricing.parse_month(month) if month else (today.replace(day=1), today)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Use the form YYYY-MM") from exc
    measured = usage.usage_in_period(db, start, end)
    complete = end < today
    if not complete:
        measured.active_systems = int(db.scalar(select(func.count()).select_from(System)) or 0)
    sub = service.active_subscription(db, min(end, today))
    plan = db.get(Plan, sub.plan_id) if sub else None
    projected = None
    if sub and plan:
        projected = pricing.total_cents(
            pricing.price_invoice(
                service.terms_of(plan), sub.base_fee_cents, measured.active_systems,
                measured.requests, f"{start:%B %Y}",
            )
        )  # fmt: skip
    return UsageOut(
        period_start=start, period_end=end, complete=complete, plan=plan.code if plan else None,
        active_systems=measured.active_systems, requests=measured.requests,
        assessments=measured.assessments, tokens=measured.tokens,
        tokens_by_provider=measured.tokens_by_provider,
        included_systems=plan.included_systems if plan else None,
        included_requests=plan.included_requests if plan else None,
        projected_cents=projected, note=SIMULATED_NOTE,
    )  # fmt: skip


@router.get("/invoices", response_model=list[InvoiceSummaryOut])
def list_invoices(
    response: Response,
    status_filter: str | None = None,
    page: Page = Depends(page_params),
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[InvoiceSummaryOut]:
    query = select(Invoice).order_by(Invoice.period_start.desc())
    if status_filter:
        query = query.where(Invoice.status == status_filter)
    return [
        InvoiceSummaryOut(
            id=i.id, number=i.number, period_start=i.period_start, period_end=i.period_end,
            status=i.status.value, total_cents=i.total_cents, is_simulated=i.is_simulated,
        )
        for i in paged(db, query, page, response)
    ]  # fmt: skip


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
def get_invoice(
    invoice_id: uuid.UUID,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
) -> InvoiceOut:
    return _invoice_out(db, _load_invoice(db, invoice_id))


@router.post("/invoice-run", response_model=InvoiceRunOut)
def invoice_run(
    request: Request,
    body: InvoiceRunIn,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> InvoiceRunOut:
    """Invoice a finished month (the previous one by default). Running it twice returns the same
    invoice."""
    today = today_of(settings)
    start, end = pricing.parse_month(body.month) if body.month else pricing.previous_month(today)
    try:
        result = service.run_invoice(db, start, end, today)
    except service.BillingError as exc:
        raise _fail(exc) from exc
    if result.created and result.invoice is not None:
        write_audit(
            db, request, "billing.invoice", principal=principal, entity_type="invoice",
            entity_id=result.invoice.id, details={"month": f"{start:%Y-%m}"},
        )  # fmt: skip
    db.commit()
    return InvoiceRunOut(
        created=result.created, reason=result.reason,
        invoice=_invoice_out(db, result.invoice) if result.invoice else None,
    )  # fmt: skip


@router.post("/invoices/{invoice_id}/pay", response_model=InvoiceOut)
def pay_invoice(
    request: Request,
    invoice_id: uuid.UUID,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
) -> InvoiceOut:
    """Mark an invoice paid. There is no payment processor; this records the payment."""
    invoice = _load_invoice(db, invoice_id)
    try:
        service.mark_paid(invoice)
    except service.BillingError as exc:
        raise _fail(exc) from exc
    write_audit(
        db, request, "billing.pay", principal=principal, entity_type="invoice",
        entity_id=invoice.id,
    )  # fmt: skip
    db.commit()
    return _invoice_out(db, invoice)
