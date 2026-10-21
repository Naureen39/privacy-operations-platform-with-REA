import dataclasses
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select

from app.api.deps import ALL_ROLES, Principal, get_visible_system, require_role, write_audit
from app.api.schemas import (
    ClassificationSummaryOut,
    DataElementOut,
    ElementReview,
    TaxonomyCategoryOut,
)
from app.api.tenancy import get_tenant_db
from app.classify.embedder import Embedder
from app.classify.engine import Classifier
from app.classify.index import PgMatcher
from app.classify.knowledge import Knowledge
from app.classify.service import ClassificationService
from app.db.enums import ReviewStatus, Role
from app.db.models import DataElement, TaxonomyEntry
from app.db.session import TenantSession

router = APIRouter(prefix="/api/v1", tags=["classification"])

REVIEWERS = (Role.ADMIN, Role.ANALYST)


def get_knowledge(request: Request) -> Knowledge:
    knowledge: Knowledge = request.app.state.knowledge
    return knowledge


def get_embedder(request: Request) -> Embedder:
    embedder: Embedder = request.app.state.embedder
    return embedder


@router.get("/taxonomy", response_model=list[TaxonomyCategoryOut])
def list_taxonomy(
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    knowledge: Knowledge = Depends(get_knowledge),
) -> list[TaxonomyCategoryOut]:
    return [
        TaxonomyCategoryOut(
            id=c.id,
            label=c.label,
            definition=c.definition,
            sensitivity=c.sensitivity,
            special_category=c.special_category,
        )
        for c in knowledge.categories.values()
    ]


@router.post("/systems/{system_id}/classification", response_model=ClassificationSummaryOut)
def classify_system(
    request: Request,
    system_id: uuid.UUID,
    principal: Principal = Depends(require_role(*REVIEWERS)),
    db: TenantSession = Depends(get_tenant_db),
    knowledge: Knowledge = Depends(get_knowledge),
    embedder: Embedder = Depends(get_embedder),
) -> ClassificationSummaryOut:
    """Classify the discovered elements and resolve the recipients (no LLM is called)."""
    system = get_visible_system(db, principal, system_id)
    if not db.scalar(select(func.count()).select_from(TaxonomyEntry)):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The taxonomy index is not loaded (run scripts/load_taxonomy.py)",
        )
    summary = ClassificationService(
        db, Classifier(knowledge, embedder, PgMatcher(db)), knowledge
    ).run(system)
    write_audit(
        db,
        request,
        "classification.run",
        principal=principal,
        entity_type="system",
        entity_id=system.id,
        details={
            "elements": summary.elements,
            "classified": summary.classified,
            "special_strong": summary.special_strong,
            "special_near": summary.special_near,
            "recipients_unknown": summary.recipients_unknown,
            "thresholds_version": summary.thresholds_version,
        },
    )
    db.commit()
    return ClassificationSummaryOut(**dataclasses.asdict(summary))


@router.patch("/systems/{system_id}/data-elements/{element_id}", response_model=DataElementOut)
def review_element(
    request: Request,
    system_id: uuid.UUID,
    element_id: uuid.UUID,
    body: ElementReview,
    principal: Principal = Depends(require_role(*REVIEWERS)),
    db: TenantSession = Depends(get_tenant_db),
    knowledge: Knowledge = Depends(get_knowledge),
) -> DataElement:
    """Accept the classifier's decision or override it. Reviewed elements are not changed again."""
    get_visible_system(db, principal, system_id)
    element = db.scalar(
        select(DataElement).where(DataElement.id == element_id, DataElement.system_id == system_id)
    )
    if element is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Data element not found")
    before = {"category": element.category, "special_category": element.special_category}
    if body.review_status == "overridden" or body.category is not None or body.not_personal_data:
        if body.not_personal_data:
            element.category = None
            element.special_category = False
            element.special_category_label = None
        elif body.category is not None:
            category = knowledge.categories.get(body.category)
            if category is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown category")
            element.category = category.id
            element.special_category = category.special_category
            element.special_category_label = category.label if category.special_category else None
        element.confidence = Decimal(1)  # decided by a person
    if body.special_category is not None:
        element.special_category = body.special_category
        if not body.special_category:
            element.special_category_label = None
    element.review_status = ReviewStatus(body.review_status)
    write_audit(
        db,
        request,
        "classification.review",
        principal=principal,
        entity_type="data_element",
        entity_id=element.id,
        details={
            "from": before,
            "to": {"category": element.category, "special_category": element.special_category},
            "status": body.review_status,
        },
    )
    db.commit()
    return element
