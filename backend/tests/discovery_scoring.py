"""Score discovery output against the reference estate's ground truth."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DATASETS = Path(__file__).resolve().parents[2] / "datasets"
ESTATE = DATASETS / "estate"
SYSTEM_IDS = [
    "web_shop", "web_analytics", "helpdesk", "crm", "clinic_portal", "newsletter", "staff_desktop", "hr_onboarding",
]  # fmt: skip

KIND_BY_EVIDENCE_FILE = {
    "har": "capture.har",
    "website": "website_snapshot.html",
    "sqlite_snapshot": "snapshot.sqlite",
}


def ground_truth(system_id: str) -> dict[str, Any]:
    return json.loads((ESTATE / system_id / "ground_truth.json").read_text(encoding="utf-8"))


def element_keys(candidates: list[Any]) -> set[tuple[str, ...]]:
    """Keys a ground-truth location can be matched against."""
    keys: set[tuple[str, ...]] = set()
    for c in candidates:
        if c.location_kind == "db_column":
            keys.add(("db_column", c.context["table"], c.name))
        else:
            keys.add((c.location_kind, c.name))
    return keys


def location_key(location: dict[str, str]) -> tuple[str, ...]:
    if location["kind"] == "db_column":
        return ("db_column", location["table"], location["column"])
    return (location["kind"], location["name"])


@dataclass
class Score:
    elements_total: int = 0
    elements_found: int = 0
    locations_total: int = 0
    locations_found: int = 0
    hosts_total: int = 0
    hosts_found: int = 0
    missed_elements: list[str] = field(default_factory=list)
    missed_hosts: list[str] = field(default_factory=list)
    candidates: int = 0
    matched_candidates: int = 0

    @property
    def element_recall(self) -> float:
        return self.elements_found / self.elements_total if self.elements_total else 1.0

    @property
    def host_recall(self) -> float:
        return self.hosts_found / self.hosts_total if self.hosts_total else 1.0

    @property
    def location_recall(self) -> float:
        return self.locations_found / self.locations_total if self.locations_total else 1.0

    @property
    def element_precision(self) -> float:
        return self.matched_candidates / self.candidates if self.candidates else 1.0


def score_system(system_id: str, element_candidates: list[Any], hosts: set[str]) -> Score:
    truth = ground_truth(system_id)
    keys = element_keys(element_candidates)
    result = Score()
    truth_keys: set[tuple[str, ...]] = set()
    for element in truth["data_elements"]:
        locations = [location_key(loc) for loc in element["locations"]]
        truth_keys.update(locations)
        result.elements_total += 1
        result.locations_total += len(locations)
        matched = [k for k in locations if k in keys]
        result.locations_found += len(matched)
        if matched:
            result.elements_found += 1
        else:
            result.missed_elements.append(element["id"])
    for recipient in truth["recipients"]:
        for host in recipient["hosts"]:
            result.hosts_total += 1
            if host in hosts:
                result.hosts_found += 1
            else:
                result.missed_hosts.append(host)
    result.candidates = len(keys)
    result.matched_candidates = len(keys & truth_keys)
    return result


def aggregate(scores: list[Score]) -> Score:
    total = Score()
    for s in scores:
        for name in (
            "elements_total",
            "elements_found",
            "locations_total",
            "locations_found",
            "hosts_total",
            "hosts_found",
            "candidates",
            "matched_candidates",
        ):
            setattr(total, name, getattr(total, name) + getattr(s, name))
        total.missed_elements += s.missed_elements
        total.missed_hosts += s.missed_hosts
    return total
