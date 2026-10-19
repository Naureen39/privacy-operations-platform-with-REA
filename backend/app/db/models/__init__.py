"""Importing this package registers every table on Base.metadata."""

from app.db.models.billing import (
    ComplianceDailyMetric,
    DailyMetric,
    Invoice,
    InvoiceLine,
    Plan,
    Subscription,
    UsageEvent,
)
from app.db.models.identity import (
    AuditLog,
    Lead,
    Membership,
    Organization,
    RefreshToken,
    User,
)
from app.db.models.inventory import (
    DataElement,
    DiscoveryEvidence,
    DiscoveryRun,
    EvidenceItem,
    Recipient,
    System,
    Technology,
)
from app.db.models.knowledge import Document, DocumentChunk, RegulationChunk
from app.db.models.llm import LlmCache, LlmCall
from app.db.models.records import (
    ActivitySystem,
    ActivityVersion,
    Dpia,
    DpiaRisk,
    ProcessingActivity,
)
from app.db.models.work import (
    AccessRequest,
    Approval,
    Comment,
    Finding,
    RequestResponse,
    RequestResult,
    Task,
)

__all__ = [
    "AccessRequest",
    "ActivitySystem",
    "ActivityVersion",
    "Approval",
    "AuditLog",
    "Comment",
    "ComplianceDailyMetric",
    "DailyMetric",
    "DataElement",
    "DiscoveryEvidence",
    "DiscoveryRun",
    "Document",
    "DocumentChunk",
    "Dpia",
    "DpiaRisk",
    "EvidenceItem",
    "Finding",
    "Invoice",
    "InvoiceLine",
    "Lead",
    "LlmCache",
    "LlmCall",
    "Membership",
    "Organization",
    "Plan",
    "ProcessingActivity",
    "Recipient",
    "RefreshToken",
    "RegulationChunk",
    "RequestResponse",
    "RequestResult",
    "Subscription",
    "System",
    "Task",
    "Technology",
    "UsageEvent",
    "User",
]
