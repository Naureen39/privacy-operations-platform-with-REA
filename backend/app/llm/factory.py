"""Build the router from settings. Providers without an API key are simply not registered."""

from collections.abc import Callable

import httpx
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.session import TenantSession
from app.llm.budget import BudgetPolicy
from app.llm.providers import GeminiProvider, GroqProvider, Provider
from app.llm.router import LLMRouter, ProviderLimits


def build_router(
    settings: Settings,
    session_factory: Callable[[], sessionmaker[TenantSession]],
    client: httpx.Client | None = None,
) -> LLMRouter:
    providers: dict[str, Provider] = {}
    if settings.groq_api_key is not None:
        providers["groq"] = GroqProvider(
            settings.groq_api_key.get_secret_value(),
            settings.groq_model,
            settings.groq_base_url,
            client,
            settings.llm_timeout_seconds,
        )
    if settings.gemini_api_key is not None:
        providers["gemini"] = GeminiProvider(
            settings.gemini_api_key.get_secret_value(),
            settings.gemini_model,
            settings.gemini_base_url,
            client,
            settings.llm_timeout_seconds,
        )
    return LLMRouter(
        providers,
        session_factory,
        policy=BudgetPolicy(request_cap=settings.llm_request_token_cap),
        limits={
            "groq": ProviderLimits(
                settings.groq_tokens_per_minute, settings.groq_requests_per_minute
            ),
            "gemini": ProviderLimits(
                settings.gemini_tokens_per_minute, settings.gemini_requests_per_minute
            ),
        },
        max_output_tokens=settings.llm_max_output_tokens,
        attempts_per_provider=settings.llm_attempts_per_provider,
    )
