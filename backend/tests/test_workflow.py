"""Tasks, comments, notifications and review reminders."""

import uuid
from typing import Any

from fastapi.testclient import TestClient

from tests.fixtures_api import client_for, csrf
from tests.fixtures_fusion import FusionEstate
from tests.test_fusion_acceptance import fuse, pipeline
from tests.test_records import record_for


def as_user(fe: FusionEstate, role: str) -> TestClient:
    return client_for(fe.app, fe.users[role])


def inbox(client: TestClient, **params: Any) -> list[dict[str, Any]]:
    response = client.get("/api/v1/notifications", params={"limit": 200, **params})
    assert response.status_code == 200, response.text
    return list(response.json())


def titles(client: TestClient) -> list[str]:
    return [n["title"] for n in inbox(client)]


# -- tasks ---------------------------------------------------------------------------------------


def test_a_task_can_be_created_assigned_and_the_assignee_is_told(
    fusion_estate: FusionEstate,
) -> None:
    fe = fusion_estate
    analyst, owner = as_user(fe, "analyst"), as_user(fe, "system_owner")
    created = analyst.post(
        "/api/v1/tasks",
        json={
            "title": "Agree the Article 9 condition",
            "description": "With the clinic director.",
            "assignee_user_id": str(fe.users["system_owner"].id),
            "system_id": fe.systems["clinic_portal"],
            "due_date": "2026-11-15",
        },
        headers=csrf(analyst),
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert (
        task["status"] == "open"
        and task["due_date"] == "2026-11-15"
        and task["assignee_user_id"] == str(fe.users["system_owner"].id)
    )
    assert any(
        n["kind"] == "task_assigned"
        and n["entity_id"] == task["id"]
        and "Agree the Article 9" in n["title"]
        for n in inbox(owner)
    )
    assert (
        analyst.get(f"/api/v1/tasks/{task['id']}").json()["title"]
        == "Agree the Article 9 condition"
    )
    audit = {e["action"] for e in fe.admin.get("/api/v1/audit-log", params={"limit": 500}).json()}
    assert "task.create" in audit


def test_task_creation_is_validated_and_limited_to_editors(fusion_estate: FusionEstate) -> None:
    fe = fusion_estate
    admin = fe.admin
    for role in ("viewer", "system_owner"):
        c = as_user(fe, role)
        assert (
            c.post("/api/v1/tasks", json={"title": "Not allowed"}, headers=csrf(c)).status_code
            == 403
        )
    assert admin.post("/api/v1/tasks", json={"title": "x"}, headers=csrf(admin)).status_code == 422
    assert (
        admin.post(
            "/api/v1/tasks", json={"title": "Valid title", "bogus": 1}, headers=csrf(admin)
        ).status_code
        == 422
    )
    assert (
        admin.post(
            "/api/v1/tasks",
            json={"title": "Valid title", "assignee_user_id": str(uuid.uuid4())},
            headers=csrf(admin),
        ).status_code
        == 422
    )
    assert (
        admin.post(
            "/api/v1/tasks",
            json={"title": "Valid title", "system_id": str(uuid.uuid4())},
            headers=csrf(admin),
        ).status_code
        == 404
    )
    assert (
        admin.post(
            "/api/v1/tasks",
            json={"title": "Valid title", "finding_id": str(uuid.uuid4())},
            headers=csrf(admin),
        ).status_code
        == 404
    )


def test_tasks_can_be_listed_filtered_and_are_scoped_for_owners(
    fusion_estate: FusionEstate,
) -> None:
    fe = fusion_estate
    admin, owner, viewer = fe.admin, as_user(fe, "system_owner"), as_user(fe, "viewer")
    mine = admin.post(
        "/api/v1/tasks",
        json={"title": "Task for the owner", "assignee_user_id": str(fe.users["system_owner"].id)},
        headers=csrf(admin),
    ).json()
    other = admin.post(
        "/api/v1/tasks",
        json={"title": "Task for the analyst", "assignee_user_id": str(fe.users["analyst"].id)},
        headers=csrf(admin),
    ).json()
    listed = owner.get("/api/v1/tasks", params={"mine": "true"})
    assert listed.status_code == 200 and mine["id"] in {t["id"] for t in listed.json()}
    assert other["id"] not in {t["id"] for t in owner.get("/api/v1/tasks").json()}
    assert owner.get(f"/api/v1/tasks/{other['id']}").status_code == 404
    assert other["id"] in {t["id"] for t in viewer.get("/api/v1/tasks").json()}
    response = admin.get("/api/v1/tasks", params={"status": "open", "limit": 1})
    assert len(response.json()) == 1 and int(response.headers["x-total-count"]) >= 2
    assert admin.get("/api/v1/tasks", params={"status": "bogus"}).status_code == 422


def test_task_updates_follow_who_may_change_what(fusion_estate: FusionEstate) -> None:
    fe = fusion_estate
    admin, owner, analyst = fe.admin, as_user(fe, "system_owner"), as_user(fe, "analyst")
    task = admin.post(
        "/api/v1/tasks",
        json={"title": "Update my status", "assignee_user_id": str(fe.users["system_owner"].id)},
        headers=csrf(admin),
    ).json()
    started = owner.patch(
        f"/api/v1/tasks/{task['id']}", json={"status": "in_progress"}, headers=csrf(owner)
    )
    assert started.status_code == 200 and started.json()["status"] == "in_progress"
    assert (
        owner.patch(
            f"/api/v1/tasks/{task['id']}", json={"title": "Renamed by owner"}, headers=csrf(owner)
        ).status_code
        == 403
    )
    assert (
        owner.patch(
            f"/api/v1/tasks/{task['id']}", json={"status": "bogus"}, headers=csrf(owner)
        ).status_code
        == 422
    )
    edited = analyst.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"title": "Renamed by analyst", "due_date": "2026-12-01"},
        headers=csrf(analyst),
    )
    assert (
        edited.json()["title"] == "Renamed by analyst" and edited.json()["due_date"] == "2026-12-01"
    )
    reassigned = admin.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"assignee_user_id": str(fe.users["analyst"].id)},
        headers=csrf(admin),
    )
    assert reassigned.status_code == 200
    assert (
        owner.patch(
            f"/api/v1/tasks/{task['id']}", json={"status": "done"}, headers=csrf(owner)
        ).status_code
        == 404
    )  # no longer theirs
    assert (
        admin.patch(
            f"/api/v1/tasks/{task['id']}",
            json={"assignee_user_id": str(uuid.uuid4())},
            headers=csrf(admin),
        ).status_code
        == 422
    )
    viewer = as_user(fe, "viewer")
    assert (
        viewer.patch(
            f"/api/v1/tasks/{task['id']}", json={"status": "done"}, headers=csrf(viewer)
        ).status_code
        == 403
    )
    done = admin.patch(f"/api/v1/tasks/{task['id']}", json={"status": "done"}, headers=csrf(admin))
    assert done.json()["status"] == "done"


def test_a_finding_becomes_one_task_for_the_owner_of_the_system(
    fusion_estate: FusionEstate,
) -> None:
    fe = fusion_estate
    admin, owner = fe.admin, as_user(fe, "system_owner")
    finding = fe.findings("clinic_portal", type="missing_art9_condition", status="open")[0]
    first = admin.post(f"/api/v1/findings/{finding['id']}/task", headers=csrf(admin))
    assert first.status_code == 201, first.text
    task = first.json()
    assert task["title"].startswith("Resolve: ") and task["finding_id"] == finding["id"]
    assert (
        task["assignee_user_id"] == str(fe.users["system_owner"].id)
        and task["system_id"] == fe.systems["clinic_portal"]
    )
    again = admin.post(f"/api/v1/findings/{finding['id']}/task", headers=csrf(admin))
    assert again.json()["id"] == task["id"]
    assert [f["status"] for f in fe.findings("clinic_portal", type="missing_art9_condition")] == [
        "acknowledged"
    ]
    assert any(n["kind"] == "task_assigned" and n["entity_id"] == task["id"] for n in inbox(owner))
    assert (
        admin.post(f"/api/v1/findings/{uuid.uuid4()}/task", headers=csrf(admin)).status_code == 404
    )
    viewer = as_user(fe, "viewer")
    assert (
        viewer.post(f"/api/v1/findings/{finding['id']}/task", headers=csrf(viewer)).status_code
        == 403
    )
    admin.patch(f"/api/v1/findings/{finding['id']}", json={"status": "open"}, headers=csrf(admin))


# -- comments ------------------------------------------------------------------------------------


def test_comments_notify_the_owner_and_earlier_commenters_but_not_the_author(
    fusion_estate: FusionEstate, estate_records: dict[str, Any]
) -> None:
    fe = fusion_estate
    analyst, owner, admin, viewer = (
        as_user(fe, "analyst"),
        as_user(fe, "system_owner"),
        fe.admin,
        as_user(fe, "viewer"),
    )
    activity_id = estate_records["crm"]["id"]
    body = {"entity_type": "activity", "entity_id": activity_id}
    first = analyst.post(
        "/api/v1/comments",
        json={**body, "body": "Please confirm the retention period with sales."},
        headers=csrf(analyst),
    )
    assert first.status_code == 201 and first.json()["author_user_id"] == str(
        fe.users["analyst"].id
    )
    assert "New comment on a activity" in titles(owner)
    assert not any(n["entity_id"] == activity_id for n in inbox(analyst))  # not the author
    admin.post(
        "/api/v1/comments",
        json={**body, "body": "Agreed, and the notice too."},
        headers=csrf(admin),
    )
    assert any(
        n["kind"] == "comment" and n["entity_id"] == activity_id for n in inbox(analyst)
    )  # an earlier commenter
    reply = owner.post(
        "/api/v1/comments", json={**body, "body": "Retention is 18 months."}, headers=csrf(owner)
    )
    assert reply.status_code == 201
    listed = viewer.get(
        "/api/v1/comments", params={"entity_type": "activity", "entity_id": activity_id}
    ).json()
    assert [c["body"] for c in listed][-3:] == [
        "Please confirm the retention period with sales.",
        "Agreed, and the notice too.",
        "Retention is 18 months.",
    ]
    assert (
        viewer.post(
            "/api/v1/comments", json={**body, "body": "I may not"}, headers=csrf(viewer)
        ).status_code
        == 403
    )


def test_comments_are_validated_and_scoped_to_what_you_can_see(fusion_estate: FusionEstate) -> None:
    fe = fusion_estate
    admin, owner = fe.admin, as_user(fe, "system_owner")
    assert (
        admin.post(
            "/api/v1/comments",
            json={"entity_type": "activity", "entity_id": str(uuid.uuid4()), "body": "x"},
            headers=csrf(admin),
        ).status_code
        == 404
    )
    assert (
        admin.post(
            "/api/v1/comments",
            json={"entity_type": "unicorn", "entity_id": str(uuid.uuid4()), "body": "x"},
            headers=csrf(admin),
        ).status_code
        == 422
    )
    assert (
        admin.post(
            "/api/v1/comments",
            json={"entity_type": "system", "entity_id": fe.systems["crm"], "body": ""},
            headers=csrf(admin),
        ).status_code
        == 422
    )
    assert (
        admin.get(
            "/api/v1/comments", params={"entity_type": "unicorn", "entity_id": str(uuid.uuid4())}
        ).status_code
        == 422
    )
    system = admin.post(
        "/api/v1/comments",
        json={
            "entity_type": "system",
            "entity_id": fe.systems["crm"],
            "body": "A note on the system.",
        },
        headers=csrf(admin),
    )
    assert system.status_code == 201
    finding = fe.findings("crm", status="open")[0]
    on_finding = admin.post(
        "/api/v1/comments",
        json={"entity_type": "finding", "entity_id": finding["id"], "body": "Looking into it."},
        headers=csrf(admin),
    )
    assert on_finding.status_code == 201
    # a system belonging to someone else is invisible to an owner
    other_id = admin.post(
        "/api/v1/systems",
        json={"name": "Comments of someone else", "owner_user_id": str(fe.users["analyst"].id)},
        headers=csrf(admin),
    ).json()["id"]
    assert (
        owner.post(
            "/api/v1/comments",
            json={"entity_type": "system", "entity_id": other_id, "body": "peek"},
            headers=csrf(owner),
        ).status_code
        == 404
    )
    assert (
        owner.get(
            "/api/v1/comments", params={"entity_type": "system", "entity_id": other_id}
        ).status_code
        == 404
    )


# -- notifications -------------------------------------------------------------------------------


def test_notifications_are_private_and_can_be_marked_read(fusion_estate: FusionEstate) -> None:
    fe = fusion_estate
    admin, owner = fe.admin, as_user(fe, "system_owner")
    for index in range(3):
        admin.post(
            "/api/v1/tasks",
            json={
                "title": f"Notify me {index}",
                "assignee_user_id": str(fe.users["system_owner"].id),
            },
            headers=csrf(admin),
        )
    response = owner.get("/api/v1/notifications", params={"unread_only": "true"})
    unread = int(response.headers["x-unread-count"])
    assert unread >= 3 and int(response.headers["x-total-count"]) == unread
    first = response.json()[0]
    marked = owner.post(f"/api/v1/notifications/{first['id']}/read", headers=csrf(owner))
    assert marked.status_code == 200 and marked.json()["read_at"]
    assert int(owner.get("/api/v1/notifications").headers["x-unread-count"]) == unread - 1
    assert (
        owner.post(f"/api/v1/notifications/{first['id']}/read", headers=csrf(owner)).status_code
        == 200
    )  # again: harmless
    # someone else cannot read or mark it
    assert (
        admin.post(f"/api/v1/notifications/{first['id']}/read", headers=csrf(admin)).status_code
        == 404
    )
    assert first["id"] not in {n["id"] for n in inbox(admin)}
    everything = owner.post("/api/v1/notifications/read-all", headers=csrf(owner))
    assert everything.status_code == 200 and everything.json()["marked"] == unread - 1
    assert int(owner.get("/api/v1/notifications").headers["x-unread-count"]) == 0
    assert owner.get("/api/v1/notifications", params={"unread_only": "true"}).json() == []
    assert (
        owner.post(f"/api/v1/notifications/{uuid.uuid4()}/read", headers=csrf(owner)).status_code
        == 404
    )


def test_approval_steps_notify_the_people_who_need_to_act(fusion_estate: FusionEstate) -> None:
    fe = fusion_estate
    admin, analyst = fe.admin, as_user(fe, "analyst")
    _, activity = record_for(fe, admin, "web_shop", "Notified shop")
    aid = activity["id"]
    analyst.post(f"/api/v1/activities/{aid}/submit", headers=csrf(analyst))
    assert any(n["kind"] == "approval_requested" and n["entity_id"] == aid for n in inbox(admin))
    assert not any(
        n["kind"] == "approval_requested" and n["entity_id"] == aid for n in inbox(analyst)
    )
    admin.post(f"/api/v1/activities/{aid}/approve", json={"note": "Fine"}, headers=csrf(admin))
    decided = [
        n for n in inbox(analyst) if n["kind"] == "approval_decided" and n["entity_id"] == aid
    ]
    assert decided and decided[0]["title"].endswith(": approved")


# -- reminders -----------------------------------------------------------------------------------


def reminder_tasks(client: TestClient, name: str) -> list[dict[str, Any]]:
    return [
        t for t in client.get("/api/v1/tasks", params={"limit": 200}).json() if name in t["title"]
    ]


def test_records_past_or_near_their_review_date_get_a_task_and_a_notification_once(
    fusion_estate: FusionEstate,
) -> None:
    fe = fusion_estate
    admin, owner = fe.admin, as_user(fe, "system_owner")
    _, overdue = record_for(fe, admin, "helpdesk", "Overdue reminder record")
    _, soon = record_for(fe, admin, "newsletter", "Upcoming reminder record")
    admin.patch(
        f"/api/v1/activities/{overdue['id']}",
        json={"next_review_date": "2026-09-01"},
        headers=csrf(admin),
    )
    admin.patch(
        f"/api/v1/activities/{soon['id']}",
        json={"next_review_date": "2026-10-10"},
        headers=csrf(admin),
    )

    run = admin.post("/api/v1/reminders/run", headers=csrf(admin))
    assert run.status_code == 200, run.text
    first = run.json()
    assert (
        first["records_overdue"] >= 1
        and first["records_due"] >= 1
        and first["tasks_created"] >= 2
        and first["notifications_created"] >= 3
    )

    late_tasks = reminder_tasks(admin, "Overdue reminder record")
    assert (
        len(late_tasks) == 1
        and late_tasks[0]["due_date"] == "2026-09-01"
        and late_tasks[0]["assignee_user_id"] == str(fe.users["system_owner"].id)
    )
    assert len(reminder_tasks(admin, "Upcoming reminder record")) == 1
    assert "Record review overdue: Overdue reminder record" in titles(owner)
    assert "Record review due soon: Upcoming reminder record" in titles(owner)
    assert "Record review overdue: Overdue reminder record" in titles(
        admin
    )  # overdue also reaches the admins
    assert "Record review due soon: Upcoming reminder record" not in titles(admin)

    second = admin.post("/api/v1/reminders/run", headers=csrf(admin)).json()
    assert second["tasks_created"] == 0 and second["notifications_created"] == 0
    assert len(reminder_tasks(admin, "Overdue reminder record")) == 1

    # moving the review date makes a new reminder; the old task stays as history
    admin.patch(
        f"/api/v1/activities/{soon['id']}",
        json={"next_review_date": "2026-10-12"},
        headers=csrf(admin),
    )
    third = admin.post("/api/v1/reminders/run", headers=csrf(admin)).json()
    assert third["tasks_created"] == 1
    assert len(reminder_tasks(admin, "Upcoming reminder record")) == 2


def test_access_requests_near_their_deadline_are_reminded(fusion_estate: FusionEstate) -> None:
    fe = fusion_estate
    admin, analyst = fe.admin, as_user(fe, "analyst")
    due = analyst.post(
        "/api/v1/access-requests",
        json={
            "identifier": f"reminder.{uuid.uuid4().hex[:6]}@inbox.example",
            "received_date": "2026-09-05",
        },
        headers=csrf(analyst),
    ).json()
    late = analyst.post(
        "/api/v1/access-requests",
        json={
            "identifier": f"late.{uuid.uuid4().hex[:6]}@inbox.example",
            "received_date": "2026-08-03",
        },
        headers=csrf(analyst),
    ).json()
    summary = admin.post("/api/v1/reminders/run", headers=csrf(admin)).json()
    assert summary["requests_flagged"] >= 2
    mine = inbox(analyst)
    assert any(
        n["kind"] == "request_deadline" and n["entity_id"] == due["id"] and "due soon" in n["title"]
        for n in mine
    )
    assert any(
        n["kind"] == "request_deadline" and n["entity_id"] == late["id"] and "overdue" in n["title"]
        for n in mine
    )
    assert any(
        n["kind"] == "request_deadline" and n["entity_id"] == late["id"] for n in inbox(admin)
    )
    again = admin.post("/api/v1/reminders/run", headers=csrf(admin)).json()
    assert again["notifications_created"] == 0


def test_only_admins_run_reminders_and_the_worker_task_does_the_same(
    fusion_estate: FusionEstate,
) -> None:
    from app.workers.runtime import runtime_from_state, set_runtime
    from app.workers.tasks import review_reminders

    fe = fusion_estate
    for role in ("analyst", "viewer", "system_owner"):
        c = as_user(fe, role)
        assert c.post("/api/v1/reminders/run", headers=csrf(c)).status_code == 403
    set_runtime(runtime_from_state(fe.app.state, fe.app.state.session_factory))
    try:
        result = review_reminders.apply(args=[str(fe.org_id)]).get()
    finally:
        set_runtime(None)
    assert set(result) == {
        "records_due",
        "records_overdue",
        "tasks_created",
        "notifications_created",
        "requests_flagged",
    }
    assert result["tasks_created"] == 0  # the earlier tests already created everything that was due
    assert pipeline and fuse
