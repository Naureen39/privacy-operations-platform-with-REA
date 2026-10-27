"""Generate two years of simulated billing history (fictional organisations, subscriptions, usage,
invoices and the daily platform metrics). Every row is marked simulated.

    cd backend
    uv run python ../scripts/seed_billing_history.py            # seed 42, 120 organisations
    uv run python ../scripts/seed_billing_history.py --reset    # replace an earlier run

Needs the database owner connection (MIGRATION_DATABASE_URL) because it spans organisations.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import create_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import make_engine, make_session_factory  # noqa: E402
from app.seeding.billing_history import seed_billing_history  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--organisations", type=int, default=120)
    parser.add_argument("--months", type=int, default=24)
    parser.add_argument("--reset", action="store_true", help="remove earlier simulated data first")
    args = parser.parse_args()
    settings = get_settings()
    owner = create_engine(settings.migration_database_url)
    factory = make_session_factory(make_engine())
    summary = seed_billing_history(
        owner,
        factory,
        seed=args.seed,
        organisations=args.organisations,
        months=args.months,
        as_of=settings.reference_date or date.today(),
        reset=args.reset,
    )
    print(
        f"{summary.organisations} organisations, {summary.subscriptions} subscriptions, "
        f"{summary.invoices} invoices, {summary.usage_events} usage events, "
        f"{summary.metric_rows} daily metric rows ({summary.first_day} to {summary.last_day})"
    )
    print("All of it is simulated: there are no real customers.")


if __name__ == "__main__":
    main()
