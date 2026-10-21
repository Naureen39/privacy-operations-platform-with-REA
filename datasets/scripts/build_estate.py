"""Rebuild the reference estate from scratch (offline, deterministic).

    uv run python datasets/scripts/build_estate.py [--out DIR] [--no-manifest]

Steps: synthetic people, seeded live databases, simulated captures (HAR, website snapshot,
bundle), read-only snapshots, privacy notices, questionnaires, ground truth, processor
agreements, access request cases, reference outputs and a checksum manifest.
"""

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_documents import (  # noqa: E402
    ground_truth,
    reference_outputs,
    write_agreements,
    write_system_documents,
)
from build_synthetic_people import build_people, load_people, write_csv  # noqa: E402
from capture_evidence import CAPTURE_PEOPLE, capture_system  # noqa: E402
from common import DATASETS_DIR, REFERENCE_DATE, rng_for, sha256_file, write_json  # noqa: E402
from estate_spec import SYSTEMS  # noqa: E402
from export_snapshots import export_system  # noqa: E402
from js_bundles import bundle_filename  # noqa: E402
from request_cases import build_cases, case_person_ids  # noqa: E402
from seed_estate import seed_all  # noqa: E402

MANIFEST_DIRS = ["estate", "people", "policies", "expected", "regulation", "evaluation"]
GENERATED_DIRS = ["estate", "expected"]


def write_manifest(base: Path) -> int:
    lines = []
    for name in MANIFEST_DIRS:
        for path in sorted((base / name).rglob("*")):
            if path.is_file():
                lines.append(f"{sha256_file(path)}  {path.relative_to(base).as_posix()}")
    (base / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return len(lines)


def evidence_files(spec: dict[str, Any]) -> dict[str, str]:
    return {
        "har": f"estate/{spec['id']}/evidence/capture.har",
        "website": f"estate/{spec['id']}/evidence/website_snapshot.html",
        "javascript_bundle": f"estate/{spec['id']}/evidence/{bundle_filename(spec)}",
        "sqlite_snapshot": f"estate/{spec['id']}/evidence/snapshot.sqlite",
        "privacy_policy": f"estate/{spec['id']}/policy.md",
        "questionnaire": f"estate/{spec['id']}/questionnaire.json",
        "ground_truth": f"estate/{spec['id']}/ground_truth.json",
    }


def build(out: Path = DATASETS_DIR, manifest: bool = True) -> dict[str, Any]:
    out = out.resolve()
    for name in GENERATED_DIRS:
        shutil.rmtree(out / name, ignore_errors=True)
    work = out / "_build"
    shutil.rmtree(work, ignore_errors=True)

    write_csv(build_people(), out / "people" / "synthetic_people.csv")
    people = load_people(out / "people" / "synthetic_people.csv")
    people_by_id = {p["person_id"]: p for p in people}
    case_pids = case_person_ids(people)

    stores = seed_all(people, work)
    truths: dict[str, dict[str, Any]] = {}
    for spec in SYSTEMS:
        system_dir = out / "estate" / spec["id"]
        population = [p["person_id"] for p in people if p[spec["population"]] == "1"]
        picker = rng_for("capture-people", spec["id"])
        capture_pids = sorted(picker.sample(population, CAPTURE_PEOPLE))
        info = capture_system(spec, stores[spec["id"]], people_by_id, capture_pids, system_dir)
        export_system(
            spec, stores[spec["id"]], population, case_pids | set(capture_pids), system_dir
        )
        evidence = system_dir / "evidence"
        artifacts = {
            "har": (evidence / "capture.har").read_text(encoding="utf-8"),
            "html": (evidence / "website_snapshot.html").read_text(encoding="utf-8"),
            "js": (evidence / bundle_filename(spec)).read_text(encoding="utf-8"),
        }
        truths[spec["id"]] = ground_truth(spec, {tuple(x) for x in info["sent_fields"]}, artifacts)
        write_system_documents(spec, system_dir, truths[spec["id"]])
        stores[spec["id"]].close()
    shutil.rmtree(work, ignore_errors=True)

    write_agreements(out)
    write_json(out / "people" / "request_cases.json", build_cases(people, SYSTEMS, out / "estate"))
    for name, content in reference_outputs(truths).items():
        write_json(out / "expected" / name, content)
    write_json(
        out / "estate" / "estate.json",
        {
            "company": {
                "name": "Northbridge Group",
                "description": "Fictional mid-size retailer with a small health clinic arm.",
                "privacy_officer_contact": "privacy@northbridge.example",
            },
            "reference_date": REFERENCE_DATE,
            "people": len(people),
            "systems": [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "host": s["host"],
                    "owner": s["owner"],
                    "stack": s["stack"],
                    "modeled_open_source_product": s["modeled"],
                    "description": s["description"],
                    "files": evidence_files(s),
                }
                for s in SYSTEMS
            ],
        },
    )
    count = write_manifest(out) if manifest else 0
    return {"systems": len(SYSTEMS), "people": len(people), "manifest_files": count}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out", type=Path, default=DATASETS_DIR, help="output directory (default: datasets/)"
    )
    parser.add_argument("--no-manifest", action="store_true")
    args = parser.parse_args()
    result = build(args.out, manifest=not args.no_manifest)
    print(
        f"built {result['systems']} systems, {result['people']} people, {result['manifest_files']} manifest entries"
    )


if __name__ == "__main__":
    main()
