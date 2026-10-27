import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from slowapi import Limiter
from sqlalchemy import func, select

from app.api.deps import Principal, app_settings, require_role, write_audit
from app.api.pagination import Page, page_params, paged
from app.api.schemas import (
    ChatIn,
    ChatOut,
    LeadIn,
    LeadOut,
    PassageOut,
    PublicMetricsOut,
    VendorOut,
)
from app.api.schemas_billing import PlanOut
from app.api.tenancy import get_tenant_db
from app.core.config import Settings
from app.db.enums import FindingStatus, LeadKind, Role
from app.db.models import (
    DailyMetric,
    Finding,
    Lead,
    Plan,
    Recipient,
    RegulationChunk,
    System,
)
from app.db.session import TenantContext, TenantSession, tenant_session
from app.fusion.facts import slug
from app.knowledge.retrieval import Filters, HybridRetriever, Passage
from app.llm.budget import JobBudget
from app.llm.errors import BudgetExceededError, LLMError
from app.llm.router import LLMRouter
from app.llm.tasks import Scope, answer_question

router = APIRouter(prefix="/api/v1", tags=["platform"])

READERS = (Role.ADMIN, Role.ANALYST, Role.VIEWER, Role.SYSTEM_OWNER)
MIN_SIMILARITY = 0.55  # below this a passage is not about the question
GAP_TYPES = ("third_country_no_safeguard", "missing_agreement", "undeclared_recipient")


# -- vendors -----------------------------------------------------------------------------------


@router.get("/vendors", response_model=list[VendorOut])
def list_vendors(
    response: Response,
    page: Page = Depends(page_params),
    principal: Principal = Depends(require_role(*READERS)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[VendorOut]:
    """Recipients across the systems you can see, one entry per vendor, with the systems that use
    it and the open gaps found for it (transfer safeguard, agreement, declaration)."""
    systems = {s.id: s for s in db.scalars(select(System))}
    if principal.role is Role.SYSTEM_OWNER:
        systems = {i: s for i, s in systems.items() if s.owner_user_id == principal.user_id}
    vendors: dict[str, dict[str, Any]] = {}
    for r in db.scalars(select(Recipient).order_by(Recipient.domain)):
        if r.system_id not in systems or (r.context or {}).get("internal"):
            continue
        key = slug(r.vendor or r.domain)
        entry = vendors.setdefault(
            key,
            {
                "key": key,
                "name": r.vendor or r.domain,
                "role": r.role.value,
                "country": r.country,
                "category": r.category,
                "domains": set(),
                "systems": {},
                "gaps": set(),
            },
        )
        entry["domains"].add(r.domain)
        entry["systems"][r.system_id] = {"id": str(r.system_id), "name": systems[r.system_id].name}
    for f in db.scalars(
        select(Finding).where(
            Finding.status.in_([FindingStatus.OPEN, FindingStatus.ACKNOWLEDGED]),
            Finding.type.in_(GAP_TYPES),
        )
    ):
        subject = (f.dedupe_key or "").split(":", 3)[-1]
        if subject in vendors and f.system_id in vendors[subject]["systems"]:
            vendors[subject]["gaps"].add(f.type)
    ordered = sorted(vendors.values(), key=lambda v: str(v["name"]).lower())
    response.headers["X-Total-Count"] = str(len(ordered))
    return [
        VendorOut(
            key=v["key"], name=v["name"], role=v["role"], country=v["country"], category=v["category"],
            domains=sorted(v["domains"]), systems=sorted(v["systems"].values(), key=lambda s: s["name"]),
            open_findings=sorted(v["gaps"]),
        )
        for v in ordered[page.offset : page.offset + page.limit]
    ]  # fmt: skip


# -- chat --------------------------------------------------------------------------------------


def _passage_out(p: Passage) -> PassageOut:
    return PassageOut(
        id=p.id,
        source=p.source,
        citation=p.citation,
        label=p.label,
        text=p.text,
        score=p.score,
        signals=p.signals,
        metadata=p.metadata,
    )


@router.post("/chat", response_model=ChatOut)
def chat(
    request: Request,
    body: ChatIn,
    principal: Principal = Depends(require_role(*READERS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> ChatOut:
    """Answer a question from the GDPR and the organisation's own documents, with the passages the
    answer relies on. If nothing relevant is found the answer says so, and no model is called. At
    most 3,000 tokens per answer."""
    filters = Filters(
        system_id=body.system_id,
        owner_user_id=principal.user_id if principal.role is Role.SYSTEM_OWNER else None,
    )
    if body.system_id is not None:
        from app.api.deps import get_visible_system

        get_visible_system(db, principal, body.system_id)
    if not db.scalar(select(func.count()).select_from(RegulationChunk).limit(1)):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The knowledge base is empty (run scripts/ingest_regulation.py)",
        )
    retriever = HybridRetriever(db, request.app.state.embedder)
    found = retriever.search(body.question, top_k=5, filters=filters, rerank=False).passages
    relevant = [
        p
        for p in found
        if p.signals.get("fulltext_rank")
        or (p.signals.get("vector_similarity") or 0) >= MIN_SIMILARITY
    ]
    llm: LLMRouter = request.app.state.llm_router
    tokens = 0
    if not relevant:
        answer, call = answer_question(
            llm, Scope(principal.org_id, principal.user_id), question=body.question, passages=[]
        )
        cited: list[Passage] = []
    elif not llm.providers:
        return ChatOut(
            answer="The assistant is not configured, so no answer was written. These are the most relevant passages.",
            supported=False, citations=[_passage_out(p) for p in relevant], retrieved=len(found), tokens_used=0,
        )  # fmt: skip
    else:
        scope = Scope(principal.org_id, principal.user_id, body.system_id, job=JobBudget(3000))
        try:
            answer, call = answer_question(llm, scope, question=body.question, passages=relevant)
        except BudgetExceededError as exc:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
        except LLMError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "The assistant is not available right now; try again shortly",
            ) from exc
        by_id = {str(p.id): p for p in relevant}
        cited = [by_id[i] for i in answer.cited_passage_ids if i in by_id]
        tokens = call.tokens if call else 0
    write_audit(
        db,
        request,
        "chat.ask",
        principal=principal,
        details={
            "retrieved": len(found),
            "relevant": len(relevant),
            "supported": answer.supported,
            "tokens": tokens,
        },
    )
    db.commit()
    return ChatOut(
        answer=answer.answer,
        supported=answer.supported,
        citations=[_passage_out(p) for p in cited],
        retrieved=len(found),
        tokens_used=tokens,
    )


# -- leads and public figures ------------------------------------------------------------------


@router.get("/leads", response_model=list[LeadOut])
def list_leads(
    response: Response,
    page: Page = Depends(page_params),
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[Lead]:
    """Contact and demo requests from the public site (the host organisation's admins only)."""
    return paged(db, select(Lead).order_by(Lead.created_at.desc()), page, response)


def build_public_router(limiter: Limiter, settings: Settings) -> APIRouter:
    public = APIRouter(prefix="/api/v1/public", tags=["public"])

    @public.post("/leads", status_code=status.HTTP_202_ACCEPTED, response_model=dict[str, str])
    @limiter.limit(settings.lead_rate_limit)
    def create_lead(request: Request, body: LeadIn) -> dict[str, str]:
        """Contact or demo request from the public site. No sign in; rate limited; the hidden
        `website` field catches bots (the request is accepted and dropped)."""
        if body.website:
            return {"status": "accepted"}
        org_id = settings.leads_org_id
        if org_id is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Requests are not being accepted right now"
            )
        with tenant_session(request.app.state.session_factory, TenantContext(org_id=org_id)) as db:
            db.add(
                Lead(
                    kind=LeadKind(body.kind),
                    name=body.name.strip(),
                    email=body.email.strip().lower(),
                    company=body.company,
                    message=body.message,
                )
            )
        return {"status": "accepted"}

    @public.get("/metrics", response_model=PublicMetricsOut)
    @limiter.limit(settings.default_rate_limit)
    def public_metrics(request: Request) -> PublicMetricsOut:
        """Headline figures for the public site: the latest platform snapshot (simulated for the
        demonstration) and the size of the regulation text."""
        with request.app.state.session_factory() as db:
            latest = db.scalars(
                select(DailyMetric).order_by(DailyMetric.metric_date.desc()).limit(1)
            ).first()
            passages = db.scalar(select(func.count()).select_from(RegulationChunk)) or 0
        return PublicMetricsOut(
            as_of=latest.metric_date if latest else None,
            accounts=latest.accounts if latest else 0, systems=latest.systems if latest else 0,
            requests=latest.requests if latest else 0, cache_hits=latest.cache_hits if latest else 0,
            failovers=latest.failovers if latest else 0, regulation_passages=int(passages),
            simulated=True if latest is None else latest.is_simulated,
            note="Figures marked simulated are generated for the demonstration; there are no real customers.",
        )  # fmt: skip

    @public.get("/plans", response_model=list[PlanOut])
    @limiter.limit(settings.default_rate_limit)
    def public_plans(request: Request) -> list[PlanOut]:
        """The price list for the pricing page. Prices are illustrative; billing is simulated."""
        with request.app.state.session_factory() as db:
            plans = db.scalars(
                select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.monthly_fee_cents)
            )
            return [
                PlanOut(
                    code=p.code, name=p.name, monthly_fee_cents=p.monthly_fee_cents,
                    included_systems=p.included_systems, included_requests=p.included_requests,
                    extra_system_cents=p.extra_system_cents,
                    extra_request_cents=p.extra_request_cents,
                )
                for p in plans
            ]  # fmt: skip

    return public


__all__ = ["build_public_router", "router", "uuid"]
