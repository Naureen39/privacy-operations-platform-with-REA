"""Bring up the whole application for the browser tests: a database, the seeded demonstration data and
the API, all on this machine. Nothing here is for production.

    python scripts/e2e_stack.py up      # database, migrations, seeds (a few minutes the first time)
    python scripts/e2e_stack.py api     # start the API in the background (pid in .e2e/api.pid)
    python scripts/e2e_stack.py down    # stop the API and the database container

Needs Docker, uv, and the embedding model already downloaded (scripts/download_embedding_model.py).
Secrets are generated once and kept in .e2e/env.json (git ignored). Background jobs run inside the API
process (CELERY_EAGER) so no broker is needed, and evidence is read by the built in parsers
(REA_ENABLED=false) so the run does not need Node.
"""

import base64
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
STATE = ROOT / ".e2e"
DB_PORT = os.environ.get("E2E_DB_PORT", "5545")
API_PORT = os.environ.get("E2E_API_PORT", "8000")
PASSWORD = "E2e-Demo-Pass-12345"  # noqa: S105  (a local demonstration password)


def load_state() -> dict[str, str]:
    STATE.mkdir(exist_ok=True)
    path = STATE / "env.json"
    if path.exists():
        return dict(json.loads(path.read_text(encoding="utf-8")))
    state = {
        "JWT_SECRET": secrets.token_urlsafe(48),
        "EVIDENCE_ENCRYPTION_KEY": base64.b64encode(os.urandom(32)).decode(),
        "SUBJECT_HASH_KEY": base64.b64encode(os.urandom(32)).decode(),
        "APP_DB_PASSWORD": secrets.token_urlsafe(18),
    }
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return state


def environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    s = load_state()
    env = {
        **os.environ,
        "POSTGRES_USER": "processledger",
        "POSTGRES_PASSWORD": "processledger_dev",
        "POSTGRES_DB": "processledger",
        "DB_HOST_PORT": DB_PORT,
        "APP_DB_PASSWORD": s["APP_DB_PASSWORD"],
        "DATABASE_URL": f"postgresql+psycopg://processledger_app:{s['APP_DB_PASSWORD']}@127.0.0.1:{DB_PORT}/processledger",
        "MIGRATION_DATABASE_URL": f"postgresql+psycopg://processledger:processledger_dev@127.0.0.1:{DB_PORT}/processledger",
        "JWT_SECRET": s["JWT_SECRET"],
        "EVIDENCE_ENCRYPTION_KEY": s["EVIDENCE_ENCRYPTION_KEY"],
        "SUBJECT_HASH_KEY": s["SUBJECT_HASH_KEY"],
        "COOKIE_SECURE": "false",
        "CELERY_EAGER": "true",
        "REA_ENABLED": "false",
        "EMBEDDING_LOCAL_FILES_ONLY": "true",
        "UPLOAD_DIR": str(STATE / "evidence"),
        "LOGIN_RATE_LIMIT": "1000/minute",
        "DEFAULT_RATE_LIMIT": "100000/minute",
        "LEAD_RATE_LIMIT": "1000/minute",
        "DEMO_PASSWORD": PASSWORD,
        "OBSERVATION_ALLOWED_HOSTS": '["127.0.0.1"]',
        "PYTHONIOENCODING": "utf-8",
    }
    env.update(extra or {})
    return env


def run(*cmd: str, cwd: Path = BACKEND, extra: dict[str, str] | None = None) -> str:
    print("+", " ".join(cmd), flush=True)
    done = subprocess.run(  # noqa: S603
        list(cmd),
        cwd=cwd,
        env=environment(extra),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return done.stdout


def wait_for_db() -> None:
    for _ in range(60):
        probe = subprocess.run(  # noqa: S603
            [
                "docker",
                "exec",
                "processledger-db",
                "pg_isready",
                "-U",
                "processledger",
            ],  # noqa: S607
            capture_output=True,
        )
        if probe.returncode == 0:
            return
        time.sleep(2)
    raise SystemExit("The database did not become ready")


def host_org_id() -> str:
    out = run(
        "uv", "run", "python", "-c",
        "from sqlalchemy import create_engine, text; import os; e = create_engine(os.environ['MIGRATION_DATABASE_URL']); "
        "print(e.connect().execute(text(\"SELECT id FROM organizations WHERE slug = 'northbridge'\")).scalar_one())",
    )  # fmt: skip
    return out.strip().splitlines()[-1]


def up() -> None:
    run("docker", "compose", "up", "-d", "db", cwd=ROOT)
    wait_for_db()
    run("uv", "run", "alembic", "upgrade", "head")
    # The role may already exist from an earlier run with another password; make them agree.
    run(
        "uv", "run", "python", "-c",
        "import os; from sqlalchemy import create_engine, text; "
        "e = create_engine(os.environ['MIGRATION_DATABASE_URL'], isolation_level='AUTOCOMMIT'); "
        "e.connect().execute(text(\"ALTER ROLE processledger_app WITH PASSWORD '\" + os.environ['APP_DB_PASSWORD'] + \"'\"))",
    )  # fmt: skip
    run("uv", "run", "python", "../scripts/seed_demo_users.py")
    run("uv", "run", "python", "../scripts/load_taxonomy.py")
    run("uv", "run", "python", "../scripts/ingest_regulation.py")
    run("uv", "run", "python", "../scripts/seed_compliance_history.py", "--reset")
    run(
        "uv",
        "run",
        "python",
        "../scripts/seed_billing_history.py",
        "--reset",
        "--organisations",
        "60",
    )
    run("uv", "run", "python", "-c", "print('ok')")
    print(
        "Ready. Accounts: admin@, analyst@, owner@, auditor@northbridge.example, password", PASSWORD
    )


def api() -> None:
    org = host_org_id()
    log = (STATE / "api.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(  # noqa: S603
        [
            "uv",
            "run",
            "uvicorn",
            "app.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            API_PORT,
        ],  # noqa: S607
        cwd=BACKEND,
        env=environment({"LEADS_ORG_ID": org}),
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    (STATE / "api.pid").write_text(str(proc.pid), encoding="utf-8")
    for _ in range(90):
        try:
            import urllib.request

            with urllib.request.urlopen(
                f"http://127.0.0.1:{API_PORT}/ready", timeout=2
            ) as r:  # noqa: S310
                if r.status == 200:
                    print(f"API ready on port {API_PORT} (pid {proc.pid})")
                    return
        except Exception:  # noqa: BLE001
            time.sleep(2)
    raise SystemExit("The API did not start; see .e2e/api.log")


def down() -> None:
    pid_file = STATE / "api.pid"
    if pid_file.exists():
        pid = int(pid_file.read_text(encoding="utf-8"))
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        pid_file.unlink()
    run("docker", "compose", "stop", "db", cwd=ROOT)


if __name__ == "__main__":
    actions = {"up": up, "api": api, "down": down}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        raise SystemExit(__doc__)
    actions[sys.argv[1]]()
