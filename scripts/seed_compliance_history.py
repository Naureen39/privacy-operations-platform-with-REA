"""Generate a simulated year of compliance activity for the demonstration organisation and the
daily compliance snapshots derived from it.

    cd backend
    uv run python ../scripts/seed_compliance_history.py --reset

The organisation is found by slug (default: northbridge, created by seed_demo_users.py).
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import (
    TenantContext,
    make_engine,
    make_session_factory,
    tenant_session,
)  # noqa: E402
from app.seeding import compliance_history  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--slug", default="northbridge")
    parser.add_argument("--reset", action="store_true", help="remove earlier simulated rows first")
    args = parser.parse_args()
    settings = get_settings()
    owner = create_engine(settings.migration_database_url)
    with owner.connect() as conn:
        org_id = conn.execute(
            text("SELECT id FROM organizations WHERE slug = :s"), {"s": args.slug}
        ).scalar_one_or_none()
    if org_id is None:
        raise SystemExit(f"No organisation with slug {args.slug!r}; run seed_demo_users.py first")
    factory = make_session_factory(make_engine())
    with tenant_session(factory, TenantContext(org_id=org_id)) as db:
        if args.reset:
            compliance_history.reset(db)
        summary = compliance_history.seed_compliance_history(
            db, seed=args.seed, as_of=settings.reference_date or date.today(), months=args.months
        )
    print(
        f"{summary.activities} records, {summary.findings} findings, {summary.assessments} "
        f"assessments, {summary.requests} requests, {summary.snapshots} daily snapshots"
    )
    print("All of it is simulated demonstration data.")


if __name__ == "__main__":
    main()
