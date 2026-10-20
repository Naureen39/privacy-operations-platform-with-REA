"""Shared helpers for the dataset build scripts: paths, deterministic JSON, checksums."""

import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any

DATASETS_DIR = Path(__file__).resolve().parent.parent
SEED = 42
# Fixed "today" for the demonstration estate, so generated content never depends on the clock.
REFERENCE_DATE = "2026-10-01"
BASE_TIME = "2026-09-28T09:00:00.000Z"  # start of the capture session in HAR files

LONG_DASHES = (chr(0x2014), chr(0x2013))

# SHA-256 hashes of lower case words that must not appear in generated or committed text
# (names of AI coding tools). Stored as hashes so that this file does not contain the words.
BANNED_WORD_HASHES = frozenset(
    {
        "c857d09db23e6822e3600bc06ad8d58f92ed62bc8efd81c753f77048662cb97d",
        "c70eca6b0f88f44d81a41311647e50fda1ac454ec04ffd442b0eb4743a993131",
        "3ea125d0bff386e6754b3782b300016fc79a9cf8f8669c0a5c3db64467ddb681",
        "60965168ce762e949600281ba6d01fee136e5b6e8257b1f216f9025ed324474c",
    }
)


def has_banned_word(text: str) -> bool:
    """True if any whole word of the text is one of the banned words (case insensitive)."""
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    return any(hashlib.sha256(w.encode()).hexdigest() in BANNED_WORD_HASHES for w in words)


def rng_for(*parts: object) -> random.Random:
    """A random generator derived from the global seed and any labels, stable across runs."""
    digest = hashlib.sha256("|".join([str(SEED), *map(str, parts)]).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text if text.endswith("\n") else text + "\n")


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strip_long_dashes(text: str) -> str:
    """Replace the long dash characters with a spaced hyphen (project text standard)."""
    for dash in LONG_DASHES:
        text = text.replace(dash, " - ")
    return " ".join(text.split()) if "  " in text else text
