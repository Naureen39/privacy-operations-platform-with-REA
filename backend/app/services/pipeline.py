"""The stages of onboarding a system, usable from a request and from a background worker.

Every function takes the shared runtime (`state`: the application state in the API, a `Runtime` in
a worker) and a tenant session, and is idempotent: running a stage again with the same evidence
changes nothing and costs no tokens (the model answers are cached).
"""

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from sqlalchemy import select

from app.classify.embedder import Embedder
from app.classify.engine import Classifier
from app.classify.index import PgMatcher
from app.classify.knowledge import Knowledge
from app.classify.service import ClassificationService
from app.core.config import Settings
from app.db.enums import JobState
from app.db.models import ProcessingActivity, System, TaxonomyEntry
from app.db.session import TenantSession
from app.discovery.executor import Executor
from app.discovery.service import DiscoveryService
from app.dpia.screening import Scale, load_criteria
from app.dpia.service import ScreeningService
from app.fusion.loader import ClassifierCategorizer, FactsLoader
from app.fusion.service import FusionService
from app.llm.budget import JobBudget
from app.llm.errors import LLMError
from app.llm.router import LLMRouter
from app.llm.schemas import PurposeAndBasis
from app.llm.tasks import Scope, suggest_purpose_and_basis
from app.records.builder import build_draft
from app.records.service import ActivityService, GenerateResult
from app.services.evidence_store import EvidenceStore

READY_FOR_RECORD = (
    JobState.FUSED,
    JobState.DRAFTED,
    JobState.AWAITING_REVIEW,
    JobState.APPROVED,
    JobState.PUBLISHED,
)


class State(Protocol):
    """What the stages need. `app.state` and the worker runtime both provide it."""

    settings: Settings
    knowledge: Knowledge
    embedder: Embedder
    evidence_store: EvidenceStore
    discovery_executor: Executor
    llm_router: LLMRouter


class StageError(Exception):
    """A stage cannot run, and running it again will not help (missing evidence, no index)."""


@dataclass
class RecordOutcome:
    result: GenerateResult
    suggestion_used: bool
    tokens: int


def today_of(settings: Settings) -> date:
    return settings.reference_date or date.today()


def make_loader(state: State, db: TenantSession, org_id: uuid.UUID) -> FactsLoader:
    return FactsLoader(
        db,
        state.evidence_store,
        ClassifierCategorizer(Classifier(state.knowledge, state.embedder, PgMatcher(db))),
        org_id,
        today_of(state.settings),
    )


def category_labels(state: State) -> dict[str, str]:
    return {c.id: c.label for c in state.knowledge.categories.values()}


def require_taxonomy(db: TenantSession) -> None:
    if not db.scalar(select(TaxonomyEntry.id).limit(1)):
        raise StageError("The taxonomy index is not loaded (run scripts/load_taxonomy.py)")


# -- stages ------------------------------------------------------------------------------------


def discover(
    db: TenantSession, state: State, system: System, user_id: uuid.UUID | None
) -> dict[str, Any]:
    run = DiscoveryService(db, state.evidence_store, state.discovery_executor).run(system, user_id)
    summary = dict(run.summary or {})
    summary["state"] = run.state.value
    summary["run_id"] = str(run.id)
    return summary


def classify(db: TenantSession, state: State, system: System) -> dict[str, Any]:
    require_taxonomy(db)
    summary = ClassificationService(
        db, Classifier(state.knowledge, state.embedder, PgMatcher(db)), state.knowledge
    ).run(system)
    return dataclasses.asdict(summary)


def fuse(
    db: TenantSession, state: State, system: System, org_id: uuid.UUID, user_id: uuid.UUID | None
) -> dict[str, Any]:
    require_taxonomy(db)
    llm = state.llm_router if state.llm_router.providers else None
    summary = FusionService(db, make_loader(state, db, org_id), llm, org_id, user_id).run(system)
    return dataclasses.asdict(summary)


def generate_record(
    db: TenantSession, state: State, system: System, org_id: uuid.UUID, user_id: uuid.UUID | None
) -> RecordOutcome:
    """Build or refresh the record of processing. Purposes and a lawful basis are suggested by the
    assistant (one cached call) and marked for review; without a provider the record is built from
    the owner's answers."""
    if system.status not in READY_FOR_RECORD:
        raise StageError("Run the comparison before generating the record")
    settings = state.settings
    facts = make_loader(state, db, org_id).load(system)
    labels = category_labels(state)
    suggestion: PurposeAndBasis | None = None
    tokens = 0
    llm = state.llm_router
    if llm.providers:
        special = sorted(
            {labels.get(e.category or "", e.name) for e in facts.elements if e.special}
        )
        try:
            suggestion, result = suggest_purpose_and_basis(
                llm,
                Scope(
                    org_id, user_id, system.id, job=JobBudget(settings.llm_onboarding_token_budget)
                ),
                name=facts.name,
                description=system.description or "",
                data_categories=sorted(
                    {labels.get(e.category or "", "") for e in facts.elements if e.category} - {""}
                ),
                special_categories=special,
                data_subjects=facts.questionnaire.data_subjects if facts.questionnaire else [],
                recipients=[
                    {"vendor": r.label, "role": r.role, "country": r.country or "unknown"}
                    for r in facts.recipients
                    if not r.internal
                ],
                declared_purposes=(
                    [str(p) for p in (facts.questionnaire.answers.get("purposes") or [])]
                    if facts.questionnaire
                    else []
                ),
            )
            tokens = result.tokens
        except LLMError:
            suggestion = None  # the record is still built from the answers; a person can edit it
    draft = build_draft(
        facts, str(system.owner_user_id) if system.owner_user_id else None, labels, suggestion
    )
    outcome = ActivityService(db).generate(system, draft, user_id)
    return RecordOutcome(outcome, suggestion is not None, tokens)


def screen(
    db: TenantSession, state: State, system: System, org_id: uuid.UUID, user_id: uuid.UUID | None,
    scale: Scale | None = None,
) -> dict[str, Any]:  # fmt: skip
    """Score the system's record against the impact assessment criteria."""
    activity = ActivityService(db).for_system(system.id)
    if activity is None:
        raise StageError("There is no record to screen yet")
    service = ScreeningService(db, make_loader(state, db, org_id), load_criteria())
    row = service.run(system, activity, scale, user_id)
    return {
        "activity_id": str(activity.id), "met": row.criteria_met, "unknown": row.criteria_unknown,
        "required": row.required,
    }  # fmt: skip


def activity_of(db: TenantSession, system_id: uuid.UUID) -> ProcessingActivity | None:
    return ActivityService(db).for_system(system_id)
