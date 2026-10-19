"""Create the demo organization and one account per role. For local use only.

    cd backend
    uv run python ../scripts/seed_demo_users.py

Registration is disabled in the application, so this is how accounts come into being.
Set DEMO_PASSWORD (at least 12 characters) to choose the shared demo password, and change
every credential before any use outside a local machine.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import create_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.services.provisioning import seed_demo_users  # noqa: E402

DEFAULT_PASSWORD = "ChangeMe-Local-Only-1"  # noqa: S105  (documented local demo password)


def main() -> None:
    password = os.environ.get("DEMO_PASSWORD") or DEFAULT_PASSWORD
    engine = create_engine(get_settings().migration_database_url)
    users = seed_demo_users(engine, password)
    for role, user in users.items():
        print(f"{role:<13} {user.email}")
    if password == DEFAULT_PASSWORD:
        print("Default demo password in use. Local use only.")


if __name__ == "__main__":
    main()
