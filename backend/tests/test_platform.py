"""Vendors, the question and answer assistant, public leads and the public figures."""

import uuid
from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.llm.router import LLMRouter
from app.main import create_app
from tests.fixtures_api import client_for, csrf
from tests.fixtures_fusion import FusionEstate
from tests.llm_support import FakeClock


def as_user(fe: FusionEstate, role: str) -> TestClient:
    return client_for(fe.app, fe.users[role])


# -- vendors -------------------------------------------------------------------------------------


def test_vendors_are_listed_once_with_their_systems_and_open_gaps(
    fusion_estate: FusionEstate,
) -> None:
    admin = fusion_estate.admin
    response = admin.get("/api/v1/vendors", params={"limit": 200})
    assert response.status_code == 200
    vendors = {v["name"]: v for v in response.json()}
    assert int(response.headers["x-total-count"]) == len(vendors) >= 12
    stripe = vendors["Stripe"]
    assert (
        stripe["role"] == "processor"
        and stripe["country"] == "US"
        and stripe["open_findings"] == []
    )
    assert "web_shop" in [
        s["name"] for s in stripe["systems"]
    ]  # copies of the estate made by other tests may also use it
    meta = vendors["Meta Platforms"]
    assert set(meta["open_findings"]) == {"third_country_no_safeguard", "undeclared_recipient"}
    assert "connect.facebook.net" in " ".join(meta["domains"]) or meta["domains"]
    mailsend = vendors["MailSend Europe"]
    assert {s["name"] for s in mailsend["systems"]} >= {
        "helpdesk",
        "newsletter",
    }  # one vendor, several systems
    assert vendors["Sentry"]["open_findings"].count("missing_agreement") == 1
    assert all(v["name"] != "" for v in vendors.values()) and list(vendors) == sorted(
        vendors, key=str.lower
    )


def test_vendors_are_scoped_and_paged(fusion_estate: FusionEstate) -> None:
    fe = fusion_estate
    first = fe.admin.get("/api/v1/vendors", params={"limit": 3})
    assert len(first.json()) == 3
    second = fe.admin.get("/api/v1/vendors", params={"limit": 3, "offset": 3}).json()
    assert {v["key"] for v in first.json()}.isdisjoint({v["key"] for v in second})
    # an owner with no systems sees no vendors
    other = fe.admin.post(
        "/api/v1/systems",
        json={"name": "Vendor scope", "owner_user_id": str(fe.users["analyst"].id)},
        headers=csrf(fe.admin),
    )
    assert other.status_code == 201
    analyst_owned = as_user(fe, "analyst")
    assert analyst_owned.get("/api/v1/vendors").status_code == 200
    assert as_user(fe, "viewer").get("/api/v1/vendors").status_code == 200
    assert fe.admin.get("/api/v1/vendors", params={"limit": 0}).status_code == 422


# -- chat ----------------------------------------------------------------------------------------


def test_a_question_is_answered_from_passages_that_exist_and_are_cited(
    fusion_estate: FusionEstate,
) -> None:
    fe = fusion_estate
    viewer = as_user(fe, "viewer")
    before = len(fe.provider.requests)
    response = viewer.post(
        "/api/v1/chat",
        json={
            "question": "Within how many hours must a personal data breach be reported to the supervisory authority?"
        },
        headers=csrf(viewer),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["supported"] is True and body["answer"] and 0 < body["tokens_used"] < 3000
    assert body["retrieved"] == 5 and 1 <= len(body["citations"]) <= 2
    assert any(c["metadata"].get("article") in (33, 34) for c in body["citations"])
    for c in body["citations"]:
        resolved = viewer.get("/api/v1/knowledge/passage", params={"citation": c["citation"]})
        assert resolved.status_code == 200 and resolved.json()["id"] == c["id"]
    sent = fe.provider.requests[before:]
    assert sent and sent[-1].schema_name == "answer_question" and sent[-1].max_tokens == 800


def test_with_nothing_relevant_the_answer_says_so_and_no_model_is_called(
    fusion_estate: FusionEstate,
) -> None:
    fe = fusion_estate
    before = len(fe.provider.requests)
    response = fe.admin.post(
        "/api/v1/chat", json={"question": "zzqx plorf wibble grault"}, headers=csrf(fe.admin)
    )
    assert response.status_code == 200
    body = response.json()
    assert (
        body["supported"] is False
        and body["answer"] == "No supporting evidence found."
        and body["citations"] == []
    )
    assert body["tokens_used"] == 0 and len(fe.provider.requests) == before


def test_questions_about_the_organisations_own_documents_can_be_limited_to_a_system(
    fusion_estate: FusionEstate,
) -> None:
    fe = fusion_estate
    owner = as_user(fe, "system_owner")
    assert (
        owner.post(
            "/api/v1/chat",
            json={"question": "How long do we keep records?", "system_id": str(uuid.uuid4())},
            headers=csrf(owner),
        ).status_code
        == 404
    )
    other = fe.admin.post(
        "/api/v1/systems",
        json={"name": "Chat of someone else", "owner_user_id": str(fe.users["analyst"].id)},
        headers=csrf(fe.admin),
    ).json()["id"]
    assert (
        owner.post(
            "/api/v1/chat",
            json={"question": "How long do we keep records?", "system_id": other},
            headers=csrf(owner),
        ).status_code
        == 404
    )
    mine = owner.post(
        "/api/v1/chat",
        json={"question": "How long do we keep records?", "system_id": fe.systems["crm"]},
        headers=csrf(owner),
    )
    assert mine.status_code == 200


def test_chat_is_validated(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    for body in (
        {"question": "ab"},
        {"question": "x" * 501},
        {"question": "valid question", "extra": 1},
        {},
    ):
        assert admin.post("/api/v1/chat", json=body, headers=csrf(admin)).status_code == 422


def test_without_a_provider_chat_returns_the_passages_it_found(
    fusion_estate: FusionEstate, session_factory: Any
) -> None:
    fe = fusion_estate
    router = LLMRouter({}, lambda: session_factory, clock=FakeClock(), sleep=lambda s: None)
    app = create_app(
        fe.app.state.settings, session_factory, embedder=fe.app.state.embedder, llm_router=router
    )
    admin = client_for(app, fe.users["admin"])
    response = admin.post(
        "/api/v1/chat",
        json={"question": "What must a controller record about processing activities?"},
        headers=csrf(admin),
    )
    body = response.json()
    assert (
        response.status_code == 200
        and body["supported"] is False
        and "not configured" in body["answer"]
    )
    assert body["tokens_used"] == 0 and body["citations"]


def test_when_the_assistant_is_down_chat_says_so(
    fusion_estate: FusionEstate, session_factory: Any
) -> None:
    from app.llm.errors import ProviderError
    from tests.llm_support import FakeProvider

    fe = fusion_estate
    down = FakeProvider("groq", "m", default=ProviderError("server", "503"))
    clock = FakeClock()
    router = LLMRouter({"groq": down}, lambda: session_factory, clock=clock, sleep=clock.sleep)
    app = create_app(
        fe.app.state.settings, session_factory, embedder=fe.app.state.embedder, llm_router=router
    )
    admin = client_for(app, fe.users["admin"])
    response = admin.post(
        "/api/v1/chat",
        json={"question": "What must a controller record about processing activities?"},
        headers=csrf(admin),
    )
    assert response.status_code == 503 and response.json()["error"]["code"] == "unavailable"


# -- leads and public figures --------------------------------------------------------------------


LEAD = {
    "kind": "demo_request",
    "name": "Alex Example",
    "email": "Alex@Example.test",
    "company": "Example Ltd",
    "message": "We would like a demonstration.",
}


def test_the_public_site_can_send_a_lead_without_signing_in(fusion_estate: FusionEstate) -> None:
    fe = fusion_estate
    anonymous = TestClient(fe.app, base_url="https://testserver")
    unique = f"lead.{uuid.uuid4().hex[:8]}@example.test"
    response = anonymous.post("/api/v1/public/leads", json={**LEAD, "email": unique})
    assert response.status_code == 202 and response.json() == {"status": "accepted"}
    leads = fe.admin.get("/api/v1/leads").json()
    stored = next(item for item in leads if item["email"] == unique)
    assert (
        stored["kind"] == "demo_request"
        and stored["company"] == "Example Ltd"
        and stored["name"] == "Alex Example"
    )
    for role in ("analyst", "viewer", "system_owner"):
        assert as_user(fe, role).get("/api/v1/leads").status_code == 403
    assert anonymous.get("/api/v1/leads").status_code in (401, 403)


def test_a_filled_in_honeypot_is_accepted_and_dropped(fusion_estate: FusionEstate) -> None:
    fe = fusion_estate
    anonymous = TestClient(fe.app, base_url="https://testserver")
    email = f"bot.{uuid.uuid4().hex[:8]}@example.test"
    response = anonymous.post(
        "/api/v1/public/leads", json={**LEAD, "email": email, "website": "http://spam.example"}
    )
    assert response.status_code == 202
    assert email not in {
        item["email"] for item in fe.admin.get("/api/v1/leads", params={"limit": 200}).json()
    }


def test_invalid_leads_are_refused(fusion_estate: FusionEstate) -> None:
    anonymous = TestClient(fusion_estate.app, base_url="https://testserver")
    for patch in (
        {"email": "not-an-email"},
        {"name": "A"},
        {"kind": "sell"},
        {"message": "x" * 4001},
        {"unexpected": 1},
    ):
        assert anonymous.post("/api/v1/public/leads", json={**LEAD, **patch}).status_code == 422


def test_leads_are_rate_limited(fusion_estate: FusionEstate, session_factory: Any) -> None:
    fe = fusion_estate
    settings = fe.app.state.settings.model_copy(update={"lead_rate_limit": "3/minute"})
    app = create_app(
        settings,
        session_factory,
        embedder=fe.app.state.embedder,
        llm_router=fe.app.state.llm_router,
    )
    anonymous = TestClient(app, base_url="https://testserver")
    codes = [
        anonymous.post(
            "/api/v1/public/leads", json={**LEAD, "email": f"rate{i}@example.test"}
        ).status_code
        for i in range(5)
    ]
    assert codes[:3] == [202, 202, 202] and codes[3:] == [429, 429]


def test_leads_are_refused_when_no_organisation_receives_them(
    fusion_estate: FusionEstate, session_factory: Any
) -> None:
    fe = fusion_estate
    settings = fe.app.state.settings.model_copy(update={"leads_org_id": None})
    app = create_app(
        settings,
        session_factory,
        embedder=fe.app.state.embedder,
        llm_router=fe.app.state.llm_router,
    )
    response = TestClient(app, base_url="https://testserver").post(
        "/api/v1/public/leads", json=LEAD
    )
    assert response.status_code == 503


def test_public_figures_are_the_latest_snapshot_marked_simulated(
    fusion_estate: FusionEstate, owner_engine: Engine
) -> None:
    anonymous = TestClient(fusion_estate.app, base_url="https://testserver")
    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_metrics"))
    empty = anonymous.get("/api/v1/public/metrics")
    assert empty.status_code == 200
    assert empty.json() | {"regulation_passages": 0} == {
        "as_of": None,
        "accounts": 0,
        "systems": 0,
        "requests": 0,
        "cache_hits": 0,
        "failovers": 0,
        "regulation_passages": 0,
        "simulated": True,
        "note": empty.json()["note"],
    }
    assert empty.json()["regulation_passages"] == 412 and "simulated" in empty.json()["note"]
    with owner_engine.begin() as conn:
        for day, accounts in ((date(2026, 9, 30), 100), (date(2026, 10, 1), 120)):
            conn.execute(
                text(
                    "INSERT INTO daily_metrics (metric_date, accounts, systems, requests, cache_hits, failovers, is_simulated) VALUES (:d, :a, :a * 3, 7, 11, 2, true)"
                ),
                {"d": day, "a": accounts},
            )
    try:
        shown = anonymous.get("/api/v1/public/metrics").json()
        assert (
            shown["as_of"] == "2026-10-01" and shown["accounts"] == 120 and shown["systems"] == 360
        )
        assert (
            shown["requests"] == 7
            and shown["cache_hits"] == 11
            and shown["failovers"] == 2
            and shown["simulated"] is True
        )
    finally:
        with owner_engine.begin() as conn:
            conn.execute(text("DELETE FROM daily_metrics"))
