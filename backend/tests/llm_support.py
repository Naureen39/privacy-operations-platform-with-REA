"""Test doubles for the LLM layer: a scripted provider, a fake clock and a transport that replays
recorded provider responses. Nothing here touches the network."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.llm.errors import ProviderError
from app.llm.providers import ProviderRequest, ProviderResponse, RateInfo
from app.llm.tokens import estimate_tokens

RECORDED = Path(__file__).resolve().parent / "recorded" / "llm"

PURPOSE_ANSWER = {
    "purposes": ["Order fulfilment", "Customer accounts"],
    "lawful_basis": "contract",
    "basis_rationale": "Orders are placed to perform a sales contract with the customer.",
    "needs_review": False,
}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


def recorded(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((RECORDED / f"{name}.json").read_text(encoding="utf-8"))
    return data


class ScriptedTransport(httpx.BaseTransport):
    """Replays a list of steps in order. A step is a recording name, a dict with status/headers/body,
    or an exception to raise. Requests are kept for inspection."""

    def __init__(self, *steps: str | dict[str, Any] | Exception) -> None:
        self.steps = list(steps)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.steps:
            raise AssertionError("no scripted response left")
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, Exception):
            raise step
        spec = recorded(step) if isinstance(step, str) else step
        return httpx.Response(
            spec["status"], headers=spec.get("headers", {}), json=spec.get("body", {})
        )

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]


@dataclass
class FakeProvider:
    """A provider whose outcomes are scripted. An outcome is a dict (the JSON answer), a string (raw
    text), or a ProviderError to raise. Token usage is estimated from the request, like a real
    provider's count would roughly be."""

    name: str
    model: str = "fake-model"
    outcomes: list[Any] = field(default_factory=list)
    default: Any = None
    requests: list[ProviderRequest] = field(default_factory=list)
    on_call: Callable[[ProviderRequest], None] | None = None

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        if self.on_call:
            self.on_call(request)
        outcome = self.outcomes.pop(0) if self.outcomes else self.default
        if isinstance(outcome, ProviderError):
            raise outcome
        if outcome is None:
            raise AssertionError(f"{self.name}: no scripted outcome")
        text = outcome if isinstance(outcome, str) else json.dumps(outcome)
        tokens_in = estimate_tokens(request.system) + estimate_tokens(request.user)
        if request.repair:
            tokens_in += estimate_tokens(request.repair)
        return ProviderResponse(
            text=text,
            tokens_in=tokens_in,
            tokens_out=estimate_tokens(text),
            cached_tokens=0,
            model=self.model,
            rate=RateInfo(),
        )

    @property
    def calls(self) -> int:
        return len(self.requests)


def rate_limited(retry_after: float | None = 2.0) -> ProviderError:
    return ProviderError("rate_limit", "429", 429, retry_after)


def server_error() -> ProviderError:
    return ProviderError("server", "503", 503)


def timeout() -> ProviderError:
    return ProviderError("timeout", "ReadTimeout")


VERDICT = {
    "verdict": "undetermined",
    "explanation": "The passages do not mention this.",
    "cited_passage_ids": [],
}


class TaskAwareProvider:
    """Answers each task with a valid, plausible object and reports estimated token usage."""

    name = "groq"
    model = "scripted"

    def __init__(self, verdict: str = "supported_by_policy", cite: bool = True) -> None:
        self.requests: list[ProviderRequest] = []
        self.verdict = verdict
        self.cite = cite

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        user = json.loads(request.user.removeprefix("<data>\n").removesuffix("\n</data>"))
        if request.schema_name == "suggest_purpose_and_basis":
            answer: dict[str, Any] = {
                "purposes": user["declared_purposes"][:3] or ["Service delivery"],
                "lawful_basis": "contract",
                "basis_rationale": "The processing is needed to provide the service the person asked for.",
                "needs_review": bool(user["special_categories"]),
            }
        else:
            ids = [p["id"] for p in user["passages"]][:1] if self.cite else []
            answer = {
                "verdict": (
                    self.verdict if ids or self.verdict == "undetermined" else "undetermined"
                ),
                "explanation": "The retrieved policy text addresses this statement.",
                "cited_passage_ids": ids,
            }
        text = json.dumps(answer)
        return ProviderResponse(
            text, estimate_tokens(request.system) + estimate_tokens(request.user),
            estimate_tokens(text), 0, self.model, RateInfo(),
        )  # fmt: skip
