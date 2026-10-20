"""Export a small read-only SQLite snapshot of each system's database.

A snapshot contains the schema (without any internal columns) and the rows of a sample of
the system's people. The sample always includes the people used in the access request
cases, so every case can be answered from the snapshots alone.
"""

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import rng_for  # noqa: E402
from estate_apps import Store  # noqa: E402

SNAPSHOT_PEOPLE = 120


def snapshot_pids(
    spec: dict[str, Any],
    population: list[str],
    must_include: set[str],
    size: int = SNAPSHOT_PEOPLE,
) -> set[str]:
    chosen = {pid for pid in must_include if pid in set(population)}
    remaining = sorted(set(population) - chosen)
    rng = rng_for("snapshot", spec["id"])
    rng.shuffle(remaining)
    chosen.update(remaining[: max(0, size - len(chosen))])
    return chosen


def export_system(
    spec: dict[str, Any], store: Store, population: list[str], must_include: set[str], out_dir: Path
) -> dict[str, int]:
    pids = snapshot_pids(spec, population, must_include)
    return store.export(out_dir / "evidence" / "snapshot.sqlite", pids)
