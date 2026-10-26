"""Onboarding as a background job: stages, events, retries, idempotence, progress stream.

The application runs with eager tasks (the stages run inside the request), which exercises the same
task code a worker runs; one test also drives a real Celery worker through an in-memory broker."""

import json
import threading
import time
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.workers import tasks as worker_tasks
from app.workers.celery_app import celery_app
from app.workers.runtime import runtime_from_state, set_runtime
from tests.fixtures_api import client_for, csrf
from tests.fixtures_fusion import FusionEstate, upload_notice_and_questionnaire
from tests.test_discovery_api import create_system, upload_estate_system

STAGES = ["discover", "classify", "fuse", "record", "screen"]


def new_system(fe: FusionEstate, estate_id: str, name: str, owner: Any = None) -> str:
    admin = fe.admin
    system_id = create_system(admin, name, owner=owner or fe.users["system_owner"].id)
    upload_estate_system(admin, system_id, estate_id)
    upload_notice_and_questionnaire(admin, system_id, estate_id)
    return system_id


def onboard(client: TestClient, system_id: str, **body: Any) -> Any:
    return client.post(
        f"/api/v1/systems/{system_id}/onboard", json=body or None, headers=csrf(client)
    )


def events_of(client: TestClient, job_id: str) -> list[dict[str, Any]]:
    response = client.get(f"/api/v1/jobs/{job_id}/log")
    assert response.status_code == 200, response.text
    return list(response.json())


def names(events: list[dict[str, Any]]) -> list[str]:
    return [(e["event"] + ":" + e["stage"]) if e["stage"] else e["event"] for e in events]


# -- a full run ----------------------------------------------------------------------------------


def test_onboarding_runs_every_stage_and_writes_an_event_for_each_transition(
    fusion_estate: FusionEstate,
) -> None:
    admin = fusion_estate.admin
    system_id = new_system(fusion_estate, "web_shop", "Job shop")
    response = onboard(admin, system_id, scale={"data_subjects_estimate": 1083})
    assert response.status_code == 202, response.text
    job = response.json()
    assert (
        job["state"] == "succeeded"
        and job["progress"] == {"done": 5, "total": 5}
        and job["error"] is None
    )
    assert list(job["stages"]) == STAGES and all(
        s["state"] == "succeeded" and s["attempts"] == 1 for s in job["stages"].values()
    )
    assert job["started_at"] and job["finished_at"]

    events = events_of(admin, job["id"])
    expected = ["queued", "started"]
    for stage in STAGES:
        expected += [f"stage_started:{stage}", f"stage_succeeded:{stage}"]
    assert names(events) == expected + ["succeeded"]
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)
    assert events[0]["detail"]["stages"] == STAGES

    # what the job produced is there through the ordinary API
    result = job["result"]
    assert result["discover"]["data_elements"] > 20 and result["classify"]["elements"] > 20
    assert result["fuse"]["findings_open"] > 5 and result["record"]["created"] is True
    assert (
        result["screen"]["required"] is False
        and result["screen"]["unknown"] == 0
        and result["screen"]["met"] == 1
    )  # large scale only, as the rubric says
    assert admin.get(f"/api/v1/systems/{system_id}").json()["status"] in ("DRAFTED", "FUSED")
    assert admin.get("/api/v1/findings", params={"system_id": system_id}).json()
    activities = [a for a in admin.get("/api/v1/activities").json() if system_id in a["system_ids"]]
    assert len(activities) == 1 and activities[0]["name"] == "Job shop"
    assert admin.get(f"/api/v1/activities/{activities[0]['id']}/dpia-screening").status_code == 200


def test_the_scale_given_with_the_job_reaches_the_screening(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    system_id = new_system(fusion_estate, "web_analytics", "Job analytics")
    job = onboard(admin, system_id, scale={"data_subjects_estimate": 1722}).json()
    assert job["result"]["screen"]["required"] is True and job["result"]["screen"]["unknown"] == 0


def test_running_the_job_again_with_unchanged_evidence_changes_nothing_and_costs_no_tokens(
    fusion_estate: FusionEstate,
) -> None:
    admin = fusion_estate.admin
    system_id = new_system(fusion_estate, "helpdesk", "Job helpdesk")
    first = onboard(admin, system_id).json()
    findings = sorted(
        (f["id"], f["status"])
        for f in admin.get("/api/v1/findings", params={"system_id": system_id}).json()
    )
    before = len(fusion_estate.provider.requests)
    second = onboard(admin, system_id).json()
    assert second["id"] != first["id"] and second["state"] == "succeeded"
    assert (
        second["result"]["record"]["created"] is False
        and second["result"]["record"]["changed"] is False
    )
    assert second["result"]["record"]["version"] == first["result"]["record"]["version"]
    assert (
        sorted(
            (f["id"], f["status"])
            for f in admin.get("/api/v1/findings", params={"system_id": system_id}).json()
        )
        == findings
    )
    assert len(fusion_estate.provider.requests) == before  # every model answer came from the cache


def test_a_subset_of_stages_runs_in_pipeline_order(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    system_id = new_system(fusion_estate, "newsletter", "Job newsletter")
    job = onboard(admin, system_id, stages=["classify", "discover"]).json()
    assert list(job["stages"]) == ["discover", "classify"] and job["state"] == "succeeded"
    assert admin.get(f"/api/v1/systems/{system_id}").json()["status"] == "CLASSIFIED"
    later = onboard(admin, system_id, stages=["fuse", "record"]).json()
    assert later["state"] == "succeeded" and list(later["stages"]) == ["fuse", "record"]


# -- refusals ------------------------------------------------------------------------------------


def test_a_system_without_evidence_cannot_be_onboarded(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    system_id = create_system(admin, "Job empty", owner=fusion_estate.users["system_owner"].id)
    response = onboard(admin, system_id)
    assert response.status_code == 409 and "evidence" in response.json()["detail"]


def test_only_one_job_runs_per_system_and_invalid_stages_are_refused(
    fusion_estate: FusionEstate, owner_engine: Any
) -> None:
    from sqlalchemy import text

    admin = fusion_estate.admin
    system_id = new_system(fusion_estate, "crm", "Job busy")
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO jobs (org_id, system_id, kind, state, stages, params, result) VALUES (:o, :s, 'onboarding', 'running', '{}', '{}', '{}')"
            ),
            {"o": fusion_estate.org_id, "s": system_id},
        )
    busy = onboard(admin, system_id)
    assert busy.status_code == 409 and "already running" in busy.json()["detail"]
    assert onboard(admin, system_id, stages=["bogus"]).status_code == 422
    assert onboard(admin, system_id, scale={"data_subjects_estimate": -5}).status_code == 422


def test_roles_and_visibility_of_jobs(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    system_id = new_system(
        fusion_estate, "clinic_portal", "Job clinic", owner=fusion_estate.users["analyst"].id
    )
    job = onboard(admin, system_id).json()
    owner = client_for(fusion_estate.app, fusion_estate.users["system_owner"])
    viewer = client_for(fusion_estate.app, fusion_estate.users["viewer"])
    assert (
        onboard(owner, system_id).status_code == 403
        and onboard(viewer, system_id).status_code == 403
    )
    assert job["id"] not in {j["id"] for j in owner.get("/api/v1/jobs").json()}
    assert owner.get(f"/api/v1/jobs/{job['id']}").status_code == 404
    assert owner.get(f"/api/v1/jobs/{job['id']}/log").status_code == 404
    assert viewer.get(f"/api/v1/jobs/{job['id']}").status_code == 200
    assert job["id"] in {
        j["id"] for j in viewer.get("/api/v1/jobs", params={"system_id": system_id}).json()
    }
    assert admin.get(f"/api/v1/jobs/{uuid.uuid4()}").status_code == 404


# -- retries and failure -------------------------------------------------------------------------


def test_a_transient_failure_is_retried_and_the_job_still_finishes(
    fusion_estate: FusionEstate, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = fusion_estate.admin
    system_id = new_system(fusion_estate, "staff_desktop", "Job retry")
    real = worker_tasks.execute_stage
    failures = {"left": 2}

    def flaky(db: Any, rt: Any, job: Any, system: Any, stage: str) -> dict[str, Any]:
        if stage == "classify" and failures["left"]:
            failures["left"] -= 1
            raise OperationalError("SELECT 1", {}, Exception("connection reset"))
        return real(db, rt, job, system, stage)

    monkeypatch.setattr(worker_tasks, "execute_stage", flaky)
    job = onboard(admin, system_id).json()
    assert job["state"] == "succeeded"
    log = names(events_of(admin, job["id"]))
    assert log.count("retry:classify") == 2 and log.count("stage_succeeded:classify") == 1
    assert job["stages"]["classify"]["state"] == "succeeded"
    assert job["progress"]["done"] == 5


def test_a_failure_that_will_not_pass_fails_the_job_and_tells_people(
    fusion_estate: FusionEstate, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = fusion_estate.admin
    system_id = new_system(fusion_estate, "hr_onboarding", "Job failing")
    real = worker_tasks.execute_stage

    def broken(db: Any, rt: Any, job: Any, system: Any, stage: str) -> dict[str, Any]:
        if stage == "fuse":
            raise ValueError("the questionnaire could not be read")
        return real(db, rt, job, system, stage)

    monkeypatch.setattr(worker_tasks, "execute_stage", broken)
    job = onboard(admin, system_id).json()
    assert job["state"] == "failed" and job["error"] == "fuse: the questionnaire could not be read"
    assert (
        job["stages"]["fuse"]["state"] == "failed" and job["stages"]["record"]["state"] == "pending"
    )
    assert job["progress"] == {"done": 2, "total": 5}
    log = names(events_of(admin, job["id"]))
    assert log[-2:] == ["stage_failed:fuse", "failed"] and "stage_started:record" not in log
    assert admin.get(f"/api/v1/systems/{system_id}").json()["status"] == "FAILED"
    mine = admin.get("/api/v1/notifications").json()
    assert any(
        n["kind"] == "job_failed" and "fuse" in n["title"] and n["entity_id"] == job["id"]
        for n in mine
    )

    monkeypatch.undo()  # the problem is fixed: a new job picks up where evidence is
    again = onboard(admin, system_id).json()
    assert again["state"] == "succeeded"


def test_gave_up_after_the_retry_limit(
    fusion_estate: FusionEstate, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = fusion_estate.admin
    system_id = new_system(fusion_estate, "newsletter", "Job giving up")

    def down(db: Any, rt: Any, job: Any, system: Any, stage: str) -> dict[str, Any]:
        raise OperationalError("SELECT 1", {}, Exception("database is down"))

    monkeypatch.setattr(worker_tasks, "execute_stage", down)
    job = onboard(admin, system_id).json()
    assert job["state"] == "failed" and "gave up after 3 retries" in job["error"]
    assert names(events_of(admin, job["id"])).count("retry:discover") == 3


def test_a_stage_that_already_succeeded_is_not_run_twice(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    system_id = new_system(fusion_estate, "crm", "Job redelivered")
    job = onboard(admin, system_id, stages=["discover"]).json()
    before = events_of(admin, job["id"])
    # a finished job ignores a redelivered message
    outcome = worker_tasks.onboarding_stage.apply(
        args=[job["id"], str(fusion_estate.org_id), "discover"]
    ).get()
    assert outcome == "succeeded"
    assert events_of(admin, job["id"]) == before


def test_a_job_can_be_cancelled_before_it_finishes(
    fusion_estate: FusionEstate, owner_engine: Any
) -> None:
    from sqlalchemy import text

    admin = fusion_estate.admin
    system_id = new_system(fusion_estate, "web_shop", "Job cancel")
    job_id = uuid.uuid4()
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO jobs (id, org_id, system_id, kind, state, stages, params, result) VALUES (:i, :o, :s, 'onboarding', 'queued', :st, '{}', '{}')"
            ),
            {
                "i": job_id,
                "o": fusion_estate.org_id,
                "s": system_id,
                "st": json.dumps({"discover": {"state": "pending"}}),
            },
        )
    viewer = client_for(fusion_estate.app, fusion_estate.users["viewer"])
    assert viewer.post(f"/api/v1/jobs/{job_id}/cancel", headers=csrf(viewer)).status_code == 403
    cancelled = admin.post(f"/api/v1/jobs/{job_id}/cancel", headers=csrf(admin))
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
    assert admin.post(f"/api/v1/jobs/{job_id}/cancel", headers=csrf(admin)).status_code == 409
    # a cancelled job does not run its stages
    assert (
        worker_tasks.onboarding_stage.apply(
            args=[str(job_id), str(fusion_estate.org_id), "discover"]
        ).get()
        == "cancelled"
    )
    assert names(events_of(admin, str(job_id))) == ["cancelled"]


def test_listing_and_filtering_jobs(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    system_id = new_system(fusion_estate, "helpdesk", "Job listing")
    onboard(admin, system_id, stages=["discover"])
    response = admin.get("/api/v1/jobs", params={"system_id": system_id, "state": "succeeded"})
    assert response.status_code == 200 and len(response.json()) == 1
    assert response.headers["x-total-count"] == "1"
    assert (
        admin.get("/api/v1/jobs", params={"system_id": system_id, "state": "failed"}).json() == []
    )
    assert admin.get("/api/v1/jobs", params={"state": "nonsense"}).status_code == 422
    assert admin.get("/api/v1/jobs", params={"limit": 500}).status_code == 422


# -- the progress stream -------------------------------------------------------------------------


def read_stream(
    client: TestClient, url: str, headers: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    with client.stream("GET", url, headers=headers or {}) as response:
        assert response.status_code == 200 and response.headers["content-type"].startswith(
            "text/event-stream"
        )
        assert response.headers["cache-control"] == "no-store"
        for line in response.iter_lines():
            if line.startswith(":"):
                continue
            if not line:
                if current:
                    frames.append(current)
                    current = {}
                continue
            key, _, value = line.partition(": ")
            current[key] = value
    return frames


def test_progress_is_streamed_as_server_sent_events_and_ends(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    system_id = new_system(fusion_estate, "web_analytics", "Job stream")
    job = onboard(admin, system_id).json()
    frames = read_stream(admin, f"/api/v1/jobs/{job['id']}/events")
    assert [f["event"] for f in frames][-2:] == ["succeeded", "end"]
    assert json.loads(frames[-1]["data"]) == {"state": "succeeded"}
    ids = [int(f["id"]) for f in frames if "id" in f]
    assert ids == sorted(ids) and len(ids) == len(events_of(admin, job["id"]))
    stage_frame = next(f for f in frames if f["event"] == "stage_succeeded")
    assert json.loads(stage_frame["data"])["stage"] == "discover"

    # a client that reconnects receives only what it missed
    cut = ids[5]
    resumed = read_stream(
        admin, f"/api/v1/jobs/{job['id']}/events", headers={"Last-Event-ID": str(cut)}
    )
    assert [int(f["id"]) for f in resumed if "id" in f] == [i for i in ids if i > cut]
    assert [
        f["event"] for f in read_stream(admin, f"/api/v1/jobs/{job['id']}/events?after={ids[-1]}")
    ] == ["end"]


def test_the_stream_is_private(fusion_estate: FusionEstate, other_org: Any) -> None:
    admin = fusion_estate.admin
    system_id = new_system(
        fusion_estate, "newsletter", "Job private stream", owner=fusion_estate.users["analyst"].id
    )
    job = onboard(admin, system_id, stages=["discover"]).json()
    owner = client_for(fusion_estate.app, fusion_estate.users["system_owner"])
    assert owner.get(f"/api/v1/jobs/{job['id']}/events").status_code == 404
    stranger = client_for(fusion_estate.app, other_org.users["admin"])
    assert stranger.get(f"/api/v1/jobs/{job['id']}/events").status_code == 404
    assert stranger.get(f"/api/v1/jobs/{job['id']}").status_code == 404


# -- a real worker -------------------------------------------------------------------------------


def test_a_real_celery_worker_runs_the_stages_from_a_queue(fusion_estate: FusionEstate) -> None:
    """The same tasks, not eager: queued on an in-memory broker and run by a worker thread."""
    from celery.contrib.testing.worker import start_worker

    admin = fusion_estate.admin
    system_id = new_system(fusion_estate, "crm", "Job real worker")
    settings = fusion_estate.app.state.settings
    original = {
        k: celery_app.conf[k] for k in ("broker_url", "result_backend", "task_always_eager")
    }
    celery_app.conf.update(
        broker_url="memory://", result_backend="cache+memory://", task_always_eager=False
    )
    app_settings = settings.model_copy(update={"celery_eager": False})
    fusion_estate.app.state.settings = app_settings
    set_runtime(
        runtime_from_state(fusion_estate.app.state, fusion_estate.app.state.session_factory)
    )
    try:
        with start_worker(
            celery_app, perform_ping_check=False, pool="solo", concurrency=1, loglevel="WARNING"
        ):
            response = onboard(admin, system_id, stages=["discover", "classify"])
            assert response.status_code == 202
            job_id = response.json()["id"]
            assert response.json()["state"] == "queued"
            deadline = time.monotonic() + 120
            state = "queued"
            while time.monotonic() < deadline and state not in ("succeeded", "failed"):
                time.sleep(0.5)
                state = admin.get(f"/api/v1/jobs/{job_id}").json()["state"]
            assert state == "succeeded", admin.get(f"/api/v1/jobs/{job_id}").json()
            assert names(events_of(admin, job_id))[-1] == "succeeded"
            assert threading.active_count() >= 1
    finally:
        fusion_estate.app.state.settings = settings
        celery_app.conf.update(**original)
        set_runtime(None)


def test_an_unreachable_queue_fails_the_request_cleanly(
    fusion_estate: FusionEstate, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no broker the API answers 503 and leaves no job waiting for a worker that never comes."""
    admin = fusion_estate.admin
    system_id = new_system(fusion_estate, "newsletter", "Job no broker")

    def unreachable(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("broker down")

    monkeypatch.setattr("app.api.routes.jobs.dispatch", unreachable)
    response = onboard(admin, system_id)
    assert response.status_code == 503 and response.json()["error"]["code"] == "unavailable"
    listed = admin.get("/api/v1/jobs", params={"system_id": system_id}).json()
    assert [j["state"] for j in listed] == ["failed"] and listed[0][
        "error"
    ] == "The job queue is not reachable"
    monkeypatch.undo()
    assert (
        onboard(admin, system_id, stages=["discover"]).status_code == 202
    )  # a failed job does not block the next
