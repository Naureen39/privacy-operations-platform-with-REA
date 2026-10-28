"""Write the API's OpenAPI document to a file, for generating the frontend's types.

cd backend
uv run python ../scripts/export_openapi.py ../frontend/src/api/openapi.json
"""

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from pydantic import SecretStr  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    settings = Settings(
        jwt_secret=SecretStr("x" * 40),
        evidence_encryption_key=SecretStr(base64.b64encode(b"k" * 32).decode()),
    )
    spec = create_app(settings, sessionmaker()).openapi()
    target.write_text(json.dumps(spec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(spec['paths'])} paths written to {target}")


if __name__ == "__main__":
    main()
