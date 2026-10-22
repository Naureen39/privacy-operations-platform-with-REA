"""LLM usage and connection test routes."""

from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.session import TenantSession
from app.llm.errors import ProviderError
from app.llm.factory import build_router
from app.llm.router import LLMRouter
from app.main import create_app
from tests.fixtures_api import Org, client_for, csrf
from tests.llm_support import PURPOSE_ANSWER, FakeClock, FakeProvider, ScriptedTransport

PAYLOAD = {
    "activity": {"name": "Shop", "description": ""},
    "data_categories": ["name"],
    "special_categories": [],
    "data_subjects": ["customers"],
    "recipients": [],
    "declared_purposes": [],
}


def make(
    settings: Settings,
    factory: sessionmaker[TenantSession],
    *providers: FakeProvider,
) -> tuple[FastAPI, LLMRouter]:
    clock = FakeClock()
    router = LLMRouter(
        {p.name: p for p in providers}, lambda: factory, clock=clock, sleep=clock.sleep
    )
    app = create_app(settings.model_copy(update={"rea_enabled": False}), factory, llm_router=router)
    return app, router


def test_usage_reports_todays_calls_tokens_cache_hits_and_failures(
    settings: Settings, session_factory: sessionmaker[TenantSession], org: Org
) -> None:
    primary = FakeProvider(
        "groq", "openai/gpt-oss-20b", [ProviderError("server", "503")], PURPOSE_ANSWER
    )
    app, router = make(settings, session_factory, primary)
    for _ in range(2):  # the second one is a cache hit
        router.complete_json("suggest_purpose_and_basis", PAYLOAD, org_id=org.id)

    for role in ("admin", "analyst", "viewer"):
        c = client_for(app, org.users[role])
        body = c.get("/api/v1/llm/usage").json()
        assert body["calls"] == 3 and body["cache_hits"] == 1 and body["failed_attempts"] == 1
        assert body["tokens_used"] > 0 and body["org_daily_budget"] == 200_000
        groq = next(r for r in body["by_provider"] if r["key"] == "groq")
        assert groq["calls"] == 2 and groq["errors"] == 1
        task = next(r for r in body["by_task"] if r["key"] == "suggest_purpose_and_basis")
        assert task["calls"] == 3 and task["tokens_in"] > 0
        states = {p["provider"]: p for p in body["providers"]}
        assert states["groq"]["configured"] and states["groq"]["circuit"] == "closed"
        assert states["gemini"]["configured"] is False
    assert client_for(app, org.users["system_owner"]).get("/api/v1/llm/usage").status_code == 403


def test_usage_is_per_organisation(
    settings: Settings, session_factory: sessionmaker[TenantSession], org: Org, other_org: Org
) -> None:
    app, router = make(settings, session_factory, FakeProvider("groq", default=PURPOSE_ANSWER))
    router.complete_json("suggest_purpose_and_basis", PAYLOAD, org_id=org.id)
    stranger = client_for(app, other_org.users["admin"])
    assert stranger.get("/api/v1/llm/usage").json()["calls"] == 0


def test_test_connection_pings_each_configured_provider(
    settings: Settings, session_factory: sessionmaker[TenantSession], org: Org
) -> None:
    good = FakeProvider("groq", "openai/gpt-oss-20b", default={"ok": True})
    bad = FakeProvider(
        "gemini", "gemini-2.5-flash-lite", default=ProviderError("auth", "bad key", 401)
    )
    app, _ = make(settings, session_factory, good, bad)
    admin = client_for(app, org.users["admin"])
    response = admin.post("/api/v1/llm/test-connection", headers=csrf(admin))
    assert response.status_code == 200, response.text
    results = {r["provider"]: r for r in response.json()}
    assert results["groq"]["ok"] is True and results["gemini"]["ok"] is False
    assert "bad key" in results["gemini"]["error"]
    assert good.requests[0].max_tokens == 20
    usage = admin.get("/api/v1/llm/usage").json()
    assert usage["calls"] == 2 and usage["failed_attempts"] == 1
    actions = {e["action"] for e in admin.get("/api/v1/audit-log").json()}
    assert "llm.test_connection" in actions
    for role in ("analyst", "viewer", "system_owner"):
        c = client_for(app, org.users[role])
        assert c.post("/api/v1/llm/test-connection", headers=csrf(c)).status_code == 403


def test_without_keys_no_provider_is_registered(tmp_path: Path, settings: Settings) -> None:
    router = build_router(settings, lambda: None)  # type: ignore[arg-type, return-value]
    assert router.providers == {}


def test_keys_build_both_providers_and_stay_out_of_reprs(settings: Settings) -> None:
    from pydantic import SecretStr

    configured = settings.model_copy(
        update={
            "groq_api_key": SecretStr("gsk_secret_value"),
            "gemini_api_key": SecretStr("AIza_secret_value"),
        }
    )
    router = build_router(configured, lambda: None)  # type: ignore[arg-type, return-value]
    assert set(router.providers) == {"groq", "gemini"}
    assert router.providers["groq"].model == "openai/gpt-oss-20b"
    assert "gsk_secret_value" not in repr(configured) and "AIza_secret_value" not in str(configured)


def test_router_built_from_settings_talks_to_recorded_responses(
    settings: Settings, session_factory: sessionmaker[TenantSession], org: Org
) -> None:
    """Groq answers 429, Gemini answers: the real adapters, replayed from recorded responses."""
    import httpx
    from pydantic import SecretStr

    groq_transport = ScriptedTransport("groq_429")
    gemini_transport = ScriptedTransport("gemini_ok")

    class Both(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            target = groq_transport if "groq" in request.url.host else gemini_transport
            return target.handle_request(request)

    configured = settings.model_copy(
        update={"groq_api_key": SecretStr("k1"), "gemini_api_key": SecretStr("k2")}
    )
    router = build_router(configured, lambda: session_factory, httpx.Client(transport=Both()))
    clock = FakeClock()
    router.clock, router.sleep = clock, clock.sleep
    result = router.complete_json("suggest_purpose_and_basis", PAYLOAD, org_id=org.id)
    assert result.provider == "gemini" and result.data.lawful_basis == "contract"  # type: ignore[attr-defined]
    assert len(groq_transport.requests) == 2  # one retry after the 429, then failover
    sent = gemini_transport.bodies()[0]
    assert sent["generationConfig"]["temperature"] == 0
    assert "k2" not in str(gemini_transport.requests[0].url)
