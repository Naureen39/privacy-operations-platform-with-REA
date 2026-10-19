"""Provisioning of organizations and users.

Registration is disabled in the product. Accounts are created here, by the owner role
(seed scripts and administration tooling), never by the application role.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Engine, text

from app.core.security import hash_password
from app.db.enums import Role


@dataclass(frozen=True)
class ProvisionedUser:
    id: uuid.UUID
    email: str
    role: Role


def create_organization(engine: Engine, name: str, slug: str, **extra: str) -> uuid.UUID:
    with engine.begin() as conn:
        org_id: uuid.UUID = conn.execute(
            text(
                "INSERT INTO organizations (name, slug, industry, region) "
                "VALUES (:name, :slug, :industry, :region) "
                "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id"
            ),
            {
                "name": name,
                "slug": slug,
                "industry": extra.get("industry"),
                "region": extra.get("region"),
            },
        ).scalar_one()
    return org_id


def create_user(
    engine: Engine,
    org_id: uuid.UUID,
    email: str,
    full_name: str,
    password: str,
    role: Role,
    min_password_length: int = 12,
) -> ProvisionedUser:
    password_hash = hash_password(password, min_password_length)
    with engine.begin() as conn:
        user_id = conn.execute(
            text(
                "INSERT INTO users (email, full_name, password_hash) VALUES (:e, :n, :h) "
                "ON CONFLICT (lower(email)) DO UPDATE SET full_name = EXCLUDED.full_name, "
                "password_hash = EXCLUDED.password_hash RETURNING id"
            ),
            {"e": email, "n": full_name, "h": password_hash},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO memberships (org_id, user_id, role) VALUES (:o, :u, :r) "
                "ON CONFLICT (org_id, user_id) DO UPDATE SET role = EXCLUDED.role"
            ),
            {"o": org_id, "u": user_id, "r": role.value},
        )
    return ProvisionedUser(user_id, email, role)


DEMO_USERS = (
    ("admin@northbridge.example", "Avery Admin", Role.ADMIN),
    ("analyst@northbridge.example", "Alex Analyst", Role.ANALYST),
    ("owner@northbridge.example", "Sam System Owner", Role.SYSTEM_OWNER),
    ("auditor@northbridge.example", "Val Viewer", Role.VIEWER),
)


def seed_demo_users(engine: Engine, password: str) -> dict[str, ProvisionedUser]:
    """Create the demo organization with one account per role. Local use only."""
    org_id = create_organization(
        engine, "Northbridge Group", "northbridge", industry="Retail", region="EU"
    )
    return {
        user.role.value: user
        for user in (
            create_user(engine, org_id, email, name, password, role)
            for email, name, role in DEMO_USERS
        )
    }
