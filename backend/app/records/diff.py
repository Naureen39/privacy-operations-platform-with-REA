"""Differences between two versions of a record."""

import json
from dataclasses import asdict, dataclass
from typing import Any

SNAPSHOT_FIELDS = (
    "name",
    "purposes",
    "data_subjects",
    "data_categories",
    "recipients",
    "transfers",
    "retention",
    "security_measures",
    "lawful_basis",
    "special_category_condition",
    "owner_user_id",
    "next_review_date",
)


@dataclass
class FieldChange:
    field: str
    change: str  # added | removed | changed
    before: Any
    after: Any
    added: list[Any] | None = None  # for lists: the items that appeared
    removed: list[Any] | None = None  # for lists: the items that disappeared


def _key(item: Any) -> str:
    return json.dumps(item, sort_keys=True, default=str)


def _empty(value: Any) -> bool:
    return value in (None, "", [], {})


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[FieldChange] = []
    for name in SNAPSHOT_FIELDS:
        a, b = before.get(name), after.get(name)
        if _key(a) == _key(b):
            continue
        if _empty(a) and not _empty(b):
            kind = "added"
        elif not _empty(a) and _empty(b):
            kind = "removed"
        else:
            kind = "changed"
        change = FieldChange(name, kind, a, b)
        if isinstance(a, list) or isinstance(b, list):
            old, new = list(a or []), list(b or [])
            old_keys, new_keys = {_key(i) for i in old}, {_key(i) for i in new}
            change.added = [i for i in new if _key(i) not in old_keys]
            change.removed = [i for i in old if _key(i) not in new_keys]
        changes.append(change)
    return [asdict(c) for c in changes]


def summarize(changes: list[dict[str, Any]]) -> str:
    if not changes:
        return "No changes"
    parts = []
    for c in changes:
        label = c["field"].replace("_", " ")
        if c["added"] is not None or c["removed"] is not None:
            parts.append(f"{label} (+{len(c['added'] or [])} -{len(c['removed'] or [])})")
        else:
            parts.append(label)
    return "Changed: " + ", ".join(parts)
