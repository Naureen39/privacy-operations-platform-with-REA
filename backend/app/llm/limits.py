"""Per provider rate limit tracking and the circuit breaker. State lives in the process; it is
seeded from the provider's response headers where they exist (Groq) and from configuration."""

import re
from collections.abc import Callable
from dataclasses import dataclass

Clock = Callable[[], float]
_DURATION = re.compile(
    r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?"
)


def parse_duration(value: str | None) -> float | None:
    """Seconds from '6.2s', '1m2.5s', '250ms' or a plain number (Retry-After)."""
    if not value:
        return None
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        pass
    match = _DURATION.fullmatch(value)
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds, millis = (float(g) if g else 0.0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


@dataclass
class TokenBucket:
    """Tokens and requests per minute, refilled continuously."""

    tokens_per_minute: int
    requests_per_minute: int
    clock: Clock
    tokens: float = 0.0
    requests: float = 0.0
    blocked_until: float = 0.0
    updated: float = 0.0

    def __post_init__(self) -> None:
        self.tokens = float(self.tokens_per_minute)
        self.requests = float(self.requests_per_minute)
        self.updated = self.clock()

    def _refill(self) -> None:
        now = self.clock()
        elapsed = max(0.0, now - self.updated)
        self.updated = now
        self.tokens = min(
            self.tokens_per_minute, self.tokens + elapsed * self.tokens_per_minute / 60
        )
        self.requests = min(
            self.requests_per_minute, self.requests + elapsed * self.requests_per_minute / 60
        )

    def wait_needed(self, tokens: int) -> float:
        """Seconds until a request of this size fits (0 when it fits now)."""
        self._refill()
        now = self.clock()
        waits = [max(0.0, self.blocked_until - now)]
        if tokens > self.tokens:
            waits.append((tokens - self.tokens) * 60 / self.tokens_per_minute)
        if self.requests < 1:
            waits.append((1 - self.requests) * 60 / self.requests_per_minute)
        return max(waits)

    def take(self, tokens: int) -> None:
        self._refill()
        self.tokens = max(0.0, self.tokens - tokens)
        self.requests = max(0.0, self.requests - 1)

    def observe(
        self,
        remaining_tokens: int | None = None,
        remaining_requests: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Trust the provider's own numbers over the local estimate."""
        self._refill()
        if remaining_tokens is not None:
            self.tokens = float(min(remaining_tokens, self.tokens_per_minute))
        if remaining_requests is not None:
            self.requests = float(min(remaining_requests, self.requests_per_minute))
        if retry_after is not None:
            self.blocked_until = self.clock() + retry_after


@dataclass
class CircuitBreaker:
    """Opens for `open_seconds` after `threshold` consecutive failures, then lets one probe through."""

    clock: Clock
    threshold: int = 3
    open_seconds: float = 60.0
    failures: int = 0
    opened_at: float | None = None
    probing: bool = False

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if self.clock() - self.opened_at >= self.open_seconds:
            return "half_open"
        return "open"

    def seconds_until_probe(self) -> float:
        if self.opened_at is None:
            return 0.0
        return max(0.0, self.open_seconds - (self.clock() - self.opened_at))

    def allow(self) -> bool:
        state = self.state
        if state == "closed":
            return True
        if state == "half_open" and not self.probing:
            self.probing = True
            return True
        return False

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None
        self.probing = False

    def failure(self) -> None:
        self.failures += 1
        self.probing = False
        if self.failures >= self.threshold or self.opened_at is not None:
            self.opened_at = self.clock()
