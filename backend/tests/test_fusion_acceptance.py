"""Phase 8 acceptance for the comparison: at least 90 percent of the seeded contradictions are found
with precision of at least 85 percent, on the reference estate taken through discovery and
classification. The model is scripted; the rules do the finding."""

import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.config import Settings
from app.fusion.evaluation import SCORED_TYPES, load_seeded, score
from app.llm.router import LLMRouter, ProviderLimits
from app.main import create_app
from tests.fixtures_api import client_for, csrf
from tests.fixtures_fusion import ESTATE, FusionEstate, upload_notice_and_questionnaire
from tests.llm_support import FakeClock, TaskAwareProvider
from tests.test_discovery_api import create_system, run_discovery, upload_estate_system

# Findings the rules report that the dataset does not list. Each is a real inconsistency of the
# estate or a known classifier miss, and each is reviewed below.
KNOWN_EXTRAS = {
    ("newsletter", "policy_contradiction"),  # the notice promises not to share beyond MailSend
    (
        "staff_desktop",
        "policy_contradiction",
    ),  # the notice promises not to share outside the company
    (
        "crm",
        "element_not_in_policy",
    ),  # 'amount' and 'lead_source' classified as purchase history and preferences
}


def test_recall_and_precision_against_the_seeded_contradictions(
    fusion_estate: FusionEstate,
) -> None:
    result = score(fusion_estate.pairs())
    print(
        f"\n[fusion] contradictions found {result.found_ids}/{result.seeded_ids} "
        f"({result.recall:.0%}), expected finding types {result.true_pairs}/{result.seeded_pairs}, "
        f"precision {result.precision:.1%} ({result.true_pairs} of {result.reported_pairs} reported), "
        f"extras {result.extra}"
    )
    assert result.seeded_ids == 19
    assert result.recall >= 0.90, result.missed
    assert result.pair_recall >= 0.90
    assert result.precision >= 0.85, result.extra
    assert set(result.extra) <= KNOWN_EXTRAS, "a new unseeded finding appeared: review it"


def test_every_seeded_contradiction_is_found_with_every_expected_type(
    fusion_estate: FusionEstate,
) -> None:
    reported = fusion_estate.pairs()
    for cid, pairs in load_seeded().items():
        assert pairs <= reported, (cid, pairs - reported)


def test_each_finding_has_a_severity_a_fix_and_evidence_that_exists(
    fusion_estate: FusionEstate, owner_engine: Engine
) -> None:
    findings = [
        f
        for f in fusion_estate.findings(status="open")
        if f["type"] in SCORED_TYPES | {"retention_review"}
    ]
    assert len(findings) > 25
    with owner_engine.connect() as conn:
        discovery_ids = {
            str(r[0])
            for r in conn.execute(
                text("SELECT id FROM discovery_evidence WHERE org_id = :o"),
                {"o": fusion_estate.org_id},
            )
        }
        evidence_ids = {
            str(r[0])
            for r in conn.execute(
                text("SELECT id FROM evidence_items WHERE org_id = :o"), {"o": fusion_estate.org_id}
            )
        }
        document_ids = {
            str(r[0])
            for r in conn.execute(
                text("SELECT id FROM documents WHERE org_id = :o"), {"o": fusion_estate.org_id}
            )
        }
    for f in findings:
        assert (
            f["severity"] in {"low", "medium", "high", "critical"}
            and f["suggested_fix"]
            and f["description"]
        )
        assert f["evidence_refs"], f["title"]
        for ref in f["evidence_refs"]:
            assert (
                ref["kind"] in {"discovery", "questionnaire", "policy", "company_policy"}
                and ref["detail"]
            )
            known = {
                "discovery": discovery_ids,
                "questionnaire": evidence_ids,
                "policy": evidence_ids,
                "company_policy": document_ids,
            }[ref["kind"]]
            assert ref["id"] in known, (f["title"], ref)


def test_specific_findings_have_the_expected_content(fusion_estate: FusionEstate) -> None:
    def one(estate_id: str, type_: str, containing: str) -> dict[str, Any]:
        found = [
            f
            for f in fusion_estate.findings(estate_id, type=type_, status="open")
            if containing.lower() in (f["title"] + f["description"]).lower()
        ]
        assert found, (estate_id, type_, containing)
        return found[0]

    assert one("web_shop", "third_country_no_safeguard", "Meta")["severity"] == "high"
    assert "84 months" in one("web_shop", "retention_conflict", "company limit")["title"]
    assert "2022" in one("helpdesk", "retention_conflict", "conversations")["description"]
    assert "full IP address" in one("web_analytics", "policy_contradiction", "IP")["title"]
    assert one("clinic_portal", "stale_review", "2023-02-01")["severity"] == "low"
    assert one("clinic_portal", "missing_art9_condition", "health")["severity"] == "critical"
    assert "consent_marketing" in one("newsletter", "consent_defect", "ticked")["title"]
    assert one("crm", "missing_retention", "retention")["severity"] == "medium"
    assert (
        "trade union"
        in one("hr_onboarding", "missing_art9_condition", "trade union")["description"]
    )


def test_systems_with_nothing_wrong_in_the_rules_get_no_invented_findings(
    fusion_estate: FusionEstate,
) -> None:
    open_types = {t for s, t in fusion_estate.pairs() if s == "hr_onboarding"}
    assert open_types <= {
        "missing_art9_condition",
        "cookie_not_in_policy",
        "special_category_review",
        "low_confidence_classification",
    }


def test_ambiguous_retention_goes_to_the_model_once_and_never_again(
    fusion_estate: FusionEstate,
) -> None:
    summaries = fusion_estate.summaries
    asked = {e for e, s in summaries.items() if s["adjudicated"]}
    assert asked == {"clinic_portal", "staff_desktop", "web_analytics"}
    assert all(0 < summaries[e]["tokens_used"] < 800 for e in asked)
    review = fusion_estate.findings("clinic_portal", type="retention_review")
    assert (
        len(review) == 1
        and "Assessment" in review[0]["description"]
        and review[0]["severity"] == "low"
    )
    # the same question for the same evidence is a cache hit
    before = len(fusion_estate.provider.requests)
    admin = fusion_estate.admin
    again = admin.post(
        f"/api/v1/systems/{fusion_estate.systems['clinic_portal']}/fusion", headers=csrf(admin)
    ).json()
    assert again["adjudicated"] == 1 and again["tokens_used"] == 0
    assert len(fusion_estate.provider.requests) == before


def test_running_the_comparison_again_changes_nothing(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    before = sorted((f["id"], f["type"], f["status"]) for f in fusion_estate.findings())
    for sid in fusion_estate.systems.values():
        assert admin.post(f"/api/v1/systems/{sid}/fusion", headers=csrf(admin)).status_code == 200
    after = sorted((f["id"], f["type"], f["status"]) for f in fusion_estate.findings())
    assert before == after


def test_a_dismissed_finding_stays_dismissed(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    finding = fusion_estate.findings("clinic_portal", type="stale_review", status="open")[0]
    patched = admin.patch(
        f"/api/v1/findings/{finding['id']}", json={"status": "dismissed"}, headers=csrf(admin)
    )
    assert patched.status_code == 200 and patched.json()["status"] == "dismissed"
    admin.post(
        f"/api/v1/systems/{fusion_estate.systems['clinic_portal']}/fusion", headers=csrf(admin)
    )
    after = fusion_estate.findings("clinic_portal", type="stale_review")
    assert [f["status"] for f in after] == ["dismissed"]
    admin.patch(f"/api/v1/findings/{finding['id']}", json={"status": "open"}, headers=csrf(admin))
    assert fusion_estate.findings("clinic_portal", type="stale_review", status="open")


def pipeline(client: TestClient, estate_id: str, owner: Any, name: str) -> str:
    system_id = create_system(client, name, owner=owner)
    upload_estate_system(client, system_id, estate_id)
    upload_notice_and_questionnaire(client, system_id, estate_id)
    run_discovery(client, system_id)
    assert (
        client.post(f"/api/v1/systems/{system_id}/classification", headers=csrf(client)).status_code
        == 200
    )
    return system_id


def fuse(client: TestClient, system_id: str) -> dict[str, Any]:
    response = client.post(f"/api/v1/systems/{system_id}/fusion", headers=csrf(client))
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_fixing_the_problem_closes_the_finding(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    system_id = pipeline(admin, "hr_onboarding", fusion_estate.users["system_owner"].id, "HR copy")
    fuse(admin, system_id)
    open_now = admin.get(
        "/api/v1/findings",
        params={"system_id": system_id, "status": "open", "type": "missing_art9_condition"},
    ).json()
    assert len(open_now) == 1

    fixed = json.loads(
        (ESTATE / "hr_onboarding" / "questionnaire.json").read_text(encoding="utf-8")
    )
    fixed["answers"][
        "special_category_condition"
    ] = "Art. 9(2)(b) employment and social security law"
    response = admin.post(
        f"/api/v1/systems/{system_id}/evidence", data={"kind": "questionnaire"},
        files={"file": ("questionnaire.json", json.dumps(fixed).encode(), "application/json")}, headers=csrf(admin),
    )  # fmt: skip
    assert response.status_code == 201
    fuse(admin, system_id)
    closed = admin.get(
        "/api/v1/findings", params={"system_id": system_id, "type": "missing_art9_condition"}
    ).json()
    assert [f["status"] for f in closed] == ["resolved"]


def test_the_model_can_confirm_a_conflict_and_the_rules_stay_in_charge(
    fusion_estate: FusionEstate, session_factory: Any, settings: Settings
) -> None:
    provider = TaskAwareProvider(verdict="contradicts_policy")
    clock = FakeClock()
    router = LLMRouter(
        {"groq": provider},
        lambda: session_factory,
        clock=clock,
        sleep=clock.sleep,
        limits={"groq": ProviderLimits(10_000_000, 10_000)},
    )
    app = create_app(
        fusion_estate.app.state.settings,
        session_factory,
        embedder=fusion_estate.app.state.embedder,
        llm_router=router,
    )
    admin = client_for(app, fusion_estate.users["admin"])
    system_id = pipeline(
        admin, "staff_desktop", fusion_estate.users["system_owner"].id, "Desktop copy"
    )
    summary = fuse(admin, system_id)
    assert summary["adjudicated"] == 1 and provider.requests
    conflicts = admin.get(
        "/api/v1/findings", params={"system_id": system_id, "type": "retention_conflict"}
    ).json()
    assert (
        len(conflicts) == 1
        and "Assessment" in conflicts[0]["description"]
        and "72 months" in conflicts[0]["title"]
    )
    assert not admin.get(
        "/api/v1/findings", params={"system_id": system_id, "type": "retention_review"}
    ).json()
    # what the model saw: the clause and the question, no personal data, three passages at most
    sent = json.loads(provider.requests[0].user.removeprefix("<data>\n").removesuffix("\n</data>"))
    assert len(sent["passages"]) <= 3 and "24 months" in sent["passages"][0]["text"]


def test_without_a_provider_the_conflict_stays_a_review_item(
    fusion_estate: FusionEstate, session_factory: Any
) -> None:
    clock = FakeClock()
    router = LLMRouter({}, lambda: session_factory, clock=clock, sleep=clock.sleep)
    app = create_app(
        fusion_estate.app.state.settings,
        session_factory,
        embedder=fusion_estate.app.state.embedder,
        llm_router=router,
    )
    admin = client_for(app, fusion_estate.users["admin"])
    system_id = pipeline(
        admin, "web_analytics", fusion_estate.users["system_owner"].id, "Analytics copy"
    )
    summary = fuse(admin, system_id)
    assert (
        summary["adjudicated"] == 0
        and summary["adjudication_pending"] == 1
        and summary["tokens_used"] == 0
    )
    review = admin.get(
        "/api/v1/findings", params={"system_id": system_id, "type": "retention_review"}
    ).json()
    assert len(review) == 1 and "a person should decide" in review[0]["description"]


def test_the_comparison_needs_a_classified_system(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    system_id = create_system(admin, "Empty", owner=fusion_estate.users["system_owner"].id)
    assert admin.post(f"/api/v1/systems/{system_id}/fusion", headers=csrf(admin)).status_code == 409


def test_system_owners_see_only_the_findings_of_their_systems(
    fusion_estate: FusionEstate, owner_engine: Engine
) -> None:
    admin = fusion_estate.admin
    other = create_system(admin, "Someone else's", owner=fusion_estate.users["analyst"].id)
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO findings (id, org_id, system_id, type, severity, title, status, evidence_refs, dedupe_key) "
                "VALUES (:i, :o, :s, 'stale_review', 'low', 'Hidden', 'open', '[]', :k)"
            ),
            {"i": uuid.uuid4(), "o": fusion_estate.org_id, "s": other, "k": f"test:{other}"},
        )
    owner = client_for(fusion_estate.app, fusion_estate.users["system_owner"])
    titles = {f["title"] for f in owner.get("/api/v1/findings", params={"limit": 1000}).json()}
    assert "Hidden" not in titles and len(titles) > 20
    assert owner.get("/api/v1/findings", params={"system_id": other}).status_code == 404
    assert any(
        f["title"] == "Hidden" for f in admin.get("/api/v1/findings", params={"limit": 1000}).json()
    )
    hidden = admin.get("/api/v1/findings", params={"system_id": other}).json()[0]
    assert (
        owner.patch(
            f"/api/v1/findings/{hidden['id']}", json={"status": "dismissed"}, headers=csrf(owner)
        ).status_code
        == 403
    )
    viewer = client_for(fusion_estate.app, fusion_estate.users["viewer"])
    assert (
        viewer.patch(
            f"/api/v1/findings/{hidden['id']}", json={"status": "dismissed"}, headers=csrf(viewer)
        ).status_code
        == 403
    )
    analyst = client_for(fusion_estate.app, fusion_estate.users["analyst"])
    assert (
        analyst.patch(
            f"/api/v1/findings/{hidden['id']}",
            json={"status": "acknowledged"},
            headers=csrf(analyst),
        ).status_code
        == 200
    )


@pytest.mark.parametrize("status", ["bogus", "", None])
def test_invalid_finding_status_is_refused(fusion_estate: FusionEstate, status: Any) -> None:
    admin = fusion_estate.admin
    finding = fusion_estate.findings("web_shop")[0]
    assert (
        admin.patch(
            f"/api/v1/findings/{finding['id']}", json={"status": status}, headers=csrf(admin)
        ).status_code
        == 422
    )
