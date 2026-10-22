from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import Select, case, func, select

from app.api.deps import Principal, app_settings, require_role, write_audit
from app.api.schemas import LlmPingOut, LlmProviderState, LlmUsageOut, LlmUsageRow
from app.api.tenancy import get_tenant_db
from app.core.config import Settings
from app.db.enums import LlmCallStatus, Role
from app.db.models import LlmCall, Organization
from app.db.session import TenantSession
from app.llm.budget import start_of_day, tokens_used_today
from app.llm.router import LLMRouter, ping_provider

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])

READERS = (Role.ADMIN, Role.ANALYST, Role.VIEWER)
KNOWN_PROVIDERS = ("groq", "gemini")


def get_router(request: Request) -> LLMRouter:
    llm: LLMRouter = request.app.state.llm_router
    return llm


def _rows(db: TenantSession, column: object) -> list[LlmUsageRow]:
    stmt: Select[Any] = (
        select(
            column,  # type: ignore[call-overload]
            func.count(),
            func.coalesce(func.sum(LlmCall.tokens_in), 0),
            func.coalesce(func.sum(LlmCall.tokens_out), 0),
            func.coalesce(func.sum(LlmCall.cached_tokens), 0),
            func.coalesce(func.sum(case((LlmCall.status != LlmCallStatus.OK, 1), else_=0)), 0),
        )
        .where(LlmCall.created_at >= start_of_day())
        .group_by(column)
        .order_by(column)
    )
    return [
        LlmUsageRow(
            key=str(key), calls=int(n), tokens_in=int(i), tokens_out=int(o),
            cached_tokens=int(c), errors=int(e),
        )  # fmt: skip
        for key, n, i, o, c, e in db.execute(stmt)
    ]


@router.get("/usage", response_model=LlmUsageOut)
def usage(
    principal: Principal = Depends(require_role(*READERS)),
    db: TenantSession = Depends(get_tenant_db),
    llm: LLMRouter = Depends(get_router),
    defaults: Settings = Depends(app_settings),
) -> LlmUsageOut:
    """Today's calls and tokens (UTC day) with the cache hit count and the provider states."""
    today = LlmCall.created_at >= start_of_day()
    calls, hits, failed = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(case((LlmCall.cache_hit, 1), else_=0)), 0),
            func.coalesce(
                func.sum(
                    case(
                        (
                            LlmCall.status.in_(
                                [
                                    LlmCallStatus.ERROR,
                                    LlmCallStatus.RATE_LIMITED,
                                    LlmCallStatus.SCHEMA_FAILURE,
                                ]
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        ).where(today)
    ).one()
    org = db.get(Organization, principal.org_id)
    budget = int(
        ((org.settings if org else None) or {}).get("daily_token_budget_org")
        or llm.policy.org_daily
    )
    providers = [
        LlmProviderState(
            provider=name,
            model=llm.providers[name].model if name in llm.providers else "",
            configured=name in llm.providers,
            circuit=llm.breakers[name].state if name in llm.providers else "not configured",
        )
        for name in KNOWN_PROVIDERS
    ]
    return LlmUsageOut(
        day=start_of_day().date().isoformat(),
        calls=int(calls),
        cache_hits=int(hits),
        failed_attempts=int(failed),
        tokens_used=tokens_used_today(db),
        org_daily_budget=budget,
        by_provider=_rows(db, LlmCall.provider),
        by_task=_rows(db, LlmCall.task),
        providers=providers,
    )


@router.post("/test-connection", response_model=list[LlmPingOut])
def test_connection(
    request: Request,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
    llm: LLMRouter = Depends(get_router),
) -> list[LlmPingOut]:
    """Send one tiny request to every configured provider (about 100 tokens in total)."""
    results = [
        ping_provider(llm, name, org_id=principal.org_id, user_id=principal.user_id)
        for name in KNOWN_PROVIDERS
        if name in llm.providers
    ]
    write_audit(
        db, request, "llm.test_connection", principal=principal, entity_type="organization",
        entity_id=principal.org_id, details={r.provider: r.ok for r in results},
    )  # fmt: skip
    db.commit()
    return [LlmPingOut(**r.__dict__) for r in results]
