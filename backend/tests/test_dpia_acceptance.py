"""Phase 9 acceptance: screening matches the rubric on all estate activities, generated assessments
pass the completeness check, every risk cites an article or evidence, and token use stays within
the budget of 6,000 tokens per assessment.

The scale of each system (how many people it holds) is an input an analyst enters. Here it is the
number of people of the synthetic people file that belong to the system."""

import csv
import io
import json
from typing import Any

import pdfplumber
import pytest
from fastapi.testclient import TestClient

from app.db.enums import Role
from app.llm.router import LLMRouter
from app.main import create_app
from app.records.builder import NOTICE
from tests.fixtures_api import client_for, csrf
from tests.fixtures_fusion import DATASETS, FusionEstate
from tests.llm_support import FakeClock
from tests.test_fusion_acceptance import fuse, pipeline
from tests.test_records import record_for

RUBRIC = {
    i["system"]: i
    for i in json.loads(
        (DATASETS / "expected" / "dpia_screening.json").read_text(encoding="utf-8")
    )["items"]
}
PEOPLE = list(csv.DictReader((DATASETS / "people" / "synthetic_people.csv").open(encoding="utf-8")))
REQUIRED = sorted(s for s, i in RUBRIC.items() if i["assessment_required"])
TOKEN_BUDGET = 6000


def people_in(estate_id: str) -> int:
    return sum(1 for p in PEOPLE if p[f"in_{estate_id}"] in ("1", "True", "true", "yes"))


@pytest.fixture(scope="module")
def screenings(
    fusion_estate: FusionEstate, estate_records: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    admin = fusion_estate.admin
    out = {}
    for estate_id, activity in estate_records.items():
        response = admin.post(
            f"/api/v1/activities/{activity['id']}/dpia-screening",
            json={"data_subjects_estimate": people_in(estate_id)},
            headers=csrf(admin),
        )
        assert response.status_code == 200, response.text
        out[estate_id] = response.json()
    return out


@pytest.fixture(scope="module")
def assessments(
    fusion_estate: FusionEstate,
    estate_records: dict[str, dict[str, Any]],
    screenings: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    admin = fusion_estate.admin
    out = {}
    for estate_id in REQUIRED:
        before = len(fusion_estate.provider.requests)
        response = admin.post(
            f"/api/v1/activities/{estate_records[estate_id]['id']}/dpia",
            json={},
            headers=csrf(admin),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        body["_model_calls"] = len(fusion_estate.provider.requests) - before
        out[estate_id] = body
    return out


# -- screening -----------------------------------------------------------------------------------


def test_screening_matches_the_rubric_on_every_estate_activity(
    screenings: dict[str, dict[str, Any]],
) -> None:
    assert set(screenings) == set(RUBRIC) and len(screenings) == 8
    for estate_id, screening in screenings.items():
        met = sorted(c["id"] for c in screening["criteria"] if c["met"])
        assert met == sorted(RUBRIC[estate_id]["criteria_met"]), (estate_id, met)
        assert screening["required"] is RUBRIC[estate_id]["assessment_required"], estate_id
        assert screening["criteria_unknown"] == 0 and screening["threshold"] == 2
        assert screening["criteria_met"] == len(RUBRIC[estate_id]["criteria_met"])
    assert sorted(s for s, v in screenings.items() if v["required"]) == [
        "clinic_portal", "hr_onboarding", "staff_desktop", "web_analytics",
    ]  # fmt: skip


def test_each_criterion_gives_a_basis_and_evidence(screenings: dict[str, dict[str, Any]]) -> None:
    for estate_id, screening in screenings.items():
        assert len(screening["criteria"]) == 9
        for c in screening["criteria"]:
            assert c["basis"]
            if c["met"]:
                assert c["refs"] and all(r["kind"] and r["detail"] for r in c["refs"]), (
                    estate_id,
                    c["id"],
                )
    clinic = {c["id"]: c for c in screenings["clinic_portal"]["criteria"]}
    assert (
        "health data" in clinic["sensitive_data"]["basis"].lower()
        and "patients" in clinic["vulnerable_subjects"]["basis"]
    )
    staff = {c["id"]: c for c in screenings["staff_desktop"]["criteria"]}
    assert "geolocation" in staff["systematic_monitoring"]["basis"].lower()
    assert (
        "LeadScope"
        in {c["id"]: c for c in screenings["crm"]["criteria"]}["combining_datasets"]["basis"]
    )


def test_scale_is_unknown_until_someone_says_and_then_decides(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    system_id, activity = record_for(fusion_estate, admin, "web_analytics", "Analytics scale")
    first = admin.post(
        f"/api/v1/activities/{activity['id']}/dpia-screening", json={}, headers=csrf(admin)
    ).json()
    scale = next(c for c in first["criteria"] if c["id"] == "large_scale")
    assert scale["met"] is None and "estimate" in scale["needs"]
    assert (
        first["required"] is False and first["undecided"] is True and first["criteria_unknown"] == 1
    )

    second = admin.post(
        f"/api/v1/activities/{activity['id']}/dpia-screening",
        json={"data_subjects_estimate": 1722},
        headers=csrf(admin),
    ).json()
    assert (
        second["required"] is True
        and second["undecided"] is False
        and second["inputs"]["data_subjects_estimate"] == 1722
    )
    # the stated scale is kept for the next screening
    third = admin.post(
        f"/api/v1/activities/{activity['id']}/dpia-screening", headers=csrf(admin)
    ).json()
    assert third["required"] is True and third["inputs"]["data_subjects_estimate"] == 1722
    shown = admin.get(f"/api/v1/activities/{activity['id']}/dpia-screening").json()
    assert shown["criteria_met"] == 2


def test_an_analyst_can_state_a_criterion(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    _, activity = record_for(fusion_estate, admin, "helpdesk", "Helpdesk flags")
    screening = admin.post(
        f"/api/v1/activities/{activity['id']}/dpia-screening",
        json={"data_subjects_estimate": 363, "flags": ["automated_decisions", "evaluation_scoring"]}, headers=csrf(admin),
    ).json()  # fmt: skip
    assert screening["required"] is True
    flagged = {c["id"]: c for c in screening["criteria"]}["automated_decisions"]
    assert flagged["met"] is True and flagged["refs"][0]["kind"] == "manual"
    bad = admin.post(
        f"/api/v1/activities/{activity['id']}/dpia-screening",
        json={"flags": ["nonsense"]},
        headers=csrf(admin),
    )
    assert bad.status_code == 422
    assert (
        admin.post(
            f"/api/v1/activities/{activity['id']}/dpia-screening",
            json={"data_subjects_estimate": -1},
            headers=csrf(admin),
        ).status_code
        == 422
    )


def test_the_screening_list_and_unscreened_activities(
    fusion_estate: FusionEstate, screenings: dict[str, Any], estate_records: dict[str, Any]
) -> None:
    viewer = client_for(fusion_estate.app, fusion_estate.users["viewer"])
    listed = viewer.get("/api/v1/dpia-screenings").json()
    assert {s["activity_name"] for s in listed} >= set(RUBRIC)
    admin = fusion_estate.admin
    system_id, activity = record_for(fusion_estate, admin, "newsletter", "Never screened")
    assert admin.get(f"/api/v1/activities/{activity['id']}/dpia-screening").status_code == 404


# -- the assessments -----------------------------------------------------------------------------


def test_assessments_are_drafted_for_the_activities_that_need_them(
    assessments: dict[str, dict[str, Any]],
) -> None:
    assert sorted(assessments) == REQUIRED
    for estate_id, a in assessments.items():
        assert a["status"] == "draft" and a["criteria_met"] == 2 and a["activity_name"] == estate_id
        assert estate_id in a["description"] and a["necessity_proportionality"]
        assert a["drafting"]["sources"] == {
            "description": "assistant",
            "necessity": "assistant",
            "risks": "assistant",
        }
        assert len(a["risks"]) >= 2
        assert a["screening"]["required"] is True


def test_generated_assessments_pass_the_completeness_check(
    assessments: dict[str, dict[str, Any]],
) -> None:
    for estate_id, a in assessments.items():
        assert a["missing_fields"] == [], (estate_id, a["missing_fields"])
        assert a["residual_risk"] in {"low", "medium", "high", "very_high"}
        for r in a["risks"]:
            assert 1 <= r["likelihood"] <= 5 and 1 <= r["severity"] <= 5 and r["mitigation"]
            assert r["residual_likelihood"] and r["residual_severity"] and r["residual_level"]
        inherent = a["matrix"]["inherent"]
        assert len(inherent) == 5 and all(len(row) == 5 for row in inherent)
        assert sum(map(sum, inherent)) == len(a["risks"]) == sum(map(sum, a["matrix"]["residual"]))


def test_every_risk_cites_an_article_or_evidence_that_exists(
    fusion_estate: FusionEstate, assessments: dict[str, dict[str, Any]]
) -> None:
    admin = fusion_estate.admin
    finding_ids = {f["id"] for f in fusion_estate.findings()}
    checked = 0
    for estate_id, a in assessments.items():
        for risk in a["risks"]:
            assert risk["citation"], (estate_id, risk["title"])
            for citation in [c.strip() for c in risk["citation"].split(";")]:
                if citation.startswith("reg:"):
                    resolved = admin.get("/api/v1/knowledge/passage", params={"citation": citation})
                    assert (
                        resolved.status_code == 200 and resolved.json()["source"] == "regulation"
                    ), citation
                else:
                    assert (
                        citation.startswith("finding:")
                        and citation.removeprefix("finding:") in finding_ids
                    ), citation
                checked += 1
    assert checked >= 8


def test_token_use_is_within_the_budget_and_takes_two_calls(
    assessments: dict[str, dict[str, Any]],
) -> None:
    tokens = {e: a["drafting"]["tokens"] for e, a in assessments.items()}
    print("\n[dpia] tokens per assessment:", tokens)
    assert all(0 < t < TOKEN_BUDGET for t in tokens.values())
    assert max(tokens.values()) < 3500
    assert all(a["_model_calls"] == 2 and a["drafting"]["calls"] == 2 for a in assessments.values())


def test_the_gaps_found_by_the_comparison_become_risks_with_evidence(
    assessments: dict[str, dict[str, Any]],
) -> None:
    clinic = assessments["clinic_portal"]["risks"]
    transfer = [r for r in clinic if "outside the EEA" in r["title"]]
    assert (
        transfer
        and "finding:" in transfer[0]["citation"]
        and "reg:gdpr-art46" in transfer[0]["citation"]
    )
    analytics = assessments["web_analytics"]["risks"]
    assert any(
        "without a written agreement" in r["title"] and "finding:" in r["citation"]
        for r in analytics
    )
    assert not any("outside the EEA" in r["title"] for r in assessments["hr_onboarding"]["risks"])


def test_a_second_draft_for_the_same_facts_costs_no_tokens(
    fusion_estate: FusionEstate, estate_records: dict[str, Any], assessments: dict[str, Any]
) -> None:
    admin = fusion_estate.admin
    first = assessments["hr_onboarding"]
    analyst = client_for(fusion_estate.app, fusion_estate.users["analyst"])
    assert (
        analyst.post(f"/api/v1/dpias/{first['id']}/submit", headers=csrf(analyst)).status_code
        == 200
    )
    rejected = admin.post(
        f"/api/v1/dpias/{first['id']}/reject", json={"reason": "Start again"}, headers=csrf(admin)
    )
    assert rejected.status_code == 200
    before = len(fusion_estate.provider.requests)
    again = admin.post(
        f"/api/v1/activities/{estate_records['hr_onboarding']['id']}/dpia",
        json={},
        headers=csrf(admin),
    )
    assert again.status_code == 201
    body = again.json()
    assert (
        body["id"] != first["id"]
        and body["drafting"]["tokens"] == 0
        and body["drafting"]["calls"] == 0
    )
    assert len(fusion_estate.provider.requests) == before  # both answers came from the cache
    assert body["description"] == first["description"] and body["missing_fields"] == []
    # while one is in progress, another cannot be started
    assert (
        admin.post(
            f"/api/v1/activities/{estate_records['hr_onboarding']['id']}/dpia",
            json={},
            headers=csrf(admin),
        ).status_code
        == 409
    )


def test_without_a_provider_the_catalogue_and_templates_still_give_a_complete_draft(
    fusion_estate: FusionEstate, session_factory: Any
) -> None:
    router = LLMRouter({}, lambda: session_factory, clock=FakeClock(), sleep=lambda s: None)
    app = create_app(
        fusion_estate.app.state.settings,
        session_factory,
        embedder=fusion_estate.app.state.embedder,
        llm_router=router,
    )
    admin = client_for(app, fusion_estate.users["admin"])
    system_id = pipeline(
        admin, "hr_onboarding", fusion_estate.users["system_owner"].id, "HR offline"
    )
    fuse(admin, system_id)
    activity = admin.post(f"/api/v1/systems/{system_id}/record", headers=csrf(admin)).json()[
        "activity"
    ]
    admin.post(
        f"/api/v1/activities/{activity['id']}/dpia-screening",
        json={"data_subjects_estimate": 122},
        headers=csrf(admin),
    )
    response = admin.post(f"/api/v1/activities/{activity['id']}/dpia", json={}, headers=csrf(admin))
    assert response.status_code == 201, response.text
    a = response.json()
    assert a["drafting"]["sources"] == {
        "description": "template",
        "necessity": "template",
        "risks": "catalogue",
    }
    assert a["drafting"]["tokens"] == 0 and a["missing_fields"] == []
    assert (
        "special category data" in a["description"]
        and "no Article 9 condition is recorded" in a["necessity_proportionality"]
    )
    titles = " ".join(r["title"] for r in a["risks"])
    assert "special category" in titles.lower() or "highly personal" in titles.lower()
    assert all(r["citation"].startswith("reg:") or "finding:" in r["citation"] for r in a["risks"])


def test_an_assessment_not_required_needs_a_reason(
    fusion_estate: FusionEstate, screenings: dict[str, Any], estate_records: dict[str, Any]
) -> None:
    admin = fusion_estate.admin
    activity_id = estate_records["crm"]["id"]
    refused = admin.post(f"/api/v1/activities/{activity_id}/dpia", json={}, headers=csrf(admin))
    assert refused.status_code == 409 and "reason" in refused.json()["detail"]["message"]
    started = admin.post(
        f"/api/v1/activities/{activity_id}/dpia",
        json={"reason": "Planned expansion to a new region"},
        headers=csrf(admin),
    )
    assert started.status_code == 201
    body = started.json()
    assert (
        body["screening"]["required"] is False
        and body["criteria_met"] == 1
        and body["missing_fields"] == []
    )


# -- review --------------------------------------------------------------------------------------


def test_review_workflow_and_the_officers_opinion(
    fusion_estate: FusionEstate, assessments: dict[str, Any]
) -> None:
    admin = fusion_estate.admin
    analyst = client_for(fusion_estate.app, fusion_estate.users["analyst"])
    dpia_id = assessments["clinic_portal"]["id"]

    assert (
        analyst.patch(
            f"/api/v1/dpias/{dpia_id}",
            json={"officer_opinion": "Looks fine"},
            headers=csrf(analyst),
        ).status_code
        == 403
    )
    edited = analyst.patch(
        f"/api/v1/dpias/{dpia_id}",
        json={"description": "Reviewed and extended by the analyst."},
        headers=csrf(analyst),
    )
    assert edited.status_code == 200 and edited.json()["description"].startswith("Reviewed")

    submitted = analyst.post(f"/api/v1/dpias/{dpia_id}/submit", headers=csrf(analyst))
    assert submitted.status_code == 200 and submitted.json()["status"] == "in_review"
    assert (
        analyst.post(f"/api/v1/dpias/{dpia_id}/approve", json={}, headers=csrf(analyst)).status_code
        == 403
    )
    assert (
        analyst.patch(
            f"/api/v1/dpias/{dpia_id}", json={"description": "late edit"}, headers=csrf(analyst)
        ).status_code
        == 409
    )

    without = admin.post(f"/api/v1/dpias/{dpia_id}/approve", json={}, headers=csrf(admin))
    assert without.status_code == 409 and without.json()["detail"]["missing_fields"] == [
        "officer_opinion"
    ]
    opinion = admin.patch(
        f"/api/v1/dpias/{dpia_id}",
        json={"officer_opinion": "Proceed with the mitigations; review in 12 months."},
        headers=csrf(admin),
    )
    assert opinion.status_code == 200
    approved = admin.post(
        f"/api/v1/dpias/{dpia_id}/approve", json={"reason": "Accepted"}, headers=csrf(admin)
    )
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    assert (
        admin.patch(
            f"/api/v1/dpias/{dpia_id}", json={"officer_opinion": "changed"}, headers=csrf(admin)
        ).status_code
        == 409
    )
    assert (
        admin.post(
            f"/api/v1/dpias/{dpia_id}/risks",
            json={"title": "Late risk", "likelihood": 1, "severity": 1},
            headers=csrf(admin),
        ).status_code
        == 409
    )
    actions = {e["action"] for e in admin.get("/api/v1/audit-log", params={"limit": 500}).json()}
    assert {"dpia.screening", "dpia.create", "dpia.edit", "dpia.submit", "dpia.approve"} <= actions


def draft_for(fusion_estate: FusionEstate, name: str) -> str:
    admin = fusion_estate.admin
    _, activity = record_for(fusion_estate, admin, "staff_desktop", name)
    admin.post(
        f"/api/v1/activities/{activity['id']}/dpia-screening",
        json={"data_subjects_estimate": 122},
        headers=csrf(admin),
    )
    created = admin.post(f"/api/v1/activities/{activity['id']}/dpia", json={}, headers=csrf(admin))
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def test_the_submitter_cannot_decide_their_own_assessment(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    dpia_id = draft_for(fusion_estate, "Desktop self review")
    assert admin.post(f"/api/v1/dpias/{dpia_id}/submit", headers=csrf(admin)).status_code == 200
    admin.patch(f"/api/v1/dpias/{dpia_id}", json={"officer_opinion": "ok"}, headers=csrf(admin))
    for action in ("approve", "reject"):
        own = admin.post(f"/api/v1/dpias/{dpia_id}/{action}", json={}, headers=csrf(admin))
        assert own.status_code == 409 and "cannot approve" in own.json()["detail"]["message"]


def test_rejection_reopens_editing(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    analyst = client_for(fusion_estate.app, fusion_estate.users["analyst"])
    dpia_id = draft_for(fusion_estate, "Desktop rejected")
    assert analyst.post(f"/api/v1/dpias/{dpia_id}/submit", headers=csrf(analyst)).status_code == 200
    rejected = admin.post(
        f"/api/v1/dpias/{dpia_id}/reject", json={"reason": "Too optimistic"}, headers=csrf(admin)
    )
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    reopened = analyst.patch(
        f"/api/v1/dpias/{dpia_id}",
        json={"necessity_proportionality": "Rewritten after review."},
        headers=csrf(analyst),
    )
    assert reopened.status_code == 200 and reopened.json()["status"] == "draft"
    again = analyst.post(f"/api/v1/dpias/{dpia_id}/submit", headers=csrf(analyst))
    assert again.status_code == 200 and again.json()["status"] == "in_review"


def test_the_risk_register_can_be_edited_and_the_overall_residual_risk_follows(
    fusion_estate: FusionEstate, assessments: dict[str, Any]
) -> None:
    admin = fusion_estate.admin
    dpia_id = assessments["web_analytics"]["id"]
    added = admin.post(
        f"/api/v1/dpias/{dpia_id}/risks",
        json={"title": "Visitor identifiers are shared with the agency", "likelihood": 5, "severity": 4, "mitigation": "Drop the identifier from the report", "residual_likelihood": 5, "residual_severity": 4},
        headers=csrf(admin),
    )  # fmt: skip
    assert added.status_code == 201
    body = added.json()
    risk = next(r for r in body["risks"] if r["title"].startswith("Visitor identifiers"))
    assert risk["inherent_level"] == "very_high" and body["residual_risk"] == "very_high"
    assert any(
        "citation" in m for m in body["missing_fields"]
    )  # a risk without a source is incomplete

    fixed = admin.patch(
        f"/api/v1/dpias/{dpia_id}/risks/{risk['id']}",
        json={"citation": "reg:gdpr-art5-p1", "residual_likelihood": 1, "residual_severity": 2},
        headers=csrf(admin),
    )  # fmt: skip
    assert fixed.status_code == 200
    updated = next(r for r in fixed.json()["risks"] if r["id"] == risk["id"])
    assert updated["residual_level"] == "low" and fixed.json()["residual_risk"] != "very_high"
    assert fixed.json()["missing_fields"] == []

    removed = admin.delete(f"/api/v1/dpias/{dpia_id}/risks/{risk['id']}", headers=csrf(admin))
    assert removed.status_code == 200 and all(
        r["id"] != risk["id"] for r in removed.json()["risks"]
    )
    assert (
        admin.delete(f"/api/v1/dpias/{dpia_id}/risks/{risk['id']}", headers=csrf(admin)).status_code
        == 404
    )


@pytest.mark.parametrize(
    "body",
    [
        {"title": "x", "likelihood": 3, "severity": 3},
        {"title": "Valid title", "likelihood": 0, "severity": 3},
        {"title": "Valid title", "likelihood": 3, "severity": 6},
        {"title": "Valid title", "likelihood": 3, "severity": 3, "extra": 1},
    ],
)
def test_invalid_risks_are_refused(
    fusion_estate: FusionEstate, assessments: dict[str, Any], body: dict[str, Any]
) -> None:
    admin = fusion_estate.admin
    assert (
        admin.post(
            f"/api/v1/dpias/{assessments['web_analytics']['id']}/risks",
            json=body,
            headers=csrf(admin),
        ).status_code
        == 422
    )


def test_an_incomplete_assessment_cannot_be_submitted(
    fusion_estate: FusionEstate, assessments: dict[str, Any]
) -> None:
    admin = fusion_estate.admin
    dpia_id = assessments["web_analytics"]["id"]
    admin.post(
        f"/api/v1/dpias/{dpia_id}/risks",
        json={"title": "A risk with no source", "likelihood": 2, "severity": 2},
        headers=csrf(admin),
    )
    analyst = client_for(fusion_estate.app, fusion_estate.users["analyst"])
    response = analyst.post(f"/api/v1/dpias/{dpia_id}/submit", headers=csrf(analyst))
    assert response.status_code == 409
    missing = response.json()["detail"]["missing_fields"]
    assert any(m.endswith(":citation") for m in missing) and any(
        m.endswith(":mitigation") for m in missing
    )


# -- reading and exporting -----------------------------------------------------------------------


def test_assessments_can_be_listed_read_and_exported(
    fusion_estate: FusionEstate, assessments: dict[str, Any]
) -> None:
    viewer = client_for(fusion_estate.app, fusion_estate.users["viewer"])
    listed = viewer.get("/api/v1/dpias").json()
    assert {d["activity_name"] for d in listed} >= set(REQUIRED) and all(
        d["risks"] >= 1 for d in listed if d["activity_name"] in REQUIRED
    )
    one = viewer.get(f"/api/v1/dpias/{assessments['clinic_portal']['id']}").json()
    assert one["activity_name"] == "clinic_portal" and len(one["risks"]) >= 2

    pdf = viewer.get(f"/api/v1/dpias/{assessments['clinic_portal']['id']}/export.pdf")
    assert (
        pdf.status_code == 200
        and pdf.headers["content-type"] == "application/pdf"
        and pdf.content.startswith(b"%PDF-")
    )
    with pdfplumber.open(io.BytesIO(pdf.content)) as doc:
        texts = [page.extract_text() or "" for page in doc.pages]
    assert all(NOTICE in t for t in texts)
    full = "\n".join(texts)
    assert (
        "Data protection impact assessment" in full
        and "Risk register" in full
        and "Systematic description" in full
    )
    assert one["risks"][0]["title"][:30] in full.replace("\n", " ") or "Risk register" in full
    assert viewer.get(f"/api/v1/dpias/{assessments['clinic_portal']['id']}").status_code == 200


def test_system_owners_see_only_the_assessments_of_their_systems(
    fusion_estate: FusionEstate, screenings: dict[str, Any]
) -> None:
    admin = fusion_estate.admin
    system_id, activity = record_for(
        fusion_estate,
        admin,
        "clinic_portal",
        "Clinic of someone else",
        owner=fusion_estate.users["analyst"].id,
    )
    admin.post(
        f"/api/v1/activities/{activity['id']}/dpia-screening",
        json={"data_subjects_estimate": 284},
        headers=csrf(admin),
    )
    created = admin.post(f"/api/v1/activities/{activity['id']}/dpia", json={}, headers=csrf(admin))
    assert created.status_code == 201
    dpia_id = created.json()["id"]
    owner = client_for(fusion_estate.app, fusion_estate.users["system_owner"])
    assert dpia_id not in {d["id"] for d in owner.get("/api/v1/dpias").json()}
    assert owner.get(f"/api/v1/dpias/{dpia_id}").status_code == 404
    assert (
        owner.get(f"/api/v1/dpias/{dpia_id}/export.pdf").status_code == 403
    )  # owners do not export
    assert owner.get(f"/api/v1/activities/{activity['id']}/dpia-screening").status_code == 404
    assert activity["id"] not in {
        s["activity_id"] for s in owner.get("/api/v1/dpia-screenings").json()
    }
    assert (
        owner.post(
            f"/api/v1/activities/{activity['id']}/dpia", json={}, headers=csrf(owner)
        ).status_code
        == 403
    )
    assert fusion_estate.users["analyst"].id is not None and Role.ANALYST


def test_unknown_assessments_and_risks_are_404(fusion_estate: FusionEstate) -> None:
    import uuid

    admin = fusion_estate.admin
    assert admin.get(f"/api/v1/dpias/{uuid.uuid4()}").status_code == 404
    assert (
        admin.post(f"/api/v1/dpias/{uuid.uuid4()}/submit", headers=csrf(admin)).status_code == 404
    )
    assert (
        admin.post(
            f"/api/v1/activities/{uuid.uuid4()}/dpia", json={}, headers=csrf(admin)
        ).status_code
        == 404
    )
    assert isinstance(admin, TestClient)
