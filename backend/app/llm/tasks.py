"""Typed entry points for the five LLM tasks. Each builds a metadata only payload, calls the router
and returns the validated result. The later phases (fusion, assessments, requests, chat) use these
and never talk to a provider directly."""

import uuid
from dataclasses import dataclass
from typing import Any

from app.knowledge.retrieval import Passage
from app.llm import schemas
from app.llm.budget import JobBudget
from app.llm.router import LLMResult, LLMRouter

MAX_PASSAGES = 3
MAX_PASSAGE_CHARS = 500
NO_EVIDENCE = "No supporting evidence found."


@dataclass(frozen=True)
class Scope:
    org_id: uuid.UUID
    user_id: uuid.UUID | None = None
    system_id: uuid.UUID | None = None
    dpia_id: uuid.UUID | None = None
    job: JobBudget | None = None


def passage_payload(passages: list[Passage], limit: int = MAX_PASSAGES) -> list[dict[str, str]]:
    """Short passages with the id the model must cite. Longer text is cut, not summarised."""
    return [{"id": str(p.id), "text": p.text[:MAX_PASSAGE_CHARS]} for p in passages[:limit]]


def _call(router: LLMRouter, task: str, payload: dict[str, Any], scope: Scope) -> LLMResult:
    return router.complete_json(
        task,
        payload,
        org_id=scope.org_id,
        user_id=scope.user_id,
        system_id=scope.system_id,
        dpia_id=scope.dpia_id,
        job=scope.job,
    )


def suggest_purpose_and_basis(
    router: LLMRouter,
    scope: Scope,
    *,
    name: str,
    description: str,
    data_categories: list[str],
    special_categories: list[str],
    data_subjects: list[str],
    recipients: list[dict[str, str]],
    declared_purposes: list[str],
) -> tuple[schemas.PurposeAndBasis, LLMResult]:
    """One call per processing activity. Category labels and recipient names only."""
    payload = {
        "activity": {"name": name, "description": description[:300]},
        "data_categories": sorted(data_categories),
        "special_categories": sorted(special_categories),
        "data_subjects": sorted(data_subjects),
        "recipients": sorted(recipients, key=lambda r: tuple(sorted(r.items()))),
        "declared_purposes": declared_purposes[:5],
    }
    result = _call(router, "suggest_purpose_and_basis", payload, scope)
    assert isinstance(result.data, schemas.PurposeAndBasis)  # noqa: S101
    return result.data, result


def adjudicate_conflict(
    router: LLMRouter,
    scope: Scope,
    *,
    conflict_type: str,
    statement: str,
    detail: str,
    passages: list[Passage],
) -> tuple[schemas.ConflictVerdict, LLMResult]:
    """Only for conflicts the rules cannot settle, with the top 3 retrieved passages."""
    payload = {
        "conflict": {"type": conflict_type, "statement": statement[:300], "detail": detail[:300]},
        "passages": passage_payload(passages),
    }
    result = _call(router, "adjudicate_conflict", payload, scope)
    assert isinstance(result.data, schemas.ConflictVerdict)  # noqa: S101
    return result.data, result


def draft_dpia_sections(
    router: LLMRouter,
    scope: Scope,
    *,
    part: str,
    activity: dict[str, Any],
    criteria_met: list[str],
    passages: list[Passage],
) -> tuple[schemas.DpiaSections, LLMResult]:
    """Two calls per assessment: part 'description', then part 'risks'."""
    if part not in ("description", "risks"):
        raise ValueError("part must be 'description' or 'risks'")
    payload = {
        "part": part,
        "activity": activity,
        "criteria_met": sorted(criteria_met),
        "passages": passage_payload(passages, limit=4),
    }
    result = _call(router, "draft_dpia_sections", payload, scope)
    assert isinstance(result.data, schemas.DpiaSections)  # noqa: S101
    return result.data, result


def draft_request_cover_note(
    router: LLMRouter, scope: Scope, *, days_taken: int, systems_found: int
) -> tuple[schemas.CoverNote, LLMResult]:
    """Counts only: no names, identifiers or request content."""
    payload = {
        "request_type": "access",
        "days_taken": days_taken,
        "systems_found": systems_found,
        "tone": "formal",
    }
    result = _call(router, "draft_request_cover_note", payload, scope)
    assert isinstance(result.data, schemas.CoverNote)  # noqa: S101
    return result.data, result


def answer_question(
    router: LLMRouter, scope: Scope, *, question: str, passages: list[Passage]
) -> tuple[schemas.Answer, LLMResult | None]:
    """Retrieval augmented answer. With nothing retrieved the model is not called at all."""
    if not passages:
        return schemas.Answer(answer=NO_EVIDENCE, supported=False, cited_passage_ids=[]), None
    payload = {"question": question[:500], "passages": passage_payload(passages, limit=5)}
    result = _call(router, "answer_question", payload, scope)
    assert isinstance(result.data, schemas.Answer)  # noqa: S101
    return result.data, result
