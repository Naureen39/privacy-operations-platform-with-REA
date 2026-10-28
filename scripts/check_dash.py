"""Fail if a file contains the long dash characters (U+2013 or U+2014), per the team standard.

python scripts/check_dash.py [files...]      # no arguments: every tracked text file
"""

import subprocess
import sys
from pathlib import Path

DASHES = chr(0x2013) + chr(0x2014)
SKIP_SUFFIXES = {
    ".png",
    ".webp",
    ".woff",
    ".woff2",
    ".ico",
    ".sqlite",
    ".pdf",
    ".xlsx",
    ".gz",
    ".har",
}
SKIP_NAMES = {"package-lock.json", "uv.lock", "schema.d.ts", "openapi.json", "gdpr_articles.json"}
ROOT = Path(__file__).resolve().parent.parent


def tracked() -> list[Path]:
    out = subprocess.run(  # noqa: S603
        ["git", "ls-files", "-co", "--exclude-standard"],  # noqa: S607
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.splitlines()  # fmt: skip
    return [ROOT / p for p in out]


def main() -> int:
    files = [Path(a) for a in sys.argv[1:]] or tracked()
    bad = []
    for path in files:
        if path.suffix.lower() in SKIP_SUFFIXES or path.name in SKIP_NAMES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(ch in text for ch in DASHES):
            bad.append(str(path))
    if bad:
        print("Long dash characters found in:", *bad, sep="\n  ")
        return 1
    print(f"No long dash characters in {len(files)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
