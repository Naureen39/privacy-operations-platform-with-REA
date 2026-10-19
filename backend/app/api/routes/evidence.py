import hashlib
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import select

from app.api.deps import (
    ALL_ROLES,
    Principal,
    app_settings,
    get_visible_system,
    require_role,
    write_audit,
)
from app.api.schemas import EvidenceOut, ObservationUrlIn
from app.api.tenancy import get_tenant_db
from app.core.config import Settings
from app.core.uploads import UploadRejectedError, validate_upload
from app.core.urlguard import UrlRejectedError, validate_observation_url
from app.db.enums import EvidenceKind, Role
from app.db.models import EvidenceItem
from app.db.session import TenantSession
from app.services.evidence_store import EvidenceStore

router = APIRouter(prefix="/api/v1/systems/{system_id}/evidence", tags=["evidence"])

UPLOADERS = (Role.ADMIN, Role.ANALYST, Role.SYSTEM_OWNER)


def get_store(request: Request) -> EvidenceStore:
    store: EvidenceStore = request.app.state.evidence_store
    return store


@router.get("", response_model=list[EvidenceOut])
def list_evidence(
    system_id: uuid.UUID,
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[EvidenceItem]:
    get_visible_system(db, principal, system_id)
    stmt = (
        select(EvidenceItem)
        .where(EvidenceItem.system_id == system_id)
        .order_by(EvidenceItem.created_at.desc())
    )
    return list(db.scalars(stmt))


@router.post("", response_model=EvidenceOut, status_code=status.HTTP_201_CREATED)
def upload_evidence(
    request: Request,
    system_id: uuid.UUID,
    kind: Annotated[EvidenceKind, Form()],
    file: Annotated[UploadFile, File()],
    principal: Principal = Depends(require_role(*UPLOADERS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
    store: EvidenceStore = Depends(get_store),
) -> EvidenceItem:
    get_visible_system(db, principal, system_id)
    # Read at most one byte over the cap, so an oversized upload is never held in memory.
    content = file.file.read(settings.max_upload_bytes + 1)
    try:
        filename = validate_upload(
            file.filename or "upload", kind, content, settings.max_upload_bytes
        )
    except UploadRejectedError as exc:
        write_audit(db, request, "evidence.upload_rejected", principal=principal,
                    entity_type="system", entity_id=system_id,
                    details={"kind": kind.value, "reason": str(exc)})  # fmt: skip
        db.commit()
        raise HTTPException(exc.status_code, str(exc)) from exc

    evidence_id = uuid.uuid4()
    path = store.save(principal.org_id, system_id, evidence_id, content)
    item = EvidenceItem(
        id=evidence_id,
        system_id=system_id,
        kind=kind,
        filename=filename,
        storage_path=path,
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        encrypted=True,
        uploaded_by=principal.user_id,
    )
    db.add(item)
    write_audit(db, request, "evidence.upload", principal=principal, entity_type="evidence",
                entity_id=evidence_id, details={"kind": kind.value, "size": len(content)})  # fmt: skip
    try:
        db.commit()
    except Exception:
        store.delete(path)
        raise
    db.refresh(item)
    return item


@router.post("/url", response_model=EvidenceOut, status_code=status.HTTP_201_CREATED)
def register_observation_url(
    request: Request,
    system_id: uuid.UUID,
    body: ObservationUrlIn,
    principal: Principal = Depends(require_role(Role.ADMIN, Role.ANALYST)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> EvidenceItem:
    """Register a website for later observation. The URL is validated here and again by
    the rea-browser runner immediately before connecting. Nothing is fetched by the API.
    """
    get_visible_system(db, principal, system_id)
    try:
        resolved = validate_observation_url(
            body.url,
            allowed_hosts=settings.observation_allowed_hosts,
            allowed_networks=settings.observation_allowed_networks,
            allowed_ports=settings.observation_allowed_ports,
        )
    except UrlRejectedError as exc:
        write_audit(db, request, "evidence.url_rejected", principal=principal,
                    entity_type="system", entity_id=system_id,
                    details={"reason": str(exc)})  # fmt: skip
        db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    item = EvidenceItem(
        system_id=system_id,
        kind=EvidenceKind.WEBSITE,
        filename=resolved.host,
        storage_path=resolved.url,
        checksum_sha256=hashlib.sha256(resolved.url.encode()).hexdigest(),
        size_bytes=0,
        encrypted=False,
        uploaded_by=principal.user_id,
    )
    db.add(item)
    db.flush()
    write_audit(db, request, "evidence.url_registered", principal=principal,
                entity_type="evidence", entity_id=item.id, details={"host": resolved.host})  # fmt: skip
    db.commit()
    db.refresh(item)
    return item
