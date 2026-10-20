"""Load the synthetic people into the estate systems' live databases.

    uv run python datasets/scripts/seed_estate.py

For every system, each person who belongs to it (see the `in_<system>` flags in
synthetic_people.csv) gets rows in the system's tables, written through the system's own
store. The live databases are build artefacts under datasets/_build/ (git ignored);
export_snapshots.py later writes the small read-only snapshots that are committed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_synthetic_people import load_people  # noqa: E402
from common import DATASETS_DIR, rng_for  # noqa: E402
from estate_apps import Store  # noqa: E402
from estate_spec import SYSTEMS  # noqa: E402
from generators import resolve  # noqa: E402


def seed_system(spec: dict, people: list[dict[str, str]], build_dir: Path) -> Store:
    store = Store(build_dir / "live" / f"{spec['id']}.sqlite", spec)
    for person in people:
        if person[spec["population"]] != "1":
            continue
        for table in spec["tables"]:
            low, high = table["per_person"]
            rng = rng_for("seed", spec["id"], table["name"], person["person_id"])
            for _ in range(rng.randint(low, high)):
                values = {
                    c["n"]: resolve(c["src"], person, rng)
                    for c in table["columns"]
                    if c["src"] != "auto"
                }
                store.insert(table["name"], values, person["person_id"])
    store.commit()
    return store


def seed_all(people: list[dict[str, str]], build_dir: Path) -> dict[str, Store]:
    return {spec["id"]: seed_system(spec, people, build_dir) for spec in SYSTEMS}


def main() -> None:
    build_dir = DATASETS_DIR / "_build"
    stores = seed_all(load_people(), build_dir)
    for system_id, store in stores.items():
        counts = {
            name: store.db.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
            for name in store.tables
        }
        print(f"{system_id:<15} {counts}")
        store.close()


if __name__ == "__main__":
    main()
