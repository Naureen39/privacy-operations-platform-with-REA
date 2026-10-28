"""What the console added to the API: the team, organization switching and the dashboard
breakdowns."""

import uuid
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.analytics import revenue_breakdown
from app.analytics.revenue_breakdown import Inputs, OrgInfo, PlanSub
from app.db.enums import EvidenceKind, Role
from app.db.models import (
    DataElement,
    DiscoveryEvidence,
    DiscoveryRun,
    EvidenceItem,
    Recipient,
    System,
)
from app.db.session import TenantContext, TenantSession, tenant_session
from app.seeding import compliance_history
from app.services import provisioning
from tests.fixtures_api import PASSWORD, Org, client_for, csrf

# -- team ----------------------------------------------------------------------------------------


def test_the_team_list_is_for_administrators_and_shows_only_this_organization(
    app: FastAPI, org: Org, other_org: Org
) -> None:
    admin = client_for(app, org.users["admin"])
    members = admin.get("/api/v1/team")
    assert members.status_code == 200 and int(members.headers["x-total-count"]) == 4
    by_role = {m["role"]: m for m in members.json()}
    assert set(by_role) == {"admin", "analyst", "system_owner", "viewer"}
    assert by_role["admin"]["is_you"] is True and by_role["analyst"]["is_you"] is False
    assert all(not m["email"].endswith("@globex.example") for m in members.json())
    assert client_for(app, org.users["analyst"]).get("/api/v1/team").status_code == 403


def test_an_administrator_changes_a_role_and_it_is_audited(app: FastAPI, org: Org) -> None:
    admin = client_for(app, org.users["admin"])
    target = org.users["viewer"].id
    changed = admin.patch(f"/api/v1/team/{target}", json={"role": "analyst"}, headers=csrf(admin))
    assert changed.status_code == 200 and changed.json()["role"] == "analyst"
    log = admin.get("/api/v1/audit-log", params={"limit": 200}).json()
    assert any(e["action"] == "team.role_changed" and e["entity_id"] == str(target) for e in log)
    own = admin.patch(
        f"/api/v1/team/{org.users['admin'].id}", json={"role": "viewer"}, headers=csrf(admin)
    )
    assert own.status_code == 409
    assert (
        admin.patch(
            f"/api/v1/team/{uuid.uuid4()}", json={"role": "viewer"}, headers=csrf(admin)
        ).status_code
        == 404
    )
    assert (
        admin.patch(
            f"/api/v1/team/{target}", json={"role": "owner"}, headers=csrf(admin)
        ).status_code
        == 422
    )


def test_removing_a_member_keeps_the_last_administrator_and_ends_their_access(
    app: FastAPI, org: Org
) -> None:
    admin = client_for(app, org.users["admin"])
    viewer = client_for(app, org.users["viewer"])
    assert viewer.get("/api/v1/systems").status_code == 200
    assert (
        admin.delete(f"/api/v1/team/{org.users['viewer'].id}", headers=csrf(admin)).status_code
        == 204
    )
    assert viewer.get("/api/v1/systems").status_code == 401  # the membership is re-read every time
    assert len(admin.get("/api/v1/team").json()) == 3
    assert (
        admin.delete(f"/api/v1/team/{org.users['admin'].id}", headers=csrf(admin)).status_code
        == 409
    )


def test_the_last_administrator_cannot_be_removed_by_another_administrator(
    app: FastAPI, org: Org, owner_engine: Engine
) -> None:
    admin = client_for(app, org.users["admin"])
    second = provisioning.create_user(
        owner_engine,
        org.id,
        f"second-{uuid.uuid4().hex[:6]}@acme.example",
        "Second",
        PASSWORD,
        Role.ADMIN,
    )
    assert admin.delete(f"/api/v1/team/{second.id}", headers=csrf(admin)).status_code == 204
    # only one administrator is left, and it is the caller, who cannot remove themselves
    assert (
        admin.delete(f"/api/v1/team/{org.users['admin'].id}", headers=csrf(admin)).status_code
        == 409
    )


# -- organization switching ----------------------------------------------------------------------


@pytest.fixture
def two_org_user(owner_engine: Engine, org: Org, other_org: Org) -> str:
    email = f"both-{uuid.uuid4().hex[:6]}@multi.example"
    provisioning.create_user(owner_engine, org.id, email, "Both Orgs", PASSWORD, Role.ANALYST)
    provisioning.create_user(owner_engine, other_org.id, email, "Both Orgs", PASSWORD, Role.VIEWER)
    return email


def test_a_person_in_two_organizations_can_list_and_switch(
    app: FastAPI, org: Org, other_org: Org, two_org_user: str
) -> None:
    from fastapi.testclient import TestClient

    from tests.fixtures_api import login

    client = TestClient(app, base_url="https://testserver")
    first = login(client, two_org_user, org_id=org.id)
    assert first.status_code == 200 and first.json()["role"] == "analyst"
    choices = client.get("/api/v1/auth/organizations").json()
    assert {c["name"] for c in choices} == {"Acme", "Globex"}
    assert [c["current"] for c in choices if c["org_id"] == str(org.id)] == [True]
    old_refresh = client.cookies.get("pl_refresh", path="/api/v1/auth")

    switched = client.post(
        "/api/v1/auth/switch", json={"org_id": str(other_org.id)}, headers=csrf(client)
    )
    assert switched.status_code == 200 and switched.json()["role"] == "viewer"
    me = client.get("/api/v1/auth/me").json()
    assert me["org_id"] == str(other_org.id) and me["role"] == "viewer"
    # the role of the new organization applies at once
    assert (
        client.post("/api/v1/systems", json={"name": "x"}, headers=csrf(client)).status_code == 403
    )
    # the token of the previous session no longer refreshes
    stale = TestClient(app, base_url="https://testserver")
    stale.cookies.set("pl_refresh", old_refresh or "", path="/api/v1/auth")
    stale.cookies.set("pl_csrf", "x")
    assert stale.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": "x"}).status_code == 401
    log = [
        e["action"]
        for e in client_for(app, other_org.users["admin"])
        .get("/api/v1/audit-log", params={"limit": 200})
        .json()
    ]
    assert "auth.switch_organization" in log


def test_switching_to_an_organization_you_do_not_belong_to_is_refused(
    app: FastAPI, org: Org, other_org: Org
) -> None:
    admin = client_for(app, org.users["admin"])
    refused = admin.post(
        "/api/v1/auth/switch", json={"org_id": str(other_org.id)}, headers=csrf(admin)
    )
    assert refused.status_code == 403
    assert admin.get("/api/v1/auth/me").json()["org_id"] == str(org.id)


# -- compliance breakdown ------------------------------------------------------------------------


def test_the_compliance_breakdown_is_built_from_the_organizations_rows(
    app: FastAPI, org: Org, session_factory: sessionmaker[TenantSession]
) -> None:
    today = date.today()
    with tenant_session(session_factory, TenantContext(org_id=org.id)) as db:
        summary = compliance_history.seed_compliance_history(db, seed=7, as_of=today, months=4)
        system = System(name="Web shop", slug="web-shop")
        db.add(system)
        db.flush()
        item = EvidenceItem(
            system_id=system.id, kind=EvidenceKind.HAR, filename="cap.har", storage_path="x",
            checksum_sha256="0" * 64, size_bytes=1,
        )  # fmt: skip
        run = DiscoveryRun(system_id=system.id)
        db.add_all([item, run])
        db.flush()
        found = DiscoveryEvidence(
            run_id=run.id, evidence_item_id=item.id, extractor="rea", duration_ms=1200
        )
        db.add(found)
        db.flush()
        db.add_all(
            [
                Recipient(
                    evidence_id=found.id,
                    system_id=system.id,
                    domain="ads.example",
                    vendor="AdCo",
                    country="US",
                    role="processor",
                ),
                Recipient(
                    evidence_id=found.id,
                    system_id=system.id,
                    domain="mail.example",
                    vendor="MailEU",
                    country="DE",
                    role="processor",
                ),
                Recipient(
                    evidence_id=found.id,
                    system_id=system.id,
                    domain="safe.example",
                    vendor="SafeCo",
                    country="US",
                    role="processor",
                    safeguard="SCC",
                ),
                DataElement(
                    system_id=system.id,
                    name="email",
                    category="contact_email",
                    confidence=0.95,
                    evidence_id=found.id,
                ),
                DataElement(
                    system_id=system.id,
                    name="phone",
                    category="contact_phone",
                    confidence=0.55,
                    evidence_id=found.id,
                ),
                DataElement(
                    system_id=system.id,
                    name="weird",
                    category="contact_email",
                    confidence=0.72,
                    evidence_id=found.id,
                ),
            ]
        )
    admin = client_for(app, org.users["admin"])
    params = {"start": str(today - timedelta(days=100)), "end": str(today), "granularity": "month"}
    body = admin.get("/api/v1/analytics/compliance/breakdown", params=params).json()

    flow = body["findings"]
    assert sum(flow["opened"]) > 0 and len(flow["periods"]) == len(flow["opened"]) == len(
        flow["closed"]
    )
    assert flow["net"] == [o - c for o, c in zip(flow["opened"], flow["closed"], strict=True)]
    assert sum(flow["open_by_severity"].values()) == sum(flow["open_by_type"].values())
    assert sum(body["lawful_bases"].values()) == summary.activities
    heat = body["category_heatmap"]
    assert heat["systems"] == ["Web shop"] and {c[1] for c in heat["cells"]} == {
        "contact_email",
        "contact_phone",
    }
    assert [c[2] for c in heat["cells"] if c[1] == "contact_email"] == [2]
    flows = body["data_flow"]
    assert flows["gaps"] == [
        "AdCo"
    ]  # a US vendor with no safeguard; SafeCo has one, MailEU is in the EEA
    kinds = {n["name"]: n["kind"] for n in flows["nodes"]}
    assert kinds["Web shop"] == "system" and kinds["AdCo"] == "vendor" and kinds["US"] == "country"
    assert {(link["source"], link["target"]) for link in flows["links"]} >= {
        ("Web shop", "AdCo"),
        ("AdCo", "US"),
    }
    assert body["confidence"]["0.5-0.6"] == 1 and body["confidence"]["0.9-1.0"] == 1
    assert body["confidence"]["0.7-0.8"] == 1
    req = body["requests"]
    assert req["answered"] > 0 and 0 <= req["on_time_rate"] <= 100
    assert sum(body["freshness"].values()) == summary.activities
    assert body["operations"]["calls"] == 0 and body["operations"]["cache_hit_rate"] is None
    assert set(body["assessments"]) <= {"draft", "in_review", "approved", "rejected"}
    # cached for a minute, and never shared with another organization
    again = admin.get("/api/v1/analytics/compliance/breakdown", params=params)
    assert again.headers["x-cache"] == "hit"
    other = client_for(app, org.users["viewer"]).get(
        "/api/v1/analytics/compliance/breakdown", params=params
    )
    assert (
        other.status_code == 200
        and other.json()["findings"]["opened"] == body["findings"]["opened"]
    )
    assert (
        client_for(app, org.users["system_owner"])
        .get("/api/v1/analytics/compliance/breakdown")
        .status_code
        == 403
    )


def test_an_empty_organization_gets_an_empty_breakdown(app: FastAPI, other_org: Org) -> None:
    admin = client_for(app, other_org.users["admin"])
    body = admin.get("/api/v1/analytics/compliance/breakdown").json()
    assert body["lawful_bases"] == {} and body["data_flow"]["links"] == []
    assert sum(body["findings"]["opened"]) == 0 and body["requests"]["on_time_rate"] is None


# -- revenue breakdown (pure) --------------------------------------------------------------------


def _inputs() -> Inputs:
    inputs = Inputs(
        orgs={
            "a": OrgInfo("Alder Health", "Healthcare", "EU"),
            "b": OrgInfo("Birch Retail", "Retail", "UK"),
            "c": OrgInfo("Cedar Labs", "Technology", "EU"),
        },
        subs=[
            PlanSub("a", "starter", date(2026, 1, 5), date(2026, 3, 1), 0),
            PlanSub("a", "professional", date(2026, 3, 1), None, 39_900),
            PlanSub("b", "professional", date(2026, 1, 20), date(2026, 6, 10), 39_900),
            PlanSub("c", "enterprise", date(2026, 2, 3), None, 180_000),
        ],
        systems={
            "a": [(date(2026, 1, 31), 2), (date(2026, 6, 30), 10)],
            "c": [(date(2026, 2, 28), 100)],
        },
        usage_revenue={"2026-06": 7_500},
        tokens={"2026-06": 220_000},
    )
    return inputs


def test_the_revenue_breakdown_adds_up() -> None:
    out = revenue_breakdown.build(_inputs(), date(2026, 8, 31))
    assert len(out["months"]) == 24 and out["months"][-1] == "2026-08"
    idx = {m: i for i, m in enumerate(out["months"])}
    june = idx["2026-06"]
    plans, industries, regions = out["mrr_by_plan"], out["mrr_by_industry"], out["mrr_by_region"]
    for series in (plans, industries, regions):
        for i in range(24):  # every cut of MRR adds up to the same total
            assert sum(v[i] for v in series.values()) == out["subscription_revenue_cents"][i]
    assert (
        out["subscription_revenue_cents"][idx["2026-02"]] == 39_900 + 180_000
    )  # a: starter 0, b, c
    assert (
        plans["professional"][idx["2026-08"]] == 39_900
    )  # b left on 10 June, a upgraded on 1 March
    assert (
        out["usage_revenue_cents"][june] == 7_500
        and out["usage_revenue_cents"][idx["2026-05"]] == 0
    )
    assert out["accounts"][idx["2026-02"]] == 3 and out["accounts"][idx["2026-08"]] == 2
    assert out["arpa_cents"][idx["2026-08"]] == round((39_900 + 180_000) / 2)
    assert out["revenue_per_system_cents"][june] == round((39_900 + 180_000) / 110)
    assert out["tokens_per_system"][june] == round(220_000 / (10 + 100))


def test_cohorts_start_at_one_hundred_percent_and_follow_who_stays() -> None:
    out = revenue_breakdown.build(_inputs(), date(2026, 8, 31))
    cohorts = out["cohorts"]
    assert cohorts["labels"] == ["2026-01", "2026-02", "2026-03"]  # a's first paid month is March
    assert cohorts["sizes"] == [1, 1, 1]
    for row in cohorts["retention"]:
        assert row[0] == 100
    january = cohorts["retention"][0]  # b, who left in June: months 0 to 4 present, then gone
    assert january[4] == 100 and january[5] == 0
    assert cohorts["retention"][1][3] == 100  # c never leaves


def test_top_customers_are_sorted_with_a_year_of_history() -> None:
    out = revenue_breakdown.build(_inputs(), date(2026, 8, 31))
    top = out["top_customers"]
    assert [t["name"] for t in top] == ["Cedar Labs", "Alder Health"]  # Birch left
    assert top[0]["mrr_cents"] == 180_000 and top[0]["plan"] == "enterprise"
    assert (
        len(top[0]["series"]) == 12 and top[0]["series"][-1] == 180_000 and top[0]["series"][0] == 0
    )


def test_me_says_whether_this_is_the_host_organization(app: FastAPI, org: Org) -> None:
    admin = client_for(app, org.users["admin"])
    assert admin.get("/api/v1/auth/me").json()["is_host"] is False
    app.state.settings.leads_org_id = org.id
    assert admin.get("/api/v1/auth/me").json()["is_host"] is True
