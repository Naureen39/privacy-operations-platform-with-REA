"""Phase 10 acceptance: all ten request cases return the expected systems and tables with no
misses, the deadline logic is exercised through the API, and no raw identifier appears in logs, in
the database, in audit entries or in a model call.

The reference estate organisation also holds copies of some systems made by other tests; they hold
the same data, so results are compared for the eight estate systems."""

import json
import logging
import uuid
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.records.builder import NOTICE
from tests.fixtures_api import client_for, csrf
from tests.fixtures_fusion import DATASETS, FusionEstate
from tests.test_discovery_api import create_system

ALL = {
    "name_matches_records": True,
    "contact_details_confirmed": True,
    "identity_document_seen": True,
}
CASES = json.loads((DATASETS / "people" / "request_cases.json").read_text(encoding="utf-8"))[
    "cases"
]
BASE = "/api/v1/access-requests"
TODAY = date(2026, 10, 1)  # the reference date of the estate organisation


def case(case_id: str) -> dict[str, Any]:
    return next(c for c in CASES if c["id"] == case_id)


def email_of(case_id: str) -> str:
    return str(case(case_id)["identifier"]["value"])


def open_request(client: TestClient, identifier: str, **extra: Any) -> dict[str, Any]:
    response = client.post(BASE, json={"identifier": identifier, **extra}, headers=csrf(client))
    assert response.status_code == 201, response.text
    return dict(response.json())


def verify(client: TestClient, request_id: str) -> dict[str, Any]:
    response = client.post(
        f"{BASE}/{request_id}/identity", json={"checklist": ALL}, headers=csrf(client)
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def run_search(client: TestClient, request_id: str, identifier: str) -> dict[str, Any]:
    response = client.post(
        f"{BASE}/{request_id}/search", json={"identifier": identifier}, headers=csrf(client)
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def prepared(client: TestClient, identifier: str, **extra: Any) -> tuple[str, dict[str, Any]]:
    request = open_request(client, identifier, **extra)
    verify(client, request["id"])
    return request["id"], run_search(client, request["id"], identifier)


def locations(
    fusion_estate: FusionEstate, results: list[dict[str, Any]]
) -> dict[tuple[str, str, str], int]:
    by_uuid = {v: k for k, v in fusion_estate.systems.items()}
    return {
        (by_uuid[r["system_id"]], r["table"], r["column"]): r["match_count"]
        for r in results
        if r["system_id"] in by_uuid
    }


# -- the ten cases -------------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", [c["id"] for c in CASES])
def test_each_request_case_returns_exactly_the_expected_locations(
    fusion_estate: FusionEstate, case_id: str
) -> None:
    c = case(case_id)
    _, outcome = prepared(fusion_estate.admin, email_of(case_id))
    expected = {
        (loc["system"], loc["table"], loc["column"]): loc["rows"] for loc in c["expected_locations"]
    }
    found = locations(fusion_estate, outcome["results"])
    assert found == expected, (
        case_id,
        sorted(set(expected) - set(found)),
        sorted(set(found) - set(expected)),
    )
    by_uuid = {v: k for k, v in fusion_estate.systems.items()}
    systems = sorted(
        {by_uuid[r["system_id"]] for r in outcome["results"] if r["system_id"] in by_uuid}
    )
    assert systems == c["expected_systems"]
    assert all(r["category"] == "contact_email" for r in outcome["results"])
    assert "searched" in outcome and len(outcome["searched"]) >= 8


def test_no_expected_location_is_missed_across_all_cases(fusion_estate: FusionEstate) -> None:
    expected_total = sum(len(c["expected_locations"]) for c in CASES)
    found_total = 0
    for c in CASES:
        _, outcome = prepared(fusion_estate.admin, email_of(c["id"]))
        found_total += len(locations(fusion_estate, outcome["results"]))
    print(
        f"\n[dsar] locations found {found_total} of {expected_total} expected across {len(CASES)} cases"
    )
    assert expected_total >= 40 and found_total == expected_total


def test_the_case_with_no_data_returns_an_empty_result(fusion_estate: FusionEstate) -> None:
    for case_id in ("RC09", "RC10"):
        _, outcome = prepared(fusion_estate.admin, email_of(case_id))
        assert (
            locations(fusion_estate, outcome["results"]) == {} and outcome["systems_matched"] == 0
        )


def test_an_e_mail_written_differently_finds_the_same_data(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    shouting = email_of("RC03").upper()
    _, outcome = prepared(admin, f"  {shouting} ")
    assert locations(fusion_estate, outcome["results"]) == {
        (loc["system"], loc["table"], loc["column"]): loc["rows"]
        for loc in case("RC03")["expected_locations"]
    }


def test_the_search_returns_counts_and_never_content(fusion_estate: FusionEstate) -> None:
    _, outcome = prepared(fusion_estate.admin, email_of("RC01"))
    for r in outcome["results"]:
        assert set(r) == {
            "id",
            "system_id",
            "system_name",
            "table",
            "column",
            "category",
            "match_count",
            "disclosure_approved",
        }
        assert r["disclosure_approved"] is False
    assert email_of("RC01").split("@")[0] not in json.dumps(outcome)


def test_systems_the_search_cannot_cover_are_reported(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    create_system(
        admin, "Intranet without a snapshot", owner=fusion_estate.users["system_owner"].id
    )
    _, outcome = prepared(admin, email_of("RC03"))
    skipped = {s["system"]: s["reason"] for s in outcome["skipped"]}
    assert skipped["Intranet without a snapshot"] == "no database snapshot on file"


# -- identity, hash and refusals -----------------------------------------------------------------


def test_searching_needs_a_verified_identity(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    request = open_request(admin, email_of("RC03"))
    refused = admin.post(
        f"{BASE}/{request['id']}/search", json={"identifier": email_of("RC03")}, headers=csrf(admin)
    )
    assert refused.status_code == 409 and "identity" in refused.json()["detail"]
    partial = admin.post(
        f"{BASE}/{request['id']}/identity",
        json={"checklist": {**ALL, "identity_document_seen": False}},
        headers=csrf(admin),
    ).json()
    assert partial["identity_verified"] is False and partial["status"] == "identity_verification"
    assert (
        admin.post(
            f"{BASE}/{request['id']}/search",
            json={"identifier": email_of("RC03")},
            headers=csrf(admin),
        ).status_code
        == 409
    )
    done = verify(admin, request["id"])
    assert done["identity_verified"] is True and done["status"] == "searching"
    unknown = admin.post(
        f"{BASE}/{request['id']}/identity", json={"checklist": {"bogus": True}}, headers=csrf(admin)
    )
    assert unknown.status_code == 422


def test_the_search_only_runs_for_the_identifier_the_request_was_opened_for(
    fusion_estate: FusionEstate,
) -> None:
    admin = fusion_estate.admin
    request = open_request(admin, email_of("RC03"))
    verify(admin, request["id"])
    wrong = admin.post(
        f"{BASE}/{request['id']}/search", json={"identifier": email_of("RC01")}, headers=csrf(admin)
    )
    assert wrong.status_code == 422
    assert email_of("RC01") not in wrong.text and email_of("RC03") not in wrong.text
    assert admin.get(f"{BASE}/{request['id']}/results").json() == []


@pytest.mark.parametrize("bad", ["not an email", "a@b", "", "x" * 300])
def test_invalid_identifiers_are_refused_without_being_echoed(
    fusion_estate: FusionEstate, bad: str
) -> None:
    admin = fusion_estate.admin
    response = admin.post(BASE, json={"identifier": bad}, headers=csrf(admin))
    assert response.status_code == 422
    if len(bad) > 3:
        assert bad not in response.text
    assert "input" not in response.text


def test_the_request_stores_only_a_hash_and_marks_duplicates(
    fusion_estate: FusionEstate, owner_engine: Engine
) -> None:
    admin = fusion_estate.admin
    address = f"duplicate.check.{uuid.uuid4().hex[:8]}@inbox.example"
    first = open_request(admin, address)
    second = open_request(admin, address.upper())
    assert first["possible_duplicates"] == [] and second["possible_duplicates"] == [
        first["reference"]
    ]
    assert first["reference"].startswith("AR-2026-") and first["reference"] != second["reference"]
    with owner_engine.connect() as conn:
        row = conn.execute(
            text("SELECT subject_hash, identifier_type FROM access_requests WHERE id = :i"),
            {"i": first["id"]},
        ).one()
        hashes = {
            r[0]
            for r in conn.execute(
                text("SELECT subject_hash FROM access_requests WHERE id IN (:a, :b)"),
                {"a": first["id"], "b": second["id"]},
            )
        }
    assert len(row[0]) == 64 and row[1] == "email" and len(hashes) == 1
    assert "duplicate" not in row[0]
    assert database_text_hits(owner_engine, address.split("@")[0]) == []


def test_the_same_person_in_another_organisation_has_another_hash(
    fusion_estate: FusionEstate, other_org: Any, owner_engine: Engine
) -> None:
    mine = open_request(fusion_estate.admin, email_of("RC08"))
    theirs = open_request(client_for(fusion_estate.app, other_org.users["admin"]), email_of("RC08"))
    with owner_engine.connect() as conn:
        a = conn.execute(
            text("SELECT subject_hash FROM access_requests WHERE id = :i"), {"i": mine["id"]}
        ).scalar_one()
        b = conn.execute(
            text("SELECT subject_hash FROM access_requests WHERE id = :i"), {"i": theirs["id"]}
        ).scalar_one()
    assert a != b


def test_a_telephone_number_can_identify_a_request(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    response = admin.post(
        BASE,
        json={"identifier_type": "phone", "identifier": "+44 20 7946 0958"},
        headers=csrf(admin),
    )
    assert response.status_code == 201 and response.json()["identifier_type"] == "phone"
    rid = response.json()["id"]
    verify(admin, rid)
    outcome = run_search(admin, rid, "(+44) 20-7946-0958")
    assert all(r["category"] == "contact_phone" for r in outcome["results"])


# -- deadlines through the API -------------------------------------------------------------------


def test_the_deadline_is_one_month_from_receipt_on_a_working_day(
    fusion_estate: FusionEstate,
) -> None:
    admin = fusion_estate.admin
    fresh = open_request(admin, email_of("RC10"))
    assert fresh["received_date"] == "2026-10-01" and fresh["original_deadline"] == "2026-11-02"
    assert (
        fresh["deadline_date"] == "2026-11-02"
        and fresh["days_remaining"] == 32
        and fresh["reminder"] == "none"
    )
    assert fresh["status"] == "received" and fresh["extended"] is False
    old = open_request(admin, email_of("RC10"), received_date="2026-08-31")
    assert (
        old["deadline_date"] == "2026-09-30"
        and old["overdue"] is True
        and old["reminder"] == "overdue"
    )
    assert old["days_remaining"] == -1
    future = admin.post(
        BASE,
        json={"identifier": email_of("RC10"), "received_date": "2026-10-02"},
        headers=csrf(admin),
    )
    assert future.status_code == 422


def test_reminders_list_what_is_overdue_or_due_soon_most_urgent_first(
    fusion_estate: FusionEstate,
) -> None:
    admin = fusion_estate.admin
    soon = open_request(
        admin, email_of("RC09"), received_date="2026-09-05"
    )  # due Monday 5 October: 4 days
    late = open_request(
        admin, email_of("RC09"), received_date="2026-08-03"
    )  # due 3 September: overdue
    quiet = open_request(
        admin, email_of("RC09"), received_date="2026-09-25"
    )  # due Monday 26 October
    listed = admin.get(f"{BASE}/reminders").json()
    ids = [r["id"] for r in listed]
    assert soon["id"] in ids and late["id"] in ids and quiet["id"] not in ids
    assert ids.index(late["id"]) < ids.index(soon["id"])
    by_id = {r["id"]: r for r in listed}
    assert (
        by_id[late["id"]]["reminder"] == "overdue" and by_id[soon["id"]]["reminder"] == "due_soon"
    )
    assert by_id[soon["id"]]["days_remaining"] == 4
    overdue = admin.get(BASE, params={"overdue": "true"}).json()
    assert late["id"] in {r["id"] for r in overdue} and soon["id"] not in {r["id"] for r in overdue}
    assert viewer_cannot_see_reminders(fusion_estate)


def viewer_cannot_see_reminders(fusion_estate: FusionEstate) -> bool:
    viewer = client_for(fusion_estate.app, fusion_estate.users["viewer"])
    return viewer.get(f"{BASE}/reminders").status_code == 403


def test_a_request_can_be_extended_once_within_the_first_month_with_a_reason(
    fusion_estate: FusionEstate,
) -> None:
    admin = fusion_estate.admin
    request = open_request(
        admin, email_of("RC09"), received_date="2026-09-15"
    )  # first deadline 15 October

    def extend(body: dict[str, Any]) -> Any:
        return admin.post(f"{BASE}/{request['id']}/extension", json=body, headers=csrf(admin))

    assert (
        extend(
            {"months": 3, "reason": "The request is complex and covers many systems."}
        ).status_code
        == 422
    )
    assert (
        extend(
            {"months": 0, "reason": "The request is complex and covers many systems."}
        ).status_code
        == 422
    )
    assert extend({"months": 2, "reason": "too short"}).status_code == 422
    done = extend({"months": 2, "reason": "The request is complex and covers many systems."})
    assert done.status_code == 200
    body = done.json()
    assert (
        body["extended"] is True
        and body["extension_months"] == 2
        and body["deadline_date"] == "2026-12-15"
    )
    assert body["original_deadline"] == "2026-10-15" and "complex" in body["extension_reason"]
    again = extend({"months": 1, "reason": "A second reason for another extension."})
    assert again.status_code == 409 and "already" in again.json()["detail"]


def test_it_is_too_late_to_extend_after_the_first_deadline(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    request = open_request(admin, email_of("RC09"), received_date="2026-08-03")
    response = admin.post(
        f"{BASE}/{request['id']}/extension",
        json={"months": 1, "reason": "The request is complex enough."},
        headers=csrf(admin),
    )
    assert response.status_code == 409 and "first month" in response.json()["detail"]


# -- the whole workflow --------------------------------------------------------------------------


def test_an_access_request_goes_from_intake_to_a_closed_case(
    fusion_estate: FusionEstate, estate_records: dict[str, Any], owner_engine: Engine
) -> None:
    admin = fusion_estate.admin
    analyst = client_for(fusion_estate.app, fusion_estate.users["analyst"])
    identifier = email_of("RC03")  # a patient who is in no other system
    request = open_request(analyst, identifier)
    rid = request["id"]
    verify(analyst, rid)
    outcome = run_search(analyst, rid, identifier)
    assert (
        request["status"] == "received"
        and analyst.get(f"{BASE}/{rid}").json()["status"] == "drafting"
    )
    ids = {
        (r["table"]): r["id"]
        for r in outcome["results"]
        if r["system_id"] == fusion_estate.systems["clinic_portal"]
    }
    assert set(ids) == {"patients", "appointments"}

    # content is disclosed only where the privacy officer approved it
    assert (
        analyst.post(
            f"{BASE}/{rid}/disclosure",
            json={"result_ids": [ids["patients"]]},
            headers=csrf(analyst),
        ).status_code
        == 403
    )
    approved = admin.post(
        f"{BASE}/{rid}/disclosure", json={"result_ids": [ids["patients"]]}, headers=csrf(admin)
    ).json()
    assert {
        r["table"]
        for r in approved
        if r["disclosure_approved"] and r["system_id"] == fusion_estate.systems["clinic_portal"]
    } == {"patients"}
    assert (
        admin.post(
            f"{BASE}/{rid}/disclosure",
            json={"result_ids": [str(uuid.uuid4())]},
            headers=csrf(admin),
        ).status_code
        == 404
    )
    admin.post(
        f"{BASE}/{rid}/disclosure", json={"result_ids": [ids["patients"]]}, headers=csrf(admin)
    )
    data = admin.post(
        f"{BASE}/{rid}/disclosed-data", json={"identifier": identifier}, headers=csrf(admin)
    )
    assert data.status_code == 200
    locations_out = [d for d in data.json() if d["system"] == "clinic_portal"]
    assert [d["table"] for d in locations_out] == ["patients"] and len(
        locations_out[0]["rows"]
    ) == 1
    assert locations_out[0]["rows"][0]["email"] == identifier
    assert (
        analyst.post(
            f"{BASE}/{rid}/disclosed-data", json={"identifier": identifier}, headers=csrf(analyst)
        ).status_code
        == 403
    )
    assert (
        admin.post(
            f"{BASE}/{rid}/disclosed-data",
            json={"identifier": email_of("RC01")},
            headers=csrf(admin),
        ).status_code
        == 422
    )

    # the letter
    draft = analyst.post(f"{BASE}/{rid}/response", json={"cover_note": True}, headers=csrf(analyst))
    assert draft.status_code == 201, draft.text
    letter = draft.json()
    assert letter["version"] == 1 and letter["status"] == "draft"
    assert letter["body"].startswith(NOTICE) and "Article 15" in letter["body"]
    assert (
        "clinic_portal" in letter["body"]
        and "patients: 1 record(s)" in letter["body"]
        and "appointments: 3 record(s)" in letter["body"]
    )
    assert (
        "Why we use it" in letter["body"] and "Appointment management" in letter["body"]
    )  # from the record of the system
    assert "Health data" in letter["body"] and "10 years" in letter["body"]
    assert letter["cover_note"] and "enclosed" in letter["cover_note"]
    assert identifier not in letter["body"] and identifier.split("@")[0] not in letter["body"]
    edited = analyst.patch(
        f"{BASE}/{rid}/response",
        json={"body": letter["body"] + "\n\nChecked by the analyst."},
        headers=csrf(analyst),
    )
    assert edited.status_code == 200 and edited.json()["body"].endswith("Checked by the analyst.")

    # approval is a different person
    assert analyst.post(f"{BASE}/{rid}/respond", headers=csrf(analyst)).status_code == 403
    assert (
        admin.post(f"{BASE}/{rid}/respond", headers=csrf(admin)).status_code == 409
    )  # nothing approved yet
    submitted = analyst.post(f"{BASE}/{rid}/submit", headers=csrf(analyst))
    assert submitted.status_code == 200 and submitted.json()["status"] == "awaiting_approval"
    assert (
        analyst.patch(
            f"{BASE}/{rid}/response", json={"cover_note": "late"}, headers=csrf(analyst)
        ).status_code
        == 409
    )
    sent_back = admin.post(
        f"{BASE}/{rid}/return", json={"note": "Add the contact"}, headers=csrf(admin)
    )
    assert sent_back.status_code == 200 and sent_back.json()["status"] == "drafting"
    analyst.post(f"{BASE}/{rid}/submit", headers=csrf(analyst))
    assert analyst.post(f"{BASE}/{rid}/approve", json={}, headers=csrf(analyst)).status_code == 403
    assert (
        admin.post(
            f"{BASE}/{rid}/approve", json={"note": "Reviewed"}, headers=csrf(admin)
        ).status_code
        == 200
    )
    assert admin.post(f"{BASE}/{rid}/close", headers=csrf(admin)).status_code == 409  # not sent yet
    sent = admin.post(f"{BASE}/{rid}/respond", headers=csrf(admin))
    assert (
        sent.status_code == 200
        and sent.json()["status"] == "responded"
        and sent.json()["responded_at"]
    )
    assert admin.get(f"{BASE}/{rid}/response").json()["status"] == "sent"
    assert admin.get(f"{BASE}/{rid}").json()["reminder"] == "none"
    closed = analyst.post(f"{BASE}/{rid}/close", headers=csrf(analyst))
    assert (
        closed.status_code == 200
        and closed.json()["status"] == "closed"
        and closed.json()["closed_at"]
    )
    actions = {e["action"] for e in admin.get("/api/v1/audit-log", params={"limit": 500}).json()}
    assert {
        "request.create",
        "request.identity",
        "request.search",
        "request.disclosure",
        "request.disclosed_data",
        "request.response_draft",
        "request.submit",
        "request.return",
        "request.approve",
        "request.respond",
        "request.close",
    } <= actions


def test_the_submitter_cannot_approve_their_own_response(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    rid, _ = prepared(admin, email_of("RC08"))
    assert admin.post(f"{BASE}/{rid}/response", json={}, headers=csrf(admin)).status_code == 201
    assert admin.post(f"{BASE}/{rid}/submit", headers=csrf(admin)).status_code == 200
    own = admin.post(f"{BASE}/{rid}/approve", json={}, headers=csrf(admin))
    assert own.status_code == 409 and "cannot approve" in own.json()["detail"]


def test_the_letter_for_a_person_with_no_data_says_so_and_lists_what_could_not_be_searched(
    fusion_estate: FusionEstate,
) -> None:
    admin = fusion_estate.admin
    rid, _ = prepared(admin, email_of("RC10"))
    letter = admin.post(f"{BASE}/{rid}/response", json={}, headers=csrf(admin)).json()
    assert "did not find personal data that matches" in letter["body"]
    assert (
        "We could not search the following systems" in letter["body"]
        and "Intranet without a snapshot" in letter["body"]
    )
    assert letter["cover_note"] is None


def test_drafting_needs_a_search_and_each_draft_is_a_new_version(
    fusion_estate: FusionEstate,
) -> None:
    admin = fusion_estate.admin
    request = open_request(admin, email_of("RC08"))
    assert (
        admin.post(f"{BASE}/{request['id']}/response", json={}, headers=csrf(admin)).status_code
        == 409
    )
    verify(admin, request["id"])
    assert (
        admin.post(f"{BASE}/{request['id']}/response", json={}, headers=csrf(admin)).status_code
        == 409
    )
    run_search(admin, request["id"], email_of("RC08"))
    first = admin.post(f"{BASE}/{request['id']}/response", json={}, headers=csrf(admin)).json()
    second = admin.post(f"{BASE}/{request['id']}/response", json={}, headers=csrf(admin)).json()
    assert (first["version"], second["version"]) == (1, 2)
    assert admin.get(f"{BASE}/{request['id']}/response").json()["version"] == 2
    assert admin.get(f"{BASE}/{uuid.uuid4()}/response").status_code == 404


def test_a_request_can_be_refused_with_a_reason(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    analyst = client_for(fusion_estate.app, fusion_estate.users["analyst"])
    request = open_request(admin, email_of("RC10"))
    assert (
        analyst.post(
            f"{BASE}/{request['id']}/reject",
            json={"reason": "Manifestly unfounded request."},
            headers=csrf(analyst),
        ).status_code
        == 403
    )
    assert (
        admin.post(
            f"{BASE}/{request['id']}/reject", json={"reason": "short"}, headers=csrf(admin)
        ).status_code
        == 422
    )
    refused = admin.post(
        f"{BASE}/{request['id']}/reject",
        json={"reason": "Manifestly unfounded: no identity given."},
        headers=csrf(admin),
    )
    assert (
        refused.status_code == 200
        and refused.json()["status"] == "rejected"
        and refused.json()["reminder"] == "none"
    )
    assert "unfounded" in refused.json()["rejection_reason"]
    assert (
        admin.post(
            f"{BASE}/{request['id']}/identity", json={"checklist": ALL}, headers=csrf(admin)
        ).status_code
        == 409
    )
    assert request["id"] not in {r["id"] for r in admin.get(f"{BASE}/reminders").json()}


# -- access control ------------------------------------------------------------------------------


def test_access_requests_are_for_the_privacy_team_only(
    fusion_estate: FusionEstate, other_org: Any
) -> None:
    admin = fusion_estate.admin
    request = open_request(admin, email_of("RC10"))
    owner = client_for(fusion_estate.app, fusion_estate.users["system_owner"])
    assert (
        owner.get(BASE).status_code == 403
        and owner.get(f"{BASE}/{request['id']}").status_code == 403
    )
    assert (
        owner.post(BASE, json={"identifier": email_of("RC10")}, headers=csrf(owner)).status_code
        == 403
    )
    viewer = client_for(fusion_estate.app, fusion_estate.users["viewer"])
    assert (
        viewer.get(f"{BASE}/{request['id']}").status_code == 200
        and viewer.get(f"{BASE}/{request['id']}/results").status_code == 200
    )
    assert (
        viewer.post(BASE, json={"identifier": email_of("RC10")}, headers=csrf(viewer)).status_code
        == 403
    )
    stranger = client_for(fusion_estate.app, other_org.users["admin"])
    assert stranger.get(f"{BASE}/{request['id']}").status_code == 404
    assert request["id"] not in {r["id"] for r in stranger.get(BASE).json()}
    assert (
        stranger.post(
            f"{BASE}/{request['id']}/search",
            json={"identifier": email_of("RC10")},
            headers=csrf(stranger),
        ).status_code
        == 404
    )


# -- no raw identifier anywhere ------------------------------------------------------------------


def database_text_hits(engine: Engine, needle: str) -> list[str]:
    """Tables with a row whose text form contains the needle."""
    with engine.connect() as conn:
        tables = [
            r[0]
            for r in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        ]
        return [
            t for t in tables
            if conn.execute(text(f'SELECT count(*) FROM "{t}" WHERE "{t}"::text ILIKE :p'), {"p": f"%{needle}%"}).scalar_one()  # noqa: S608
        ]  # fmt: skip


def test_no_raw_identifier_reaches_logs_the_database_audit_entries_or_a_model(
    fusion_estate: FusionEstate,
    owner_engine: Engine,
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG)
    admin = fusion_estate.admin
    analyst = client_for(fusion_estate.app, fusion_estate.users["analyst"])
    secrets = [email_of("RC01"), email_of("RC04"), email_of("RC07")]
    before = len(fusion_estate.provider.requests)
    for index, identifier in enumerate(secrets):
        client = analyst if index % 2 else admin
        rid, _ = prepared(client, identifier)
        client.post(f"{BASE}/{rid}/response", json={"cover_note": True}, headers=csrf(client))
        client.post(
            f"{BASE}/{rid}/search", json={"identifier": "wrong." + identifier}, headers=csrf(client)
        )  # a refused call
        client.get(f"{BASE}/{rid}")
        client.get(f"{BASE}/{rid}/results")
    admin.post(
        BASE, json={"identifier": "bad value " + secrets[0]}, headers=csrf(admin)
    )  # a validation error

    captured = capfd.readouterr()
    sent_to_models = "\n".join(r.user + r.system for r in fusion_estate.provider.requests[before:])
    audit = json.dumps(admin.get("/api/v1/audit-log", params={"limit": 500}).json())
    requests_listing = json.dumps(admin.get(BASE).json()) + json.dumps(
        admin.get(f"{BASE}/reminders").json()
    )
    assert (
        len(fusion_estate.provider.requests) > before
    )  # the cover notes did go through the router
    for identifier in secrets:
        local = identifier.split("@")[0]
        for where, blob in (
            ("log records", caplog.text), ("stdout and stderr", captured.out + captured.err),
            ("model requests", sent_to_models), ("audit log", audit), ("request listings", requests_listing),
        ):  # fmt: skip
            assert identifier not in blob and local not in blob, where
        assert database_text_hits(owner_engine, identifier) == [], identifier
        assert database_text_hits(owner_engine, local) == [], local


def test_the_cover_note_call_carries_counts_only(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    before = len(fusion_estate.provider.requests)
    rid, outcome = prepared(admin, email_of("RC02"))
    admin.post(f"{BASE}/{rid}/response", json={"cover_note": True}, headers=csrf(admin))
    sent = [
        r
        for r in fusion_estate.provider.requests[before:]
        if r.schema_name == "draft_request_cover_note"
    ]
    assert sent
    payload = json.loads(sent[-1].user.removeprefix("<data>\n").removesuffix("\n</data>"))
    assert set(payload) == {"request_type", "days_taken", "systems_found", "tone"}
    assert (
        payload["systems_found"] == outcome["systems_matched"] >= 3 and payload["days_taken"] == 0
    )
