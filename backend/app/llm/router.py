"""The LLM router: cache first, then budgets, then providers in order with retries, failover and a
circuit breaker. Every attempt is written to `llm_calls` in its own transaction, so the log survives
a caller that rolls back.

    result = router.complete_json("adjudicate_conflict", payload, org_id=org, system_id=system)

If no provider can answer, `LLMUnavailableError` carries a retry delay; the caller keeps its job and
tries again later. Nothing is lost and nothing is partly written.
"""

import hashlib
import json
import random
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from app.db.enums import LlmCallStatus
from app.db.models import LlmCache, LlmCall, Organization
from app.db.session import TenantContext, TenantSession, tenant_session
from app.llm.budget import BudgetPolicy, JobBudget, tokens_used_today
from app.llm.errors import (
    Attempt,
    BudgetExceededError,
    LLMUnavailableError,
    ProviderError,
    SchemaFailureError,
)
from app.llm.guard import sanitize
from app.llm.limits import CircuitBreaker, Clock, TokenBucket
from app.llm.prompts import PromptSpec, get_prompt
from app.llm.providers import Provider, ProviderRequest, ProviderResponse
from app.llm.tokens import estimate_tokens

DEFAULT_ORDER = ("groq", "gemini")
MAX_BACKOFF = 8.0


@dataclass
class LLMResult:
    data: BaseModel
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    cached_tokens: int
    cache_hit: bool
    attempts: int

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out


@dataclass
class ProviderLimits:
    tokens_per_minute: int
    requests_per_minute: int


class LLMRouter:
    def __init__(
        self,
        providers: dict[str, Provider],
        session_factory: Callable[[], sessionmaker[TenantSession]],
        *,
        policy: BudgetPolicy | None = None,
        limits: dict[str, ProviderLimits] | None = None,
        max_output_tokens: int = 800,
        attempts_per_provider: int = 2,
        base_backoff: float = 0.5,
        clock: Clock = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.providers = providers
        self._factory = session_factory
        self.policy = policy or BudgetPolicy()
        self.max_output_tokens = max_output_tokens
        self.attempts_per_provider = max(1, attempts_per_provider)
        self.base_backoff = base_backoff
        self.clock = clock
        self.sleep = sleep
        self.rng = rng or random.Random()  # noqa: S311  (backoff jitter, not security)
        limits = limits or {}
        self.buckets = {
            name: TokenBucket(
                (limits.get(name) or ProviderLimits(1_000_000, 600)).tokens_per_minute,
                (limits.get(name) or ProviderLimits(1_000_000, 600)).requests_per_minute,
                clock,
            )
            for name in providers
        }
        self.breakers = {name: CircuitBreaker(clock) for name in providers}

    # -- public ------------------------------------------------------------------------------

    def complete_json(
        self,
        task: str,
        payload: dict[str, Any],
        *,
        org_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        system_id: uuid.UUID | None = None,
        dpia_id: uuid.UUID | None = None,
        job: JobBudget | None = None,
        order: Sequence[str] | None = None,
    ) -> LLMResult:
        spec = get_prompt(task)
        clean = sanitize(payload).payload
        user_message = _fenced(clean)
        estimate = (
            estimate_tokens(spec.system) + estimate_tokens(user_message) + self.max_output_tokens
        )
        request_hash = _request_hash(spec, clean)
        ctx = TenantContext(org_id=org_id, user_id=user_id)
        meta = _CallMeta(task, system_id, dpia_id)

        with tenant_session(self._factory(), ctx) as db:
            org_settings = _org_settings(db, org_id)
            cached = self._cache_get(db, spec, request_hash)
            if cached is not None:
                self._log(db, meta, "cache", "cache", LlmCallStatus.OK, cache_hit=True)
                return LLMResult(cached, "cache", "cache", 0, 0, 0, True, 0)
            blocked = self._check_budgets(db, estimate, system_id, job, org_settings)
        if blocked is not None:
            with tenant_session(self._factory(), ctx) as db:
                self._log(
                    db, meta, "none", "none", LlmCallStatus.BUDGET_BLOCKED, error=str(blocked)
                )
            raise blocked

        names = [
            n for n in (order or org_settings.get("order") or DEFAULT_ORDER) if n in self.providers
        ]
        result = self._run(spec, clean, user_message, estimate, names, ctx, meta, job)
        with tenant_session(self._factory(), ctx) as db:
            self._cache_put(db, spec, request_hash, result.data)
        return result

    # -- provider loop -----------------------------------------------------------------------

    def _run(
        self,
        spec: PromptSpec,
        clean: dict[str, Any],
        user_message: str,
        estimate: int,
        names: list[str],
        ctx: TenantContext,
        meta: "_CallMeta",
        job: JobBudget | None,
    ) -> LLMResult:
        attempts: list[Attempt] = []
        waits: list[float] = []
        calls = 0
        for name in names:
            provider = self.providers[name]
            breaker, bucket = self.breakers[name], self.buckets[name]
            if not breaker.allow():
                attempts.append(Attempt(name, "circuit open"))
                waits.append(breaker.seconds_until_probe())
                continue
            wait = bucket.wait_needed(estimate)
            if wait > 0:
                attempts.append(Attempt(name, "rate limit reached", f"{wait:.1f}s"))
                waits.append(wait)
                continue
            for attempt in range(self.attempts_per_provider):
                calls += 1
                request = ProviderRequest(
                    spec.system, user_message, spec.schema, spec.schema_name, self.max_output_tokens
                )
                try:
                    outcome = self._call_and_validate(
                        provider, spec, clean, request, ctx, meta, job
                    )
                except ProviderError as exc:
                    bucket.observe(retry_after=exc.retry_after)
                    breaker.failure()
                    attempts.append(Attempt(name, exc.kind, exc.message[:80]))
                    retry_here = exc.kind in ("server", "timeout", "network") or (
                        exc.kind == "rate_limit" and (exc.retry_after or 0) <= MAX_BACKOFF
                    )
                    if retry_here and attempt + 1 < self.attempts_per_provider and breaker.allow():
                        self.sleep(self._backoff(attempt, exc.retry_after))
                        continue
                    if exc.retry_after:
                        waits.append(exc.retry_after)
                    break
                except SchemaFailureError as exc:
                    breaker.failure()
                    attempts.append(Attempt(name, "schema failure", str(exc)[:80]))
                    break
                breaker.success()
                outcome.attempts = calls
                return outcome
        raise LLMUnavailableError(min(waits) if waits else 30.0, attempts)

    def _call_and_validate(
        self,
        provider: Provider,
        spec: PromptSpec,
        clean: dict[str, Any],
        request: ProviderRequest,
        ctx: TenantContext,
        meta: "_CallMeta",
        job: JobBudget | None,
    ) -> LLMResult:
        """One provider call plus at most one repair call when the answer does not validate."""
        total_in = total_out = total_cached = 0
        repair: str | None = None
        for round_ in range(2):
            started = time.perf_counter()
            req = request if repair is None else _with_repair(request, repair)
            try:
                response = provider.complete(req)
            except ProviderError as exc:
                self._log_isolated(
                    ctx, meta, provider, LlmCallStatus.RATE_LIMITED if exc.kind == "rate_limit" else LlmCallStatus.ERROR,
                    error=str(exc), latency=_ms(started),
                )  # fmt: skip
                raise
            self.buckets[provider.name].take(response.tokens_in + response.tokens_out)
            self.buckets[provider.name].observe(
                response.rate.remaining_tokens, response.rate.remaining_requests
            )
            total_in += response.tokens_in
            total_out += response.tokens_out
            total_cached += response.cached_tokens
            if job is not None:
                job.consume(response.tokens_in + response.tokens_out)
            try:
                data = _parse(spec, clean, response)
            except (ValidationError, ValueError) as exc:
                self._log_isolated(
                    ctx, meta, provider, LlmCallStatus.SCHEMA_FAILURE, response=response,
                    error=_short_error(exc), latency=_ms(started),
                )  # fmt: skip
                repair = (
                    "Your previous answer was invalid: "
                    + _short_error(exc)
                    + ". Answer again with one valid JSON object only."
                )
                if round_ == 1:
                    raise SchemaFailureError(_short_error(exc)) from exc
                continue
            self._log_isolated(
                ctx, meta, provider, LlmCallStatus.OK, response=response, latency=_ms(started)
            )
            return LLMResult(
                data, provider.name, response.model or provider.model,
                total_in, total_out, total_cached, False, 1,
            )  # fmt: skip
        raise SchemaFailureError("no valid answer")  # unreachable

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        delay = float(min(MAX_BACKOFF, self.base_backoff * (2**attempt)))
        delay *= 0.5 + self.rng.random() / 2  # jitter
        return max(delay, retry_after or 0.0)

    # -- budgets -----------------------------------------------------------------------------

    def _check_budgets(
        self,
        db: Session,
        estimate: int,
        system_id: uuid.UUID | None,
        job: JobBudget | None,
        org_settings: dict[str, Any],
    ) -> BudgetExceededError | None:
        if estimate > self.policy.request_cap:
            return BudgetExceededError("request", self.policy.request_cap, estimate)
        if job is not None and estimate > job.remaining:
            return BudgetExceededError("job", job.limit, job.used + estimate)
        org_limit = int(org_settings.get("org_daily") or self.policy.org_daily)
        used = tokens_used_today(db)
        if used + estimate > org_limit:
            return BudgetExceededError("organisation daily", org_limit, used + estimate)
        if system_id is not None:
            system_limit = int(org_settings.get("system_daily") or self.policy.system_daily)
            system_used = tokens_used_today(db, system_id)
            if system_used + estimate > system_limit:
                return BudgetExceededError("system daily", system_limit, system_used + estimate)
        return None

    # -- cache and log -----------------------------------------------------------------------

    def _cache_get(self, db: Session, spec: PromptSpec, request_hash: str) -> BaseModel | None:
        row = db.query(LlmCache).filter(LlmCache.request_hash == request_hash).one_or_none()
        if row is None:
            return None
        try:
            data = spec.output_model.model_validate(row.response)
        except ValidationError:
            return None  # an older schema; ask again
        db.execute(
            update(LlmCache).where(LlmCache.id == row.id).values(hit_count=LlmCache.hit_count + 1)
        )
        return data

    def _cache_put(self, db: Session, spec: PromptSpec, request_hash: str, data: BaseModel) -> None:
        org_id = db.info["tenant_context"].org_id
        db.execute(
            pg_insert(LlmCache)
            .values(
                org_id=org_id,
                request_hash=request_hash,
                task=spec.task,
                response=data.model_dump(mode="json"),
            )
            .on_conflict_do_nothing(index_elements=["org_id", "request_hash"])
        )

    def _log(
        self,
        db: Session,
        meta: "_CallMeta",
        provider: str,
        model: str,
        status: LlmCallStatus,
        *,
        response: ProviderResponse | None = None,
        cache_hit: bool = False,
        error: str | None = None,
        latency: int | None = None,
    ) -> None:
        db.add(
            LlmCall(
                provider=provider,
                model=model,
                task=meta.task,
                tokens_in=response.tokens_in if response else 0,
                tokens_out=response.tokens_out if response else 0,
                cached_tokens=response.cached_tokens if response else 0,
                latency_ms=latency,
                status=status,
                cache_hit=cache_hit,
                system_id=meta.system_id,
                dpia_id=meta.dpia_id,
                error=error[:500] if error else None,
            )
        )

    def _log_isolated(
        self,
        ctx: TenantContext,
        meta: "_CallMeta",
        provider: Provider,
        status: LlmCallStatus,
        *,
        response: ProviderResponse | None = None,
        error: str | None = None,
        latency: int | None = None,
    ) -> None:
        with tenant_session(self._factory(), ctx) as db:
            self._log(
                db, meta, provider.name, (response.model if response else "") or provider.model,
                status, response=response, error=error, latency=latency,
            )  # fmt: skip


@dataclass(frozen=True)
class _CallMeta:
    task: str
    system_id: uuid.UUID | None
    dpia_id: uuid.UUID | None


def _fenced(clean: dict[str, Any]) -> str:
    body = json.dumps(clean, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return f"<data>\n{body}\n</data>"


def _request_hash(spec: PromptSpec, clean: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"task": spec.task, "version": spec.version, "prompt": spec.sha256, "payload": clean},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse(spec: PromptSpec, clean: dict[str, Any], response: ProviderResponse) -> BaseModel:
    text = response.text.strip()
    if text.startswith("```"):  # some models fence the JSON despite instructions
        text = text.strip("`").removeprefix("json").strip()
    data = spec.output_model.model_validate_json(text)
    if spec.check is not None:
        spec.check(clean, data)
    return data


def _with_repair(request: ProviderRequest, repair: str) -> ProviderRequest:
    return ProviderRequest(
        request.system,
        request.user,
        request.schema,
        request.schema_name,
        request.max_tokens,
        repair,
    )


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        return f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}"[:200]
    return str(exc)[:200]


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _org_settings(db: Session, org_id: uuid.UUID) -> dict[str, Any]:
    org = db.get(Organization, org_id)
    raw = (org.settings if org else None) or {}
    return {
        "order": raw.get("llm_provider_order"),
        "org_daily": raw.get("daily_token_budget_org"),
        "system_daily": raw.get("daily_token_budget_system"),
    }


@dataclass
class PingResult:
    provider: str
    model: str
    ok: bool
    latency_ms: int | None = None
    error: str | None = None


def ping_provider(
    router: LLMRouter, name: str, *, org_id: uuid.UUID, user_id: uuid.UUID | None
) -> PingResult:
    """One tiny request to check the credentials and the model name. Logged like any other call."""
    provider = router.providers[name]
    spec = get_prompt("ping")
    request = ProviderRequest(
        spec.system, _fenced({"check": "connection"}), spec.schema, spec.schema_name, 20
    )
    ctx = TenantContext(org_id=org_id, user_id=user_id)
    meta = _CallMeta("ping", None, None)
    started = time.perf_counter()
    try:
        response = provider.complete(request)
    except ProviderError as exc:
        status = LlmCallStatus.RATE_LIMITED if exc.kind == "rate_limit" else LlmCallStatus.ERROR
        router._log_isolated(ctx, meta, provider, status, error=str(exc), latency=_ms(started))
        return PingResult(name, provider.model, False, _ms(started), str(exc))
    router._log_isolated(
        ctx, meta, provider, LlmCallStatus.OK, response=response, latency=_ms(started)
    )
    return PingResult(name, response.model or provider.model, True, _ms(started))
