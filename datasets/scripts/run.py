"""Single entry point for the dataset build (what `make datasets` calls).

    uv run python datasets/scripts/run.py regulation [--force]
    uv run python datasets/scripts/run.py estate
    uv run python datasets/scripts/run.py verify
    uv run python datasets/scripts/run.py all [--force]

`regulation` downloads the GDPR text only when gdpr_articles.json is missing (or with --force).
`estate` is fully offline. `all` runs both and then refreshes the manifest.
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_estate import build, write_manifest  # noqa: E402
from common import DATASETS_DIR  # noqa: E402
from verify_manifest import verify  # noqa: E402

REGULATION_FILE = DATASETS_DIR / "regulation" / "gdpr_articles.json"


def regulation(force: bool) -> None:
    if REGULATION_FILE.exists() and not force:
        print(f"{REGULATION_FILE.name} exists; use --force to download again")
        return
    script = Path(__file__).with_name("fetch_regulation.py")
    subprocess.run([sys.executable, str(script)], check=True)  # noqa: S603


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["regulation", "estate", "verify", "all"])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.command in ("regulation", "all"):
        regulation(args.force)
    if args.command in ("estate", "all"):
        result = build(DATASETS_DIR, manifest=False)
        entries = write_manifest(DATASETS_DIR)
        print(
            f"built {result['systems']} systems, {result['people']} people, {entries} manifest entries"
        )
    if args.command == "verify":
        problems = verify()
        if problems:
            print("\n".join(problems))
            sys.exit(1)
        print("datasets match MANIFEST.sha256")


if __name__ == "__main__":
    main()
