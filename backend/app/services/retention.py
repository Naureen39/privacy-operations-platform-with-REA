"""Evidence retention: delete uploaded evidence older than the configured period."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, delete, select, text
from sqlalchemy.orm import sessionmaker

from app.db.models import AuditLog, EvidenceItem
from app.db.session import TenantContext, TenantSession, tenant_session
from app.services.evidence_store import EvidenceStore

log = logging.getLogger(__name__)


def purge_expired_evidence(
    owner_engine: Engine,
    factory: sessionmaker[TenantSession],
    store: EvidenceStore,
    default_days: int,
    now: datetime | None = None,
) -> dict[str, int]:
    """Delete expired evidence for every organization. Returns the count per organization id.

    Organizations are listed with the owner role (the application role cannot see other
    tenants). Each organization is then processed in its own tenant session, so row level
    security still bounds what is deleted.
    """
    now = now or datetime.now(UTC)
    with owner_engine.connect() as conn:
        orgs = conn.execute(text("SELECT id, settings FROM organizations")).all()

    purged: dict[str, int] = {}
    for org_id, org_settings in orgs:
        days = int((org_settings or {}).get("evidence_retention_days", default_days))
        cutoff = now - timedelta(days=days)
        with tenant_session(factory, TenantContext(org_id)) as s:
            expired = list(
                s.execute(
                    select(
                        EvidenceItem.id,
                        EvidenceItem.storage_path,
                        EvidenceItem.encrypted,
                    ).where(EvidenceItem.created_at < cutoff)
                )
            )
            if not expired:
                continue
            for _, path, encrypted in expired:
                if encrypted:
                    store.delete(path)
            s.execute(delete(EvidenceItem).where(EvidenceItem.id.in_([row[0] for row in expired])))
            s.add(
                AuditLog(
                    org_id=org_id,
                    action="evidence.retention_purge",
                    details={"deleted": len(expired), "retention_days": days},
                )
            )
            purged[str(org_id)] = len(expired)
    log.info("evidence retention purge finished", extra={"organizations": len(purged)})
    return purged
