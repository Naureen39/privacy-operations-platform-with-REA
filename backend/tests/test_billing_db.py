"""Billing and analytics against a real database: the invoice run, the nightly snapshots, the
simulated history and its reconciliation, and the endpoints. A database of its own keeps the
simulated organisations out of every other test."""

import csv
import io
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.analytics import compliance, nightly
from app.analytics.daily import rebuild
from app.billing import pricing, service, usage
from app.core.config import Settings
from app.db.enums import FindingSeverity, FindingStatus, InvoiceStatus, Role, UsageKind
from app.db.models import Finding, Invoice, InvoiceLine, Subscription, UsageEvent
from app.db.session import (
    TenantContext,
    TenantSession,
    make_engine,
    make_session_factory,
    tenant_session,
)
from app.main import create_app
from app.seeding import compliance_history
from app.seeding.billing_history import seed_billing_history
from app.services import provisioning
from app.workers import runtime
from tests.conftest import alembic_config, app_url, create_database
from tests.fixtures_api import ENCRYPTION_KEY, JWT_SECRET, PASSWORD, client_for, csrf

TODAY = date(2026, 10, 26)


@dataclass
class Env:
    owner: Engine
    factory: sessionmaker[TenantSession]
    app: FastAPI
    host_id: uuid.UUID
    customer_id: uuid.UUID
    users: dict[str, Any]  # "host_admin", "host_viewer", "admin", "viewer", "owner"
    summary: Any

    def client(self, who: str) -> TestClient:
        return client_for(self.app, self.users[who])

    def session(self, org_id: uuid.UUID) -> Any:
        return tenant_session(self.factory, TenantContext(org_id=org_id))


@pytest.fixture(scope="module")
def env(admin_url: URL, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    url = create_database(admin_url, f"billing_{uuid.uuid4().hex[:8]}")
    command.upgrade(alembic_config(url.render_as_string(hide_password=False)), "head")
    owner = create_engine(url)
    app_engine = make_engine(app_url(url).render_as_string(hide_password=False), pool_size=3)
    factory = make_session_factory(app_engine)

    host_id = provisioning.create_organization(owner, "Host", f"host-{uuid.uuid4().hex[:6]}")
    customer_id = provisioning.create_organization(
        owner, "Customer", f"cust-{uuid.uuid4().hex[:6]}"
    )
    users: dict[str, Any] = {}
    for key, org, role in (
        ("host_admin", host_id, Role.ADMIN),
        ("host_viewer", host_id, Role.VIEWER),
        ("admin", customer_id, Role.ADMIN),
        ("viewer", customer_id, Role.VIEWER),
        ("owner", customer_id, Role.SYSTEM_OWNER),
    ):
        users[key] = provisioning.create_user(
            owner, org, f"{key}-{uuid.uuid4().hex[:6]}@billing.example", key, PASSWORD, role
        )
    settings = Settings(
        jwt_secret=SecretStr(JWT_SECRET),
        evidence_encryption_key=SecretStr(ENCRYPTION_KEY),
        upload_dir=str(tmp_path_factory.mktemp("billing") / "evidence"),
        login_rate_limit="1000/minute",
        default_rate_limit="100000/minute",
        embedding_local_files_only=True,
        reference_date=TODAY,
        celery_eager=True,
        leads_org_id=host_id,
        migration_database_url=url.render_as_string(hide_password=False),
        cors_allowed_origins=["https://app.example.test"],
    )
    app = create_app(settings, factory)
    summary = seed_billing_history(
        owner, factory, seed=42, organisations=16, months=8, as_of=TODAY, reset=True
    )
    runtime.set_runtime(runtime.runtime_from_state(app.state, factory))
    yield Env(owner, factory, app, host_id, customer_id, users, summary)
    runtime.set_runtime(None)
    app_engine.dispose()
    owner.dispose()


# -- subscriptions and the invoice run -----------------------------------------------------------


def test_the_price_list_is_seeded_by_the_migration(env: Env) -> None:
    plans = env.client("admin").get("/api/v1/billing/plans").json()
    assert [p["code"] for p in plans] == ["starter", "professional", "enterprise"]
    assert [p["monthly_fee_cents"] for p in plans] == [0, 39_900, 180_000]


def test_the_price_list_is_public_for_the_pricing_page(env: Env) -> None:
    anonymous = TestClient(env.app, base_url="https://testserver")
    plans = anonymous.get("/api/v1/public/plans")
    assert plans.status_code == 200
    assert [p["code"] for p in plans.json()] == ["starter", "professional", "enterprise"]
    assert plans.json()[1]["included_systems"] == 25


@pytest.fixture
def fresh_org(env: Env) -> Iterator[uuid.UUID]:
    """An organisation of its own that is removed afterwards, so its subscriptions never reach the
    platform wide figures that the simulated history is checked against."""
    org = provisioning.create_organization(env.owner, "Run test", f"run-{uuid.uuid4().hex[:8]}")
    yield org
    with env.owner.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM invoice_lines WHERE invoice_id IN (SELECT id FROM invoices WHERE org_id = :o)"
            ),
            {"o": org},
        )
        for table in ("invoices", "usage_events", "subscriptions"):
            conn.execute(text(f"DELETE FROM {table} WHERE org_id = :o"), {"o": org})  # noqa: S608
        conn.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})


def test_changing_plan_ends_the_old_subscription_and_a_same_day_change_replaces_it(
    env: Env, fresh_org: uuid.UUID
) -> None:
    with env.session(fresh_org) as db:
        first = service.subscribe(db, "starter", date(2026, 1, 10))
        with pytest.raises(service.BillingError, match="already"):
            service.subscribe(db, "starter", date(2026, 1, 20))
        upgraded = service.subscribe(db, "professional", date(2026, 3, 1))
        db.refresh(first)
        assert first.ended_at == date(2026, 3, 1) and first.status.value == "canceled"
        assert upgraded.base_fee_cents == 39_900 and upgraded.ended_at is None
        replaced = service.subscribe(db, "enterprise", date(2026, 3, 1))
        assert replaced.id == upgraded.id and replaced.base_fee_cents == 180_000
        assert service.active_subscription(db, date(2026, 2, 28)).id == first.id  # type: ignore[union-attr]
        with pytest.raises(service.BillingError, match="Unknown"):
            service.subscribe(db, "platinum", date(2026, 4, 1))
        service.cancel(db, date(2026, 6, 1))
        assert service.active_subscription(db, date(2026, 6, 1)) is None


def test_the_invoice_run_prices_the_month_once_and_refuses_an_unfinished_one(
    env: Env, fresh_org: uuid.UUID
) -> None:
    org = fresh_org
    with env.session(org) as db:
        service.subscribe(db, "professional", date(2026, 5, 1))
        stamp = datetime(2026, 8, 31, 23, 59, tzinfo=UTC)
        usage.record_usage(db, UsageKind.ACTIVE_SYSTEMS, 28, at=stamp)
        usage.record_usage(
            db, UsageKind.REQUESTS_PROCESSED, 40, at=datetime(2026, 8, 5, tzinfo=UTC)
        )
        usage.record_usage(
            db, UsageKind.REQUESTS_PROCESSED, 20, at=datetime(2026, 8, 20, tzinfo=UTC)
        )
        usage.record_usage(
            db, UsageKind.REQUESTS_PROCESSED, 99, at=datetime(2026, 9, 2, tzinfo=UTC)
        )
        with pytest.raises(service.BillingError, match="not over"):
            service.run_invoice(db, date(2026, 10, 1), date(2026, 10, 31), TODAY)
        result = service.run_invoice(db, date(2026, 8, 1), date(2026, 8, 31), TODAY, simulated=True)
        assert result.created and result.invoice is not None
        assert result.invoice.total_cents == 39_900 + 3 * 1_500 + 10 * 800
        assert result.invoice.number == "INV-202608-0001"
        lines = db.query(InvoiceLine).filter_by(invoice_id=result.invoice.id).all()
        assert sum(line.amount_cents for line in lines) == result.invoice.total_cents
        again = service.run_invoice(db, date(2026, 8, 1), date(2026, 8, 31), TODAY)
        assert (
            not again.created
            and again.invoice is not None
            and again.invoice.id == result.invoice.id
        )
        assert db.query(Invoice).count() == 1
        # a month with no subscription in force at its end has no invoice
        none = service.run_invoice(db, date(2026, 4, 1), date(2026, 4, 30), TODAY)
        assert none.invoice is None and "no subscription" in none.reason


def test_the_invoice_run_measures_systems_and_tokens_from_the_tenant_tables(
    env: Env, fresh_org: uuid.UUID
) -> None:
    org = fresh_org
    with env.session(org) as db:
        db.execute(
            text(
                "INSERT INTO systems (org_id, name, slug, created_at) VALUES "
                "(:o, 'a', 'a', '2026-08-02'), (:o, 'b', 'b', '2026-08-03'), (:o, 'c', 'c', '2026-09-04')"
            ),
            {"o": org},
        )
        service.subscribe(db, "starter", date(2026, 7, 1))
        service.run_invoice(db, date(2026, 8, 1), date(2026, 8, 31), TODAY)
        events = db.query(UsageEvent).filter_by(kind=UsageKind.ACTIVE_SYSTEMS).all()
        assert [e.quantity for e in events] == [2]  # the system made in September is not counted
        service.run_invoice(db, date(2026, 8, 1), date(2026, 8, 31), TODAY)
        assert db.query(UsageEvent).filter_by(kind=UsageKind.ACTIVE_SYSTEMS).count() == 1


def test_payment_states(env: Env, fresh_org: uuid.UUID) -> None:
    with env.session(fresh_org) as db:
        service.subscribe(db, "professional", date(2026, 5, 1))
        invoice = service.run_invoice(db, date(2026, 8, 1), date(2026, 8, 31), TODAY).invoice
        assert invoice is not None
        service.mark_paid(invoice)
        assert invoice.status is InvoiceStatus.PAID and invoice.paid_at is not None
        with pytest.raises(service.BillingError, match="already"):
            service.mark_paid(invoice)
        with pytest.raises(service.BillingError, match="paid invoice"):
            service.void(invoice)
    # the stand-in outcome is deterministic and never pays before the month ends
    first = service.simulated_outcome("INV-1", date(2026, 8, 31), TODAY)
    assert first == service.simulated_outcome("INV-1", date(2026, 8, 31), TODAY)
    status, paid_at = service.simulated_outcome("INV-1", date(2026, 8, 31), date(2026, 8, 31))
    assert status is InvoiceStatus.OPEN and paid_at is None


# -- the simulated history -----------------------------------------------------------------------


def _seeded(env: Env, sql: str, **params: Any) -> list[Any]:
    with env.owner.connect() as conn:
        return list(conn.execute(text(sql), params))


def test_the_history_is_simulated_end_to_end_and_complete(env: Env) -> None:
    s = env.summary
    assert s.organisations == 16 and s.invoices > 30 and s.subscriptions >= 16
    assert _seeded(env, "SELECT count(*) FROM organizations WHERE is_simulated")[0][0] == 16
    assert _seeded(env, "SELECT count(*) FROM subscriptions WHERE NOT is_simulated")[0][0] == 0
    assert _seeded(env, "SELECT count(*) FROM invoices WHERE NOT is_simulated")[0][0] == 0
    assert _seeded(env, "SELECT count(*) FROM usage_events WHERE NOT is_simulated")[0][0] == 0
    statuses = {r[0] for r in _seeded(env, "SELECT DISTINCT status FROM invoices")}
    assert "paid" in statuses
    days = _seeded(env, "SELECT min(metric_date), max(metric_date), count(*) FROM daily_metrics")[0]
    assert days[1] == TODAY and days[2] == (days[1] - days[0]).days + 1


def test_the_same_seed_gives_the_same_history(env: Env) -> None:
    before = _seeded(env, "SELECT metric_date, mrr_cents, requests FROM daily_metrics ORDER BY 1")
    again = seed_billing_history(
        env.owner, env.factory, seed=42, organisations=16, months=8, as_of=TODAY, reset=True
    )
    after = _seeded(env, "SELECT metric_date, mrr_cents, requests FROM daily_metrics ORDER BY 1")
    assert before == after and again.invoices == env.summary.invoices
    with pytest.raises(RuntimeError, match="already exists"):
        seed_billing_history(env.owner, env.factory, as_of=TODAY, organisations=2, months=2)


def test_mrr_movements_add_up_day_by_day_and_month_by_month(env: Env) -> None:
    rows = _seeded(
        env,
        "SELECT metric_date, mrr_cents, new_mrr_cents, expansion_mrr_cents, contraction_mrr_cents, "
        "churned_mrr_cents FROM daily_metrics ORDER BY metric_date",
    )
    previous = 0
    for day, mrr, new, expansion, contraction, churned in rows:
        assert mrr - previous == new + expansion - contraction - churned, day
        previous = mrr
    assert rows[-1][1] > 0
    body = (
        env.client("host_admin")
        .get(
            "/api/v1/analytics/revenue",
            params={"start": rows[0][0], "end": rows[-1][0], "granularity": "month"},
        )
        .json()
    )
    opening = 0
    for point in body["series"]:
        net = (
            point["new_mrr_cents"] + point["expansion_mrr_cents"]
            - point["contraction_mrr_cents"] - point["churned_mrr_cents"]
        )  # fmt: skip
        assert point["mrr_cents"] - opening == net, point["period"]
        opening = point["mrr_cents"]


def test_invoice_lines_equal_the_revenue_shown(env: Env) -> None:
    rows = _seeded(
        env,
        "SELECT i.period_end, "
        "sum(l.amount_cents) FILTER (WHERE l.kind = 'base'), "
        "coalesce(sum(l.amount_cents) FILTER (WHERE l.kind <> 'base' AND i.status <> 'void'), 0) "
        "FROM invoices i JOIN invoice_lines l ON l.invoice_id = i.id "
        "GROUP BY i.period_end ORDER BY 1",
    )
    assert len(rows) >= 6
    metrics = {
        r[0]: (r[1], r[2])
        for r in _seeded(
            env, "SELECT metric_date, mrr_cents, usage_revenue_cents FROM daily_metrics"
        )
    }
    # the invoice total is the sum of its lines, for every invoice
    assert not _seeded(
        env,
        "SELECT 1 FROM invoices i WHERE i.total_cents <> "
        "(SELECT coalesce(sum(amount_cents), 0) FROM invoice_lines WHERE invoice_id = i.id)",
    )
    for period_end, base, extra in rows:
        mrr, usage_revenue = metrics[period_end]
        assert (
            base == mrr
        ), period_end  # the base fees billed for a month are the MRR on its last day
        assert extra == usage_revenue, period_end  # and the extra lines are the usage revenue shown
    # and the endpoint reports the same usage revenue as the invoices carry
    body = (
        env.client("host_admin")
        .get(
            "/api/v1/analytics/revenue",
            params={"start": TODAY - timedelta(days=250), "end": TODAY, "granularity": "month"},
        )
        .json()
    )
    shown = sum(p["usage_revenue_cents"] for p in body["series"])
    assert shown == sum(r[2] for r in rows if r[0] >= TODAY - timedelta(days=250))
    assert body["totals"]["usage_revenue_cents"] == shown and body["simulated"] is True


def test_derived_figures_match_their_definitions(env: Env) -> None:
    row = _seeded(
        env,
        "SELECT mrr_cents, paying_accounts, arpa_cents, accounts FROM daily_metrics "
        "WHERE metric_date = :d",
        d=TODAY,
    )[0]
    expected_mrr = _seeded(
        env,
        "SELECT coalesce(sum(base_fee_cents), 0) FROM subscriptions "
        "WHERE started_at <= :d AND (ended_at IS NULL OR ended_at > :d)",
        d=TODAY,
    )[0][0]
    assert row[0] == expected_mrr and row[2] == round(row[0] / row[1]) and row[3] >= row[1]


# -- nightly snapshots ---------------------------------------------------------------------------


def test_the_nightly_job_writes_compliance_and_platform_rows_for_every_organisation(
    env: Env,
) -> None:
    summary = nightly.run_nightly(env.owner, env.factory, TODAY, days=3)
    assert summary.organisations >= 2 + 16 and summary.days == 3 and summary.metric_rows == 3
    rows = _seeded(
        env, "SELECT count(*) FROM compliance_daily_metrics WHERE metric_date = :d", d=TODAY
    )
    assert rows[0][0] == summary.organisations
    with env.session(env.customer_id) as db:  # a tenant sees only its own row
        assert db.execute(text("SELECT count(*) FROM compliance_daily_metrics")).scalar() == 3


def test_the_monthly_run_invoices_every_organisation_once(env: Env, fresh_org: uuid.UUID) -> None:
    org = fresh_org
    with env.session(org) as db:
        service.subscribe(db, "professional", date(2026, 6, 1))
    first = nightly.run_invoices(env.owner, env.factory, date(2026, 10, 1))
    second = nightly.run_invoices(env.owner, env.factory, date(2026, 10, 1))
    assert first.created >= 1 and second.created == 0
    with env.session(org) as db:
        assert db.query(Invoice).filter_by(period_start=date(2026, 9, 1)).count() == 1


# -- compliance history --------------------------------------------------------------------------


def test_the_compliance_history_is_rebuilt_from_timestamps(env: Env) -> None:
    org = provisioning.create_organization(env.owner, "History", f"hist-{uuid.uuid4().hex[:8]}")
    with env.session(org) as db:
        summary = compliance_history.seed_compliance_history(db, seed=42, as_of=TODAY, months=4)
        assert summary.snapshots > 100 and summary.findings > 20 and summary.requests >= 8
        latest = compliance.store(db, TODAY, simulated=True)
        assert (
            latest.open_findings["total"]
            == db.query(Finding).filter_by(status=FindingStatus.OPEN).count()
        )
        assert (
            latest.requests_open
            == db.execute(
                text("SELECT count(*) FROM access_requests WHERE status = 'searching'")
            ).scalar()
        )
        assert latest.approved_records == summary.activities
        assert 0 <= latest.stale_records <= summary.activities
        # a past day shows what was known then: fewer records existed three months earlier
        early = db.execute(
            text("SELECT approved_records FROM compliance_daily_metrics WHERE metric_date = :d"),
            {"d": TODAY - timedelta(days=110)},
        ).scalar()
        assert early is not None and early < latest.approved_records
        by_severity = latest.open_findings["by_severity"]
        assert sum(by_severity.values()) == latest.open_findings["total"]
        assert sum(latest.open_findings["by_type"].values()) == latest.open_findings["total"]
        compliance_history.reset(db)
        assert db.execute(text("SELECT count(*) FROM compliance_daily_metrics")).scalar() == 0


# -- endpoints -----------------------------------------------------------------------------------


def test_revenue_and_platform_figures_are_for_the_host_administrators_only(env: Env) -> None:
    for who, expected in (
        ("host_admin", 200),
        ("host_viewer", 403),
        ("admin", 403),
        ("owner", 403),
    ):
        for path in ("revenue", "platform"):
            got = env.client(who).get(f"/api/v1/analytics/{path}").status_code
            assert got == expected, (who, path, got)
    assert (
        TestClient(env.app, base_url="https://testserver")
        .get("/api/v1/analytics/revenue")
        .status_code
        == 401
    )
    assert env.client("admin").post("/api/v1/analytics/refresh", headers={}).status_code in (
        403,
        401,
    )


def test_range_granularity_comparison_and_validation(env: Env) -> None:
    host = env.client("host_admin")
    base = "/api/v1/analytics/revenue"
    week = host.get(
        base, params={"start": "2026-09-01", "end": "2026-09-30", "granularity": "week"}
    )
    assert week.status_code == 200 and week.json()["granularity"] == "week"
    assert [p["period"] for p in week.json()["series"]][0] == "2026-08-31"  # a Monday
    compared = host.get(
        base, params={"start": "2026-09-01", "end": "2026-09-30", "compare": True}
    ).json()
    assert compared["previous"] is not None and set(compared["change"]) == set(compared["totals"])
    assert len(compared["series"]) == 30
    previous = host.get(base, params={"start": "2026-08-02", "end": "2026-08-31"}).json()
    assert compared["previous"] == previous["totals"]
    assert host.get(base).json()["previous"] is None
    for bad in (
        {"start": "2026-09-30", "end": "2026-09-01"},
        {"granularity": "year"},
        {"format": "xml"},
        {"start": "2020-01-01", "end": "2026-09-01"},
        {"start": "not-a-date"},
    ):
        assert host.get(base, params=bad).status_code == 422, bad
    platform = host.get("/api/v1/analytics/platform", params={"granularity": "month"}).json()
    assert "tokens_by_provider" in platform["series"][-1] and platform["totals"]["requests"] >= 0


def test_csv_export_and_the_sixty_second_cache(env: Env) -> None:
    host = env.client("host_admin")
    params = {"start": "2026-09-01", "end": "2026-09-10", "format": "csv"}
    first = host.get("/api/v1/analytics/revenue", params=params)
    assert first.headers["content-type"].startswith("text/csv")
    assert "attachment" in first.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(first.text)))
    assert rows[0][:3] == ["period", "last_day", "days"] and len(rows) == 11
    assert first.headers["x-cache"] == "miss"
    assert host.get("/api/v1/analytics/revenue", params=params).headers["x-cache"] == "hit"
    json_params = {"start": "2026-09-01", "end": "2026-09-10"}
    assert host.get("/api/v1/analytics/revenue", params=json_params).headers["x-cache"] == "miss"
    # rebuilding the snapshots drops the cache
    assert host.post("/api/v1/analytics/refresh", headers=csrf(host)).status_code == 202
    assert host.get("/api/v1/analytics/revenue", params=params).headers["x-cache"] == "miss"


def test_compliance_figures_belong_to_the_organisation(env: Env) -> None:
    nightly.run_nightly(env.owner, env.factory, TODAY, days=2)
    admin, viewer = env.client("admin"), env.client("viewer")
    mine = admin.get("/api/v1/analytics/compliance", params={"compare": True})
    assert mine.status_code == 200 and mine.json()["previous"] is not None
    assert viewer.get("/api/v1/analytics/compliance").status_code == 200
    assert env.client("owner").get("/api/v1/analytics/compliance").status_code == 403
    other = env.client("host_admin").get("/api/v1/analytics/compliance").json()
    assert other["series"] != [] and mine.json()["series"] != []
    # the host's rows are its own: nothing of the customer leaks into them
    with env.session(env.customer_id) as db:
        db.add(
            Finding(
                type="t",
                severity=FindingSeverity.HIGH,
                title="visible only to the customer",
                created_at=datetime(
                    2026, 10, 20, 9, 0, tzinfo=UTC
                ),  # not the wall clock: TODAY is pinned
            )
        )
    nightly.run_nightly(env.owner, env.factory, TODAY, days=1)
    customer = admin.get(
        "/api/v1/analytics/compliance", params={"start": str(TODAY), "end": str(TODAY)}
    ).json()
    host = (
        env.client("host_admin")
        .get("/api/v1/analytics/compliance", params={"start": str(TODAY), "end": str(TODAY)})
        .json()
    )
    assert customer["series"][0]["open_findings"]["total"] == 1
    assert host["series"][0]["open_findings"]["total"] == 0


def test_the_billing_endpoints(env: Env, fresh_org: uuid.UUID) -> None:
    org = fresh_org
    user = provisioning.create_user(
        env.owner, org, f"b-{uuid.uuid4().hex[:6]}@billing.example", "B", PASSWORD, Role.ADMIN
    )
    viewer = provisioning.create_user(
        env.owner, org, f"v-{uuid.uuid4().hex[:6]}@billing.example", "V", PASSWORD, Role.VIEWER
    )
    admin = client_for(env.app, user)
    assert admin.get("/api/v1/billing/subscription").status_code == 404
    assert client_for(env.app, viewer).get("/api/v1/billing/invoices").status_code == 403
    assert client_for(env.app, viewer).get("/api/v1/billing/plans").status_code == 200
    assert (
        admin.put(
            "/api/v1/billing/subscription", json={"plan": "gold"}, headers=csrf(admin)
        ).status_code
        == 404
    )
    changed = admin.put(
        "/api/v1/billing/subscription", json={"plan": "professional"}, headers=csrf(admin)
    )
    assert changed.status_code == 200 and changed.json()["plan"] == "professional"
    assert (
        admin.put(
            "/api/v1/billing/subscription", json={"plan": "professional"}, headers=csrf(admin)
        ).status_code
        == 409
    )
    usage_now = admin.get("/api/v1/billing/usage").json()
    assert usage_now["complete"] is False and usage_now["projected_cents"] == 39_900
    assert admin.get("/api/v1/billing/usage", params={"month": "2026-13"}).status_code == 422

    # a finished month needs a subscription that was in force at its end
    with env.session(org) as db:
        sub = db.query(Subscription).one()
        sub.started_at = date(2026, 6, 1)
        usage.record_usage(
            db, UsageKind.REQUESTS_PROCESSED, 55, at=datetime(2026, 9, 3, tzinfo=UTC)
        )
        db.execute(
            text(
                "INSERT INTO systems (org_id, name, slug, created_at) "
                "SELECT :o, 's' || n, 's' || n, '2026-09-01' FROM generate_series(1, 26) n"
            ),
            {"o": org},
        )
    run = admin.post("/api/v1/billing/invoice-run", json={}, headers=csrf(admin))
    assert run.status_code == 200 and run.json()["created"] is True
    invoice = run.json()["invoice"]
    assert invoice["period_start"] == "2026-09-01"
    assert invoice["total_cents"] == 39_900 + 1_500 + 5 * 800
    assert sum(line["amount_cents"] for line in invoice["lines"]) == invoice["total_cents"]
    again = admin.post("/api/v1/billing/invoice-run", json={}, headers=csrf(admin)).json()
    assert again["created"] is False and again["invoice"]["id"] == invoice["id"]
    assert (
        admin.post(
            "/api/v1/billing/invoice-run", json={"month": "2026-10"}, headers=csrf(admin)
        ).status_code
        == 409
    )
    assert (
        admin.post(
            "/api/v1/billing/invoice-run", json={"month": "10/2026"}, headers=csrf(admin)
        ).status_code
        == 422
    )

    listed = admin.get("/api/v1/billing/invoices")
    assert (
        listed.headers["x-total-count"] == "1" and listed.json()[0]["number"] == invoice["number"]
    )
    assert admin.get("/api/v1/billing/invoices", params={"status_filter": "paid"}).json() == []
    assert (
        admin.get(f"/api/v1/billing/invoices/{invoice['id']}").json()["lines"] == invoice["lines"]
    )
    assert admin.get(f"/api/v1/billing/invoices/{uuid.uuid4()}").status_code == 404
    paid = admin.post(f"/api/v1/billing/invoices/{invoice['id']}/pay", headers=csrf(admin))
    assert paid.json()["status"] == "paid" and paid.json()["paid_at"]
    assert (
        admin.post(f"/api/v1/billing/invoices/{invoice['id']}/pay", headers=csrf(admin)).status_code
        == 409
    )
    done = admin.get("/api/v1/billing/usage", params={"month": "2026-09"}).json()
    assert done["complete"] is True and done["requests"] == 55 and done["active_systems"] == 26

    # another organisation cannot see or pay this invoice
    other = env.client("admin")
    assert other.get(f"/api/v1/billing/invoices/{invoice['id']}").status_code == 404


def test_metric_snapshot_rebuild_is_idempotent(env: Env) -> None:
    sql = (
        "SELECT metric_date, mrr_cents, new_mrr_cents, usage_revenue_cents, accounts, systems, "
        "requests, nrr_bp, gross_churn_bp FROM daily_metrics ORDER BY metric_date"
    )
    before = _seeded(env, sql)
    rebuild(env.owner, TODAY - timedelta(days=30), TODAY)
    assert _seeded(env, sql) == before
    assert pricing.parse_month("2026-09")[1] < TODAY
