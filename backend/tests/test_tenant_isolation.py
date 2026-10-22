import uuid
from datetime import date

import pytest
from sqlalchemy import Engine, delete, select, text, update
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import sessionmaker

from app.db.enums import (
    DocumentType,
    EvidenceKind,
    Extractor,
    FindingSeverity,
    LeadKind,
    LlmCallStatus,
    Role,
)
from app.db.models import (
    AccessRequest,
    AuditLog,
    DataElement,
    DiscoveryEvidence,
    DiscoveryRun,
    Document,
    DocumentChunk,
    Dpia,
    DpiaScreening,
    EvidenceItem,
    Finding,
    Lead,
    LlmCall,
    Membership,
    Organization,
    ProcessingActivity,
    Recipient,
    System,
    User,
)
from app.db.repositories import AuditLogRepository, SystemRepository, UserRepository
from app.db.session import TenantContext, TenantSession, set_tenant, tenant_session
from tests.conftest import OrgFixture

NON_TENANT_TABLES = {
    "users",
    "refresh_tokens",
    "plans",
    "regulation_chunks",
    "daily_metrics",
    "taxonomy_entries",
}
VECTOR = [0.1] * 384


def populate(factory: sessionmaker[TenantSession], org: OrgFixture, user_id: uuid.UUID) -> None:
    """Create a connected graph of rows as the application role, never passing org_id."""
    with tenant_session(factory, TenantContext(org.id, user_id)) as s:
        system = System(name=f"System {org.slug}", slug="shop", owner_user_id=user_id)
        s.add(system)
        s.flush()
        item = EvidenceItem(
            system_id=system.id,
            kind=EvidenceKind.HAR,
            filename="capture.har",
            storage_path="/evidence/x",
            checksum_sha256="0" * 64,
            size_bytes=10,
        )
        run = DiscoveryRun(system_id=system.id)
        s.add_all([item, run])
        s.flush()
        evidence = DiscoveryEvidence(
            run_id=run.id, evidence_item_id=item.id, extractor=Extractor.REA
        )
        s.add(evidence)
        s.flush()
        s.add_all(
            [
                DataElement(
                    system_id=system.id,
                    name="email",
                    category="contact",
                    evidence_id=evidence.id,
                    embedding=VECTOR,
                ),
                Recipient(
                    system_id=system.id,
                    domain="analytics.example",
                    evidence_id=evidence.id,
                ),
                Finding(
                    system_id=system.id,
                    type="undeclared_recipient",
                    severity=FindingSeverity.HIGH,
                    title="Recipient not declared",
                ),
            ]
        )
        activity = ProcessingActivity(name="Order handling")
        s.add(activity)
        s.flush()
        s.add(Dpia(activity_id=activity.id))
        s.add(DpiaScreening(activity_id=activity.id, criteria_met=2, required=True))
        doc = Document(doc_type=DocumentType.POLICY, title="Policy", system_id=system.id)
        s.add(doc)
        s.flush()
        s.add(
            DocumentChunk(
                document_id=doc.id,
                chunk_index=0,
                text="We keep order records for seven years.",
                embedding=VECTOR,
            )
        )
        s.add(
            AccessRequest(
                subject_hash="h" * 64,
                received_date=date(2026, 1, 5),
                deadline_date=date(2026, 2, 5),
            )
        )
        s.add(Lead(kind=LeadKind.CONTACT, name="Sample", email="sample@example.test"))
        s.add(
            LlmCall(
                provider="groq",
                model="m",
                task="t",
                status=LlmCallStatus.OK,
                system_id=system.id,
            )
        )
        s.add(Membership(user_id=user_id, role=Role.ANALYST))
        s.add(AuditLog(action="seed"))


@pytest.fixture
def populated(
    session_factory: sessionmaker[TenantSession],
    owner_engine: Engine,
    two_orgs: tuple[OrgFixture, OrgFixture],
) -> tuple[OrgFixture, OrgFixture, uuid.UUID, uuid.UUID]:
    org_a, org_b = two_orgs
    with owner_engine.begin() as conn:
        users = [
            conn.execute(
                text(
                    "INSERT INTO users (email, full_name, password_hash) "
                    "VALUES (:e, 'Sample User', 'x') RETURNING id"
                ),
                {"e": f"user-{uuid.uuid4().hex[:8]}@example.test"},
            ).scalar_one()
            for _ in range(2)
        ]
    populate(session_factory, org_a, users[0])
    populate(session_factory, org_b, users[1])
    yield org_a, org_b, users[0], users[1]
    with owner_engine.begin() as conn:
        for uid in users:
            conn.execute(text("DELETE FROM users WHERE id = :i"), {"i": uid})


def test_app_role_cannot_bypass_row_security(owner_engine: Engine, app_engine: Engine) -> None:
    with app_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
                "FROM pg_roles WHERE rolname = current_user"
            )
        ).one()
        assert not any(row)
        owned = conn.execute(
            text(
                "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner = current_user"
            )
        ).scalar_one()
        assert owned == 0


def test_every_tenant_table_has_forced_rls_and_a_policy(owner_engine: Engine) -> None:
    with owner_engine.connect() as conn:
        tenant_tables = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND column_name='org_id'"
                )
            )
        } | {"organizations"}
        all_tables = {
            r[0]
            for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
        } - {"alembic_version"}
        flags = {
            r[0]: (r[1], r[2])
            for r in conn.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relkind='r' AND relnamespace='public'::regnamespace"
                )
            )
        }
        policies = {r[0] for r in conn.execute(text("SELECT DISTINCT tablename FROM pg_policies"))}
    assert tenant_tables | NON_TENANT_TABLES == all_tables
    for table in tenant_tables:
        assert flags[table] == (True, True), table
        assert table in policies, table
    for table in NON_TENANT_TABLES:
        assert flags[table] == (False, False), table


def test_each_org_sees_only_its_own_rows_in_every_tenant_table(
    populated: tuple[OrgFixture, OrgFixture, uuid.UUID, uuid.UUID],
    owner_engine: Engine,
    session_factory: sessionmaker[TenantSession],
) -> None:
    org_a, org_b, user_a, _ = populated
    with owner_engine.connect() as conn:
        tables = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND column_name='org_id' AND table_name <> 'memberships'"
                )
            )
        ]
        expected = {
            (t, o.id): conn.execute(
                text(f'SELECT count(*) FROM "{t}" WHERE org_id = :o'), {"o": o.id}
            ).scalar_one()
            for t in tables
            for o in (org_a, org_b)
        }
    assert any(count > 0 for count in expected.values())
    for org in (org_a, org_b):
        with tenant_session(session_factory, TenantContext(org.id)) as s:
            for table in tables:
                total = s.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
                assert total == expected[(table, org.id)], table
                foreign = s.execute(
                    text(f'SELECT count(*) FROM "{table}" WHERE org_id IS DISTINCT FROM :o'),
                    {"o": org.id},
                ).scalar_one()
                # audit_log rows without an org are not readable either
                assert foreign == 0, table


def test_no_tenant_context_returns_no_rows(
    populated: tuple[OrgFixture, OrgFixture, uuid.UUID, uuid.UUID],
    session_factory: sessionmaker[TenantSession],
) -> None:
    with session_factory() as s:
        assert s.scalars(select(System)).all() == []
        assert s.scalars(select(DataElement)).all() == []
        assert s.scalars(select(Organization)).all() == []


def test_org_a_cannot_read_org_b_by_id(
    populated: tuple[OrgFixture, OrgFixture, uuid.UUID, uuid.UUID],
    session_factory: sessionmaker[TenantSession],
) -> None:
    org_a, org_b, user_a, user_b = populated
    with tenant_session(session_factory, TenantContext(org_b.id, user_b)) as s:
        b_system = s.scalars(select(System)).one()
        b_org = s.get(Organization, org_b.id)
        assert b_org is not None
    with tenant_session(session_factory, TenantContext(org_a.id, user_a)) as s:
        assert s.get(System, b_system.id) is None
        assert s.get(Organization, org_b.id) is None
        assert SystemRepository(s).get_by_slug("shop") is not None  # its own, not B's
        assert SystemRepository(s).count() == 1


def test_org_a_cannot_update_or_delete_org_b_rows(
    populated: tuple[OrgFixture, OrgFixture, uuid.UUID, uuid.UUID],
    session_factory: sessionmaker[TenantSession],
) -> None:
    org_a, org_b, user_a, user_b = populated
    with tenant_session(session_factory, TenantContext(org_b.id, user_b)) as s:
        b_system_id = s.scalars(select(System)).one().id
    with tenant_session(session_factory, TenantContext(org_a.id, user_a)) as s:
        updated = s.execute(update(System).where(System.id == b_system_id).values(name="hijacked"))
        deleted = s.execute(delete(System).where(System.id == b_system_id))
        assert updated.rowcount == 0  # type: ignore[attr-defined]
        assert deleted.rowcount == 0  # type: ignore[attr-defined]
    with tenant_session(session_factory, TenantContext(org_b.id, user_b)) as s:
        assert s.get(System, b_system_id) is not None
        assert s.get(System, b_system_id).name != "hijacked"  # type: ignore[union-attr]


def test_cannot_insert_rows_for_another_org(
    populated: tuple[OrgFixture, OrgFixture, uuid.UUID, uuid.UUID],
    session_factory: sessionmaker[TenantSession],
) -> None:
    org_a, org_b, user_a, _ = populated
    with pytest.raises(DBAPIError, match="row-level security"):  # noqa: PT012
        with tenant_session(session_factory, TenantContext(org_a.id, user_a)) as s:
            s.add(System(org_id=org_b.id, name="planted", slug="planted"))
            s.flush()


def test_cannot_move_a_row_into_another_org(
    populated: tuple[OrgFixture, OrgFixture, uuid.UUID, uuid.UUID],
    session_factory: sessionmaker[TenantSession],
) -> None:
    org_a, org_b, user_a, _ = populated
    with pytest.raises(DBAPIError, match="row-level security"):  # noqa: PT012
        with tenant_session(session_factory, TenantContext(org_a.id, user_a)) as s:
            s.execute(update(System).values(org_id=org_b.id))


def test_insert_without_tenant_fails(
    session_factory: sessionmaker[TenantSession],
) -> None:
    with pytest.raises(DBAPIError):  # noqa: PT012
        with session_factory() as s:
            s.add(System(name="orphan", slug="orphan"))
            s.flush()


def test_org_id_defaults_from_the_tenant_setting(
    populated: tuple[OrgFixture, OrgFixture, uuid.UUID, uuid.UUID],
    session_factory: sessionmaker[TenantSession],
) -> None:
    org_a, _, user_a, _ = populated
    with tenant_session(session_factory, TenantContext(org_a.id, user_a)) as s:
        system = SystemRepository(s).add(name="Defaulted", slug="defaulted")
        s.refresh(system)
        assert system.org_id == org_a.id


def test_tenant_survives_a_mid_unit_commit(
    populated: tuple[OrgFixture, OrgFixture, uuid.UUID, uuid.UUID],
    session_factory: sessionmaker[TenantSession],
) -> None:
    org_a, _, user_a, _ = populated
    with tenant_session(session_factory, TenantContext(org_a.id, user_a)) as s:
        SystemRepository(s).add(name="First", slug="first")
        s.commit()
        names = {x.name for x in s.scalars(select(System))}
        assert "First" in names
        assert all(x.org_id == org_a.id for x in s.scalars(select(System)))


def test_settings_do_not_leak_between_pooled_connections(
    populated: tuple[OrgFixture, OrgFixture, uuid.UUID, uuid.UUID],
    session_factory: sessionmaker[TenantSession],
    app_engine: Engine,
) -> None:
    org_a, _, user_a, _ = populated
    with tenant_session(session_factory, TenantContext(org_a.id, user_a)) as s:
        assert s.scalars(select(System)).first() is not None
    # The same pooled connection, reused without a tenant, must see nothing.
    for _ in range(5):
        with app_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM systems")).scalar_one() == 0
            assert conn.execute(
                text("SELECT current_setting('app.org_id', true)")
            ).scalar_one() in (
                "",
                None,
            )


def test_vector_search_is_tenant_scoped(
    populated: tuple[OrgFixture, OrgFixture, uuid.UUID, uuid.UUID],
    session_factory: sessionmaker[TenantSession],
) -> None:
    org_a, _, user_a, _ = populated
    with tenant_session(session_factory, TenantContext(org_a.id, user_a)) as s:
        rows = s.scalars(
            select(DataElement).order_by(DataElement.embedding.cosine_distance(VECTOR)).limit(10)
        ).all()
        assert len(rows) == 1 and rows[0].org_id == org_a.id
        hits = s.execute(
            text(
                "SELECT count(*) FROM document_chunks "
                "WHERE tsv @@ plainto_tsquery('english', 'order records')"
            )
        ).scalar_one()
        assert hits == 1


def test_memberships_visible_across_orgs_only_for_own_user(
    populated: tuple[OrgFixture, OrgFixture, uuid.UUID, uuid.UUID],
    session_factory: sessionmaker[TenantSession],
    owner_engine: Engine,
) -> None:
    org_a, org_b, user_a, user_b = populated
    with owner_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO memberships (org_id, user_id, role) VALUES (:o, :u, 'viewer')"),
            {"o": org_b.id, "u": user_a},
        )
    # user_a, acting for org A, can list their own memberships in both orgs
    with tenant_session(session_factory, TenantContext(org_a.id, user_a)) as s:
        mine = s.scalars(select(Membership).where(Membership.user_id == user_a)).all()
        assert {m.org_id for m in mine} == {org_a.id, org_b.id}
        # but cannot see user_b's membership in org B
        assert s.scalars(select(Membership).where(Membership.user_id == user_b)).all() == []
        # and cannot write a membership into org B
        with pytest.raises(DBAPIError, match="row-level security"):
            s.add(Membership(org_id=org_b.id, user_id=user_a, role=Role.ADMIN))
            s.flush()
        s.rollback()


def test_audit_log_is_append_only(
    populated: tuple[OrgFixture, OrgFixture, uuid.UUID, uuid.UUID],
    session_factory: sessionmaker[TenantSession],
) -> None:
    org_a, _, user_a, _ = populated
    with tenant_session(session_factory, TenantContext(org_a.id, user_a)) as s:
        AuditLogRepository(s).record("login", actor_user_id=user_a)
        assert s.scalars(select(AuditLog).where(AuditLog.action == "login")).one()
    with pytest.raises(ProgrammingError, match="permission denied"):  # noqa: PT012
        with tenant_session(session_factory, TenantContext(org_a.id, user_a)) as s:
            s.execute(update(AuditLog).values(action="tampered"))
    with pytest.raises(ProgrammingError, match="permission denied"):  # noqa: PT012
        with tenant_session(session_factory, TenantContext(org_a.id, user_a)) as s:
            s.execute(delete(AuditLog))


def test_app_role_cannot_create_or_delete_organizations(
    populated: tuple[OrgFixture, OrgFixture, uuid.UUID, uuid.UUID],
    session_factory: sessionmaker[TenantSession],
) -> None:
    org_a, _, user_a, _ = populated
    with pytest.raises(ProgrammingError, match="permission denied"):  # noqa: PT012
        with tenant_session(session_factory, TenantContext(org_a.id, user_a)) as s:
            s.add(Organization(name="Rogue", slug=f"rogue-{uuid.uuid4().hex[:6]}"))
            s.flush()
    with pytest.raises(ProgrammingError, match="permission denied"):  # noqa: PT012
        with tenant_session(session_factory, TenantContext(org_a.id, user_a)) as s:
            s.execute(delete(Organization))


def test_app_role_cannot_write_shared_reference_tables(
    session_factory: sessionmaker[TenantSession],
) -> None:
    for statement in (
        "INSERT INTO plans (code, name, monthly_fee_cents, included_systems, included_requests) "
        "VALUES ('x', 'x', 1, 1, 1)",
        "INSERT INTO regulation_chunks (text) VALUES ('x')",
        "INSERT INTO daily_metrics (metric_date) VALUES (current_date)",
        "INSERT INTO taxonomy_entries (category_id, kind, text, source_version, embedding) "
        "VALUES ('x', 'label', 'x', 'v', array_fill(0.1::float4, ARRAY[384])::vector)",
    ):
        with pytest.raises(ProgrammingError, match="permission denied"):  # noqa: PT012
            with session_factory() as s:
                s.execute(text(statement))


def test_user_repository_lookup_is_case_insensitive(
    populated: tuple[OrgFixture, OrgFixture, uuid.UUID, uuid.UUID],
    session_factory: sessionmaker[TenantSession],
) -> None:
    org_a, _, user_a, _ = populated
    with tenant_session(session_factory, TenantContext(org_a.id, user_a)) as s:
        email = s.get(User, user_a).email  # type: ignore[union-attr]
        assert UserRepository(s).get_by_email(email.upper()) is not None


def test_set_tenant_helper_binds_an_existing_session(
    populated: tuple[OrgFixture, OrgFixture, uuid.UUID, uuid.UUID],
    session_factory: sessionmaker[TenantSession],
) -> None:
    org_a, org_b, user_a, user_b = populated
    with session_factory() as s:
        set_tenant(s, TenantContext(org_b.id, user_b))
        assert s.scalars(select(System)).one().org_id == org_b.id
        s.rollback()
        set_tenant(s, TenantContext(org_a.id, user_a))
        assert s.scalars(select(System)).one().org_id == org_a.id
