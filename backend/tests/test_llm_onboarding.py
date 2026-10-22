"""Phase 7 acceptance on the reference estate: a first onboarding of a system stays under 4,000
tokens, a repeated onboarding with unchanged evidence uses zero tokens, and changed evidence asks
only about what changed.

The provider is scripted; its token counts are the router's own (deliberately high) estimate of
the request and the answer, so the figures are an upper bound for real tokenizers."""

import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.db.session import TenantContext, TenantSession, set_tenant
from app.knowledge.chunking import chunk_document
from app.knowledge.retrieval import Passage
from app.llm.budget import JobBudget, tokens_used_today
from app.llm.router import LLMRouter, ProviderLimits
from app.llm.tasks import Scope, adjudicate_conflict, suggest_purpose_and_basis
from app.services import provisioning
from tests.llm_support import FakeClock, TaskAwareProvider

ESTATE = Path(__file__).resolve().parents[2] / "datasets" / "estate"
SYSTEM_IDS = sorted(p.name for p in ESTATE.iterdir() if (p / "ground_truth.json").exists())
BUDGET = 4000


def facts(system_id: str) -> dict[str, Any]:
    truth = json.loads((ESTATE / system_id / "ground_truth.json").read_text(encoding="utf-8"))
    answers = json.loads((ESTATE / system_id / "questionnaire.json").read_text(encoding="utf-8"))[
        "answers"
    ]
    policy = (ESTATE / system_id / "policy.md").read_bytes()
    _, chunks = chunk_document("policy.md", policy)
    passages = [
        Passage(
            uuid.uuid5(uuid.NAMESPACE_URL, f"{system_id}/{c.index}"), "document", f"doc:{system_id}#{c.index}",
            c.heading or "", c.text, 0.0,
        )
        for c in chunks
    ]  # fmt: skip
    return {
        "name": truth["system_name"],
        "categories": sorted({e["category"] for e in truth["data_elements"]}),
        "special": sorted({e["category"] for e in truth["data_elements"] if e["special_category"]}),
        "subjects": answers.get("data_subjects", []),
        "recipients": [
            {"vendor": r["vendor"], "role": r["role"], "country": r["country"]}
            for r in truth["recipients"]
            if not r["internal"]
        ],
        "purposes": answers.get("purposes", []),
        "passages": passages,
        "retention": truth["retention"]["policy"],
    }


def onboard(
    router: LLMRouter, org_id: uuid.UUID, system_uuid: uuid.UUID, system_id: str
) -> JobBudget:
    """What Phase 8 will do for one system: one purpose and basis call, and the two conflicts that
    rules cannot settle, each with the top 3 policy passages."""
    f = facts(system_id)
    job = JobBudget(BUDGET)
    scope = Scope(org_id, system_id=system_uuid, job=job)
    suggest_purpose_and_basis(
        router, scope, name=f["name"], description="", data_categories=f["categories"],
        special_categories=f["special"], data_subjects=f["subjects"], recipients=f["recipients"],
        declared_purposes=f["purposes"],
    )  # fmt: skip
    for statement in (f"Retention: {f['retention']}", "Recipients are listed in the notice"):
        adjudicate_conflict(
            router, scope, conflict_type="statement_check", statement=statement,
            detail="questionnaire and notice may differ", passages=f["passages"][:3],
        )  # fmt: skip
    return job


@pytest.fixture
def setup(
    owner_engine: Engine, session_factory: sessionmaker[TenantSession]
) -> Iterator[
    tuple[
        LLMRouter, TaskAwareProvider, uuid.UUID, dict[str, uuid.UUID], sessionmaker[TenantSession]
    ]
]:
    org_id = provisioning.create_organization(owner_engine, "Onboard", f"ob-{uuid.uuid4().hex[:8]}")
    from app.db.models import System

    ids: dict[str, uuid.UUID] = {}
    with session_factory() as db:
        set_tenant(db, TenantContext(org_id=org_id))
        for sid in SYSTEM_IDS:
            system = System(org_id=org_id, name=sid, slug=sid.replace("_", "-"))
            db.add(system)
            db.flush()
            ids[sid] = system.id
        db.commit()
    provider = TaskAwareProvider()
    clock = FakeClock()
    router = LLMRouter(
        {"groq": provider}, lambda: session_factory, clock=clock, sleep=clock.sleep,
        limits={"groq": ProviderLimits(10_000_000, 10_000)},
    )  # fmt: skip
    yield router, provider, org_id, ids, session_factory


def test_a_first_onboarding_stays_under_4000_tokens(setup: Any) -> None:
    router, provider, org_id, ids, _ = setup
    used = {}
    for sid in SYSTEM_IDS:
        before = len(provider.requests)
        job = onboard(router, org_id, ids[sid], sid)
        used[sid] = job.used
        assert len(provider.requests) - before == 3  # 1 purpose call + 2 conflicts
        assert 0 < job.used < BUDGET, (sid, job.used)
    print("\n[tokens] first onboarding per system:", used, "max", max(used.values()))
    assert len(SYSTEM_IDS) == 8


def test_a_repeated_onboarding_with_unchanged_evidence_uses_zero_tokens(setup: Any) -> None:
    router, provider, org_id, ids, factory = setup
    first = {sid: onboard(router, org_id, ids[sid], sid).used for sid in SYSTEM_IDS}
    calls_after_first = len(provider.requests)
    with factory() as db:
        set_tenant(db, TenantContext(org_id=org_id))
        spent = tokens_used_today(db)
    assert spent == sum(first.values())

    for sid in SYSTEM_IDS:
        job = onboard(router, org_id, ids[sid], sid)
        assert job.used == 0, sid
    assert len(provider.requests) == calls_after_first  # not one provider call
    with factory() as db:
        set_tenant(db, TenantContext(org_id=org_id))
        assert tokens_used_today(db) == spent


def test_changed_evidence_asks_only_about_what_changed(setup: Any) -> None:
    router, provider, org_id, ids, _ = setup
    sid = "web_shop"
    onboard(router, org_id, ids[sid], sid)
    base = len(provider.requests)

    f = facts(sid)
    scope = Scope(org_id, system_id=ids[sid])
    suggest_purpose_and_basis(  # a new recipient was discovered
        router, scope, name=f["name"], description="", data_categories=f["categories"],
        special_categories=f["special"], data_subjects=f["subjects"],
        recipients=[*f["recipients"], {"vendor": "NewAds", "role": "controller", "country": "US"}],
        declared_purposes=f["purposes"],
    )  # fmt: skip
    adjudicate_conflict(  # unchanged conflict: free
        router, scope, conflict_type="statement_check", statement=f"Retention: {f['retention']}",
        detail="questionnaire and notice may differ", passages=f["passages"][:3],
    )  # fmt: skip
    assert len(provider.requests) - base == 1
