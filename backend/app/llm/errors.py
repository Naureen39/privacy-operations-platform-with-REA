from dataclasses import dataclass, field
from typing import Literal

ErrorKind = Literal["rate_limit", "server", "timeout", "network", "auth", "bad_request"]


class LLMError(Exception):
    """Base class for everything the router raises."""


class PayloadRejectedError(LLMError):
    """The payload carried something that must never reach a model (sample values, identifiers)."""


class BudgetExceededError(LLMError):
    def __init__(self, scope: str, limit: int, needed: int) -> None:
        super().__init__(f"{scope} token budget of {limit} would be exceeded (needs {needed})")
        self.scope = scope
        self.limit = limit
        self.needed = needed


@dataclass
class Attempt:
    provider: str
    outcome: str
    detail: str = ""


class LLMUnavailableError(LLMError):
    """No provider could answer right now. The caller keeps the job and retries after
    `retry_after_seconds`; nothing was lost."""

    def __init__(self, retry_after_seconds: float, attempts: list[Attempt]) -> None:
        super().__init__(
            "No LLM provider is available: "
            + "; ".join(f"{a.provider} {a.outcome}" for a in attempts)
        )
        self.retry_after_seconds = retry_after_seconds
        self.attempts = attempts


@dataclass
class ProviderError(Exception):
    kind: ErrorKind
    message: str = ""
    status: int | None = None
    retry_after: float | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.kind}: {self.message}"[:300]


class SchemaFailureError(LLMError):
    """The model's answer did not match the schema, even after one repair attempt."""
