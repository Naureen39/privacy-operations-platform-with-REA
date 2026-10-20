"""Check that the files under datasets/ still match MANIFEST.sha256.

    uv run python datasets/scripts/verify_manifest.py

Exit status 1 lists changed, missing and unexpected files. The manifest is rewritten by
build_estate.py; the regulation file is added to it by the same step.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_estate import MANIFEST_DIRS  # noqa: E402
from common import DATASETS_DIR, sha256_file  # noqa: E402


def read_manifest(base: Path) -> dict[str, str]:
    entries = {}
    for line in (base / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        entries[name] = digest
    return entries


def verify(base: Path = DATASETS_DIR) -> list[str]:
    expected = read_manifest(base)
    actual = {
        path.relative_to(base).as_posix(): sha256_file(path)
        for name in MANIFEST_DIRS
        for path in sorted((base / name).rglob("*"))
        if path.is_file()
    }
    problems = [
        f"changed: {name}"
        for name in sorted(expected.keys() & actual.keys())
        if expected[name] != actual[name]
    ]
    problems += [f"missing: {name}" for name in sorted(expected.keys() - actual.keys())]
    problems += [f"unexpected: {name}" for name in sorted(actual.keys() - expected.keys())]
    return problems


def main() -> None:
    problems = verify()
    if problems:
        print("\n".join(problems))
        sys.exit(1)
    print("datasets match MANIFEST.sha256")


if __name__ == "__main__":
    main()
