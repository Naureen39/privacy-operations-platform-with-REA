"""SQLite snapshot extraction: tables and columns, with masked sample values.

The REA path reads `inspect-sqlite-database` (database wide schema plus a bounded row sample per
table). The fallback path reads the file with the standard library, read only. Sample values are
used here to detect pattern classes and are then reduced to shape masks.
"""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.discovery.candidates import ElementCandidate
from app.discovery.patterns import dominant_pattern, masked_samples

ROW_SAMPLE = 20
MAX_TABLES = 100


@dataclass
class ColumnInfo:
    name: str
    declared_type: str | None
    primary_key: bool
    not_null: bool


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo]
    sample_columns: list[str] = field(default_factory=list)
    sample_rows: list[list[Any]] = field(default_factory=list)


def _decode_cell(cell: dict[str, Any]) -> Any:
    kind = cell.get("type")
    if kind == "integer":
        return int(cell["value"])
    if kind == "real":
        return (
            float(cell["value"]) if cell["value"] not in {"Infinity", "-Infinity", "-0"} else None
        )
    if kind == "text":
        return cell["value"]
    return None  # null and blob cells carry no pattern information


def tables_from_rea(result: dict[str, Any]) -> list[TableInfo]:
    schema = result["schema"]["normalized_result"]["schema"]["tables"]
    tables: list[TableInfo] = []
    for table in schema:
        if table.get("kind") != "table" or table["name"].startswith("sqlite_"):
            continue
        info = TableInfo(
            name=table["name"],
            columns=[
                ColumnInfo(
                    c["name"],
                    c.get("declared_type") or None,
                    (c.get("primary_key_position") or 0) > 0,
                    bool(c.get("not_null")),
                )
                for c in table.get("columns", [])
            ],
        )
        sampled = result["samples"].get(table["name"], {})
        rows = (sampled.get("rows") or {}) if sampled.get("ok") else {}
        info.sample_columns = list(rows.get("columns", []))
        info.sample_rows = [[_decode_cell(c) for c in row] for row in rows.get("values", [])]
        tables.append(info)
    return tables[:MAX_TABLES]


def tables_from_file(path: Path, row_sample: int = ROW_SAMPLE) -> list[TableInfo]:
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    db = sqlite3.connect(uri, uri=True)
    try:
        names = [
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        tables = []
        for name in names[:MAX_TABLES]:
            quoted = '"' + name.replace('"', '""') + '"'
            info_rows = db.execute(f"PRAGMA table_info({quoted})").fetchall()
            info = TableInfo(
                name=name,
                columns=[ColumnInfo(r[1], r[2] or None, bool(r[5]), bool(r[3])) for r in info_rows],
            )
            cursor = db.execute(f"SELECT * FROM {quoted} LIMIT ?", [row_sample])  # noqa: S608
            info.sample_columns = [d[0] for d in cursor.description]
            info.sample_rows = [
                [v if not isinstance(v, bytes) else None for v in row] for row in cursor.fetchall()
            ]
            tables.append(info)
        return tables
    finally:
        db.close()


def extract_tables(tables: list[TableInfo]) -> list[ElementCandidate]:
    candidates: list[ElementCandidate] = []
    for table in tables:
        index = {name: i for i, name in enumerate(table.sample_columns)}
        for column in table.columns:
            # An auto increment integer key identifies a row, not a person.
            if column.primary_key and (column.declared_type or "").upper() == "INTEGER":
                continue
            values = [row[index[column.name]] for row in table.sample_rows if column.name in index]
            pattern, observed = dominant_pattern(values)
            candidates.append(
                ElementCandidate(
                    name=column.name,
                    path=f"db:{table.name}",
                    location_kind="db_column",
                    data_type=column.declared_type,
                    pattern_class=pattern,
                    context={
                        "table": table.name,
                        "declared_type": column.declared_type,
                        "not_null": column.not_null,
                        "table_columns": [c.name for c in table.columns],
                        "values_seen": observed,
                        "masked_samples": masked_samples(values),
                    },
                )
            )
    return candidates
