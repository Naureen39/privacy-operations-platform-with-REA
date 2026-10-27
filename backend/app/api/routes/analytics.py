"""Metrics endpoints. Platform figures (revenue, usage) are for the administrators of the host
organisation only; compliance figures belong to the caller's organisation (row level security)."""

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import inspect, select

from app.analytics import series
from app.analytics.cache import Cache, cache_key
from app.analytics.csvout import to_csv
from app.api.deps import Principal, app_settings, require_role
from app.api.tenancy import get_tenant_db
from app.core.config import Settings
from app.db.enums import Role
from app.db.models import ComplianceDailyMetric, DailyMetric
from app.db.session import TenantSession
from app.services.pipeline import today_of

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

SIMULATED_NOTE = (
    "Revenue and usage figures are simulated for the demonstration: there are no real customers."
)

REVENUE = series.Spec(
    flow=(
        "new_mrr_cents", "expansion_mrr_cents", "contraction_mrr_cents", "churned_mrr_cents",
        "usage_revenue_cents",
    ),
    stock=("mrr_cents", "accounts", "paying_accounts", "arpa_cents", "nrr_bp", "gross_churn_bp"),
)  # fmt: skip
PLATFORM = series.Spec(
    flow=("requests", "failovers", "cache_hits"),
    stock=("accounts", "systems"),
    json_sum=("tokens_by_provider",),
)
COMPLIANCE = series.Spec(
    stock=(
        "approved_records", "stale_records", "requests_open", "requests_overdue",
        "discovery_confidence_avg", "rea_run_duration_ms_avg",
    ),
    json_last=("open_findings", "assessments_by_status"),
)  # fmt: skip

ANALYSTS = (Role.ADMIN, Role.ANALYST, Role.VIEWER)


class Window:
    """The validated query parameters shared by every metrics endpoint."""

    def __init__(
        self,
        request: Request,
        start: date | None = Query(None, description="First day (default: 90 days to the end)"),
        end: date | None = Query(None, description="Last day (default: today)"),
        granularity: series.Granularity = Query("day"),
        compare: bool = Query(False, description="Also return the previous period of equal length"),
        format: str = Query("json", pattern="^(json|csv)$"),  # noqa: A002
        settings: Settings = Depends(app_settings),
    ) -> None:
        self.end = end or today_of(settings)
        self.start = start or self.end - timedelta(days=89)
        try:
            series.check_range(self.start, self.end)
        except series.RangeError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        self.granularity: series.Granularity = granularity
        self.compare = compare
        self.format = format
        self.cache: Cache = request.app.state.cache

    def params(self) -> dict[str, Any]:
        return {
            "start": self.start, "end": self.end, "granularity": self.granularity,
            "compare": self.compare, "format": self.format,
        }  # fmt: skip


def host_admin(
    principal: Principal = Depends(require_role(Role.ADMIN)),
    settings: Settings = Depends(app_settings),
) -> Principal:
    """Platform figures cover every customer, so only the host organisation's administrators see them."""
    if settings.leads_org_id is None or principal.org_id != settings.leads_org_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    return principal


def _as_dict(row: Any) -> dict[str, Any]:
    return {c.key: getattr(row, c.key) for c in inspect(type(row)).column_attrs}


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _flat(value: Any) -> Any:
    return json.dumps(_jsonable(value), sort_keys=True) if isinstance(value, dict) else value


def _csv(spec: series.Spec, points: list[dict[str, Any]]) -> str:
    names = ("period", "last_day", "days", *spec.flow, *spec.stock, *spec.json_sum, *spec.json_last)
    return to_csv(names, [[_flat(_jsonable(p.get(n))) for n in names] for p in points])


def _build(
    rows: list[dict[str, Any]],
    previous_rows: list[dict[str, Any]] | None,
    spec: series.Spec,
    window: Window,
    simulated: bool,
    note: str,
) -> dict[str, Any]:
    points = series.aggregate(rows, spec, window.granularity)
    current = series.totals(rows, spec)
    body: dict[str, Any] = {
        "start": window.start, "end": window.end, "granularity": window.granularity,
        "simulated": simulated, "series": points, "totals": current, "previous": None,
        "change": None, "note": note,
    }  # fmt: skip
    if previous_rows is not None:
        before = series.totals(previous_rows, spec)
        body["previous"] = before
        body["change"] = series.change(current, before)
    return body


def _respond(
    response: Response,
    window: Window,
    scope: str,
    endpoint: str,
    spec: series.Spec,
    produce: Any,
) -> Any:
    """Serve from the 60 second cache when the same question was asked recently."""
    key = cache_key(window.cache, scope, endpoint, window.params())
    hit = window.cache.get(key)
    if hit is None:
        body = _jsonable(produce())
        hit = json.dumps(body).encode()
        window.cache.set(key, hit)
        response.headers["X-Cache"] = "miss"
    else:
        body = json.loads(hit)
        response.headers["X-Cache"] = "hit"
    if window.format == "csv":
        text = _csv(spec, body["series"])
        return Response(
            text,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{endpoint}.csv"',
                "X-Cache": response.headers["X-Cache"],
            },
        )
    return body


def _platform_rows(db: TenantSession, start: date, end: date) -> list[dict[str, Any]]:
    stmt = (
        select(DailyMetric)
        .where(DailyMetric.metric_date >= start, DailyMetric.metric_date <= end)
        .order_by(DailyMetric.metric_date)
    )
    return [_as_dict(r) for r in db.scalars(stmt)]


def _platform(db: TenantSession, window: Window, spec: series.Spec) -> dict[str, Any]:
    rows = _platform_rows(db, window.start, window.end)
    previous = None
    if window.compare:
        p_start, p_end = series.previous_period(window.start, window.end)
        previous = _platform_rows(db, p_start, p_end)
    simulated = any(r["is_simulated"] for r in rows) if rows else True
    return _build(rows, previous, spec, window, simulated, SIMULATED_NOTE)


@router.get("/revenue")
def revenue(
    response: Response,
    window: Window = Depends(),
    principal: Principal = Depends(host_admin),
    db: TenantSession = Depends(get_tenant_db),
) -> Any:
    """MRR and its movements (new, expansion, contraction, churn), usage revenue, accounts, ARPA,
    net revenue retention and gross churn, by day, week or month."""
    return _respond(
        response, window, "platform", "revenue", REVENUE, lambda: _platform(db, window, REVENUE)
    )


@router.get("/platform")
def platform_usage(
    response: Response,
    window: Window = Depends(),
    principal: Principal = Depends(host_admin),
    db: TenantSession = Depends(get_tenant_db),
) -> Any:
    """Usage across the platform: accounts, systems, requests, tokens by provider, failovers and
    cache hits."""
    return _respond(
        response, window, "platform", "platform", PLATFORM, lambda: _platform(db, window, PLATFORM)
    )


def _compliance_rows(db: TenantSession, start: date, end: date) -> list[dict[str, Any]]:
    stmt = (
        select(ComplianceDailyMetric)
        .where(ComplianceDailyMetric.metric_date >= start, ComplianceDailyMetric.metric_date <= end)
        .order_by(ComplianceDailyMetric.metric_date)
    )
    return [_as_dict(r) for r in db.scalars(stmt)]


@router.get("/compliance")
def compliance(
    response: Response,
    window: Window = Depends(),
    principal: Principal = Depends(require_role(*ANALYSTS)),
    db: TenantSession = Depends(get_tenant_db),
) -> Any:
    """The organisation's own figures: approved and stale records, open findings by severity and
    type, assessments by status, requests open and overdue, discovery confidence, REA run time."""

    def produce() -> dict[str, Any]:
        rows = _compliance_rows(db, window.start, window.end)
        previous = None
        if window.compare:
            p_start, p_end = series.previous_period(window.start, window.end)
            previous = _compliance_rows(db, p_start, p_end)
        simulated = any(r["is_simulated"] for r in rows)
        note = "Includes simulated history." if simulated else ""
        return _build(rows, previous, COMPLIANCE, window, simulated, note)

    return _respond(response, window, str(principal.org_id), "compliance", COMPLIANCE, produce)


@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
def refresh(
    request: Request,
    principal: Principal = Depends(host_admin),
    settings: Settings = Depends(app_settings),
) -> dict[str, str]:
    """Rebuild the latest snapshots now instead of waiting for the nightly job."""
    from app.workers.tasks import analytics_nightly

    try:
        if settings.celery_eager:
            analytics_nightly.apply(args=[])
        else:
            analytics_nightly.delay()
    except Exception as exc:  # the broker is unreachable
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The job queue is not available"
        ) from exc
    request.app.state.cache.bump()
    return {"status": "queued"}
