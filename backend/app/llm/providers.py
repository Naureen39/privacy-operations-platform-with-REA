"""Provider adapters. Both speak HTTPS through httpx (a transport can be injected, which is how the
tests replay recorded responses), send temperature 0 and a JSON schema, and report real token usage.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.llm.errors import ProviderError
from app.llm.limits import parse_duration


@dataclass(frozen=True)
class ProviderRequest:
    system: str
    user: str
    schema: dict[str, Any]
    schema_name: str
    max_tokens: int
    repair: str | None = None  # appended after the user message when repairing an invalid answer


@dataclass
class RateInfo:
    remaining_tokens: int | None = None
    remaining_requests: int | None = None
    retry_after: float | None = None


@dataclass
class ProviderResponse:
    text: str
    tokens_in: int
    tokens_out: int
    cached_tokens: int = 0
    model: str = ""
    rate: RateInfo = field(default_factory=RateInfo)


class Provider(Protocol):
    name: str
    model: str

    def complete(self, request: ProviderRequest) -> ProviderResponse: ...


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    retry_after = parse_duration(response.headers.get("retry-after"))
    detail = ""
    try:
        body = response.json()
        detail = (
            str(body.get("error", {}).get("message", ""))[:200] if isinstance(body, dict) else ""
        )
    except ValueError:
        pass
    if status == 429:
        raise ProviderError("rate_limit", detail or "rate limited", status, retry_after)
    if status in (401, 403):
        raise ProviderError("auth", "the provider refused the credentials", status)
    if status == 408:
        raise ProviderError("timeout", detail or "request timeout", status)
    if status >= 500:
        raise ProviderError("server", detail or f"server error {status}", status, retry_after)
    raise ProviderError("bad_request", detail or f"request rejected ({status})", status)


class _HttpProvider:
    name = ""
    model = ""

    def __init__(self, client: httpx.Client | None, timeout: float) -> None:
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=False)

    def _post(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> httpx.Response:
        try:
            response = self._client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", type(exc).__name__) from exc
        except httpx.TransportError as exc:
            raise ProviderError("network", type(exc).__name__) from exc
        _raise_for_status(response)
        return response


class GroqProvider(_HttpProvider):
    """OpenAI compatible chat completions with strict JSON schema output."""

    name = "groq"

    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-oss-20b",
        base_url: str = "https://api.groq.com/openai/v1",
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(client, timeout)
        self._key = api_key
        self.model = model
        self._url = f"{base_url.rstrip('/')}/chat/completions"

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        messages = [
            {"role": "system", "content": request.system},
            {"role": "user", "content": request.user},
        ]
        if request.repair:
            messages.append({"role": "user", "content": request.repair})
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_completion_tokens": request.max_tokens,
            "reasoning_effort": "low",
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "strict": True,
                    "schema": request.schema,
                },
            },
        }
        response = self._post(self._url, {"Authorization": f"Bearer {self._key}"}, body)
        data = _json(response)
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("server", "unexpected response shape") from exc
        usage = data.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        headers = response.headers
        return ProviderResponse(
            text=text,
            tokens_in=_int(usage.get("prompt_tokens")) or 0,
            tokens_out=_int(usage.get("completion_tokens")) or 0,
            cached_tokens=_int(details.get("cached_tokens")) or 0,
            model=str(data.get("model") or self.model),
            rate=RateInfo(
                remaining_tokens=_int(headers.get("x-ratelimit-remaining-tokens")),
                remaining_requests=_int(headers.get("x-ratelimit-remaining-requests")),
            ),
        )


class GeminiProvider(_HttpProvider):
    """Google Gemini `generateContent` with a response JSON schema. The key travels in a header,
    never in the URL, so it cannot end up in access logs."""

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://generativelanguage.googleapis.com",
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(client, timeout)
        self._key = api_key
        self.model = model
        self._url = f"{base_url.rstrip('/')}/v1beta/models/{model}:generateContent"

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        contents = [{"role": "user", "parts": [{"text": request.user}]}]
        if request.repair:
            contents.append({"role": "user", "parts": [{"text": request.repair}]})
        body = {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": contents,
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": request.max_tokens,
                "responseMimeType": "application/json",
                "responseJsonSchema": request.schema,
            },
        }
        response = self._post(self._url, {"x-goog-api-key": self._key}, body)
        data = _json(response)
        try:
            candidate = data["candidates"][0]
        except (KeyError, IndexError, TypeError) as exc:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise ProviderError("bad_request", f"no answer ({reason})") from exc
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        if candidate.get("finishReason") in ("SAFETY", "RECITATION") and not text:
            raise ProviderError("bad_request", f"blocked ({candidate['finishReason']})")
        usage = data.get("usageMetadata") or {}
        return ProviderResponse(
            text=text,
            tokens_in=_int(usage.get("promptTokenCount")) or 0,
            tokens_out=(_int(usage.get("candidatesTokenCount")) or 0)
            + (_int(usage.get("thoughtsTokenCount")) or 0),
            cached_tokens=_int(usage.get("cachedContentTokenCount")) or 0,
            model=str(data.get("modelVersion") or self.model),
        )


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise ProviderError("server", "the provider returned something that is not JSON") from exc
    if not isinstance(data, dict):
        raise ProviderError("server", "unexpected response shape")
    return data
