"""Choose the people for the 10 access request cases and compute the expected search results.

People are chosen by which systems they belong to, using only the people file. The expected
locations are then computed from the committed snapshots: for each system, each table and each
identifier column (e-mail), the number of rows that match the person's address. That keeps
the expectation tied to what the platform will actually be able to search.
"""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

FLAGS = [
    "in_web_shop", "in_web_analytics", "in_helpdesk", "in_crm",
    "in_clinic_portal", "in_newsletter", "in_staff_desktop", "in_hr_onboarding",
]  # fmt: skip


def _on(p: dict[str, str]) -> set[str]:
    return {f for f in FLAGS if p[f] == "1"}


CASE_DEFINITIONS: list[tuple[str, str, Callable[[dict[str, str]], bool]]] = [
    ("RC01", "Person present in the most systems", lambda p: False),  # handled specially below
    ("RC02", "Customer who also subscribed to the newsletter",
     lambda p: _on(p) == {"in_web_shop", "in_web_analytics", "in_newsletter"}),
    ("RC03", "Patient who is in no other system", lambda p: _on(p) == {"in_clinic_portal"}),
    ("RC04", "Patient who is also a shop customer",
     lambda p: {"in_clinic_portal", "in_web_shop"} <= _on(p) and p["in_hr_onboarding"] == "0"),
    ("RC05", "Employee who is not a customer",
     lambda p: p["in_hr_onboarding"] == "1" and p["in_web_shop"] == "0"),
    ("RC06", "Employee who is also a shop customer",
     lambda p: p["in_hr_onboarding"] == "1" and p["in_web_shop"] == "1"),
    ("RC07", "Support contact who is also a sales lead",
     lambda p: {"in_helpdesk", "in_crm"} <= _on(p) and p["in_clinic_portal"] == "0"),
    ("RC08", "Newsletter subscriber who is not a customer",
     lambda p: _on(p) <= {"in_newsletter", "in_web_analytics"} and p["in_newsletter"] == "1"),
    ("RC09", "Website visitor known only by a pseudonymous identifier",
     lambda p: _on(p) == {"in_web_analytics"}),
    ("RC10", "Person who appears in no system", lambda p: not _on(p)),
]  # fmt: skip


def select_case_people(people: list[dict[str, str]]) -> list[tuple[str, str, dict[str, str]]]:
    chosen: list[tuple[str, str, dict[str, str]]] = []
    used: set[str] = set()
    for case_id, description, predicate in CASE_DEFINITIONS:
        if case_id == "RC01":
            # Most customer-facing systems; employees are excluded so the case stays one scenario.
            customer_flags = {"in_staff_desktop", "in_hr_onboarding"}
            person = sorted(people, key=lambda p: (-len(_on(p) - customer_flags), p["person_id"]))[
                0
            ]
        else:
            matches = [p for p in people if p["person_id"] not in used and predicate(p)]
            if not matches:
                raise RuntimeError(f"no person matches case {case_id}: {description}")
            person = matches[0]
        used.add(person["person_id"])
        chosen.append((case_id, description, person))
    return chosen


def expected_locations(
    person: dict[str, str], systems: list[dict[str, Any]], estate_dir: Path
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for spec in systems:
        db = sqlite3.connect(
            f"file:{(estate_dir / spec['id'] / 'evidence' / 'snapshot.sqlite').as_posix()}?mode=ro",
            uri=True,
        )
        try:
            for table in spec["tables"]:
                for column in table["columns"]:
                    if column.get("id_for") != "email":
                        continue
                    count = db.execute(
                        f'SELECT count(*) FROM "{table["name"]}" WHERE "{column["n"]}" = ?',
                        [person["email"]],
                    ).fetchone()[0]
                    if count:
                        found.append(
                            {
                                "system": spec["id"],
                                "table": table["name"],
                                "column": column["n"],
                                "rows": count,
                            }
                        )
        finally:
            db.close()
    return found


def build_cases(
    people: list[dict[str, str]], systems: list[dict[str, Any]], estate_dir: Path
) -> dict[str, Any]:
    cases = []
    for case_id, description, person in select_case_people(people):
        locations = expected_locations(person, systems, estate_dir)
        cases.append(
            {
                "id": case_id,
                "description": description,
                "subject": {"person_id": person["person_id"], "full_name": person["full_name"]},
                "identifier": {"type": "email", "value": person["email"]},
                "expected_systems": sorted({loc["system"] for loc in locations}),
                "expected_locations": locations,
            }
        )
    return {
        "note": "Expected locations are the tables whose e-mail identifier column matches the subject, "
        "counted in the committed snapshots. A case with no locations must return an empty result.",
        "cases": cases,
    }


def case_person_ids(people: list[dict[str, str]]) -> set[str]:
    return {person["person_id"] for _, _, person in select_case_people(people)}
