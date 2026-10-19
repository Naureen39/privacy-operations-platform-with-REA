from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    ANALYST = "analyst"
    SYSTEM_OWNER = "system_owner"
    VIEWER = "viewer"


class JobState(StrEnum):
    CREATED = "CREATED"
    EVIDENCE_ATTACHED = "EVIDENCE_ATTACHED"
    DISCOVERING = "DISCOVERING"
    CLASSIFIED = "CLASSIFIED"
    FUSED = "FUSED"
    DRAFTED = "DRAFTED"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class EvidenceKind(StrEnum):
    HAR = "har"
    WEBSITE = "website"
    JAVASCRIPT_BUNDLE = "javascript_bundle"
    SQLITE_SNAPSHOT = "sqlite_snapshot"
    QUESTIONNAIRE = "questionnaire"
    PRIVACY_POLICY = "privacy_policy"
    VENDOR_AGREEMENT = "vendor_agreement"


class Extractor(StrEnum):
    REA = "rea"
    FALLBACK = "fallback"
    DOCUMENT = "document"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    OVERRIDDEN = "overridden"


class RecipientRole(StrEnum):
    CONTROLLER = "controller"
    PROCESSOR = "processor"
    JOINT_CONTROLLER = "joint_controller"
    UNKNOWN = "unknown"


class ActivityStatus(StrEnum):
    DRAFT = "draft"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class DpiaStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class FindingSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class TaskStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RequestStatus(StrEnum):
    RECEIVED = "received"
    IDENTITY_VERIFICATION = "identity_verification"
    SEARCHING = "searching"
    DRAFTING = "drafting"
    AWAITING_APPROVAL = "awaiting_approval"
    RESPONDED = "responded"
    CLOSED = "closed"
    REJECTED = "rejected"


class ResponseStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SENT = "sent"


class DocumentType(StrEnum):
    POLICY = "policy"
    VENDOR_AGREEMENT = "vendor_agreement"
    QUESTIONNAIRE = "questionnaire"
    GUIDANCE = "guidance"


class LlmCallStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    SCHEMA_FAILURE = "schema_failure"
    BUDGET_BLOCKED = "budget_blocked"


class LeadKind(StrEnum):
    CONTACT = "contact"
    DEMO_REQUEST = "demo_request"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    CANCELED = "canceled"


class InvoiceStatus(StrEnum):
    PAID = "paid"
    OPEN = "open"
    OVERDUE = "overdue"
    VOID = "void"


class InvoiceLineKind(StrEnum):
    BASE = "base"
    EXTRA_SYSTEMS = "extra_systems"
    EXTRA_REQUESTS = "extra_requests"


class UsageKind(StrEnum):
    ACTIVE_SYSTEMS = "active_systems"
    REQUESTS_PROCESSED = "requests_processed"
    ASSESSMENTS_GENERATED = "assessments_generated"
    TOKENS_USED = "tokens_used"
