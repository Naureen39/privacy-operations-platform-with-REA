"""Search the data map for one person.

For every system, the columns that discovery found and classified as the identifier (an e-mail or
telephone column) are queried in the system's database snapshot with a read only, parameterised
statement. The result is a count per table and column, never the content. The snapshot is opened
from memory (it is decrypted for the call and never written to disk), and table and column names are
checked against the snapshot's own schema before they are quoted into a query.
"""

import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import EvidenceKind
from app.db.models import DataElement, EvidenceItem, System
from app.dsar.hashing import ID_CATEGORIES
from app.services.evidence_store import EvidenceStore

MAX_ROWS_PER_TABLE = 50
PHONE_STRIP = ("' '", "'-'", "'('", "')'", "'.'", "'+'")


@dataclass(frozen=True)
class Hit:
    system_id: uuid.UUID
    system_name: str
    table: str
    column: str
    category: str
    count: int


@dataclass
class SearchOutcome:
    hits: list[Hit] = field(default_factory=list)
    searched: list[tuple[uuid.UUID, str]] = field(default_factory=list)
    skipped: list[tuple[uuid.UUID, str, str]] = field(default_factory=list)  # system, name, reason


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def match_expression(identifier_type: str, column: str) -> str:
    col = quote(column)
    if identifier_type == "phone":
        expr = f"CAST({col} AS TEXT)"
        for char in PHONE_STRIP:
            expr = f"replace({expr}, {char}, '')"
        return expr
    return f"lower(trim(CAST({col} AS TEXT)))"


def open_snapshot(content: bytes) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.deserialize(content)
    connection.execute("PRAGMA query_only = ON")
    return connection


def schema_of(connection: sqlite3.Connection) -> dict[str, set[str]]:
    tables = [
        r[0]
        for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {t: {r[1] for r in connection.execute(f"PRAGMA table_info({quote(t)})")} for t in tables}


class SnapshotSearcher:
    def __init__(self, db: Session, store: EvidenceStore) -> None:
        self.db = db
        self.store = store

    def identifier_columns(
        self, system_id: uuid.UUID, identifier_type: str
    ) -> list[tuple[str, str, str]]:
        """(table, column, category) of the discovered identifier columns of a system."""
        wanted = ID_CATEGORIES[identifier_type]
        found: dict[tuple[str, str], str] = {}
        for e in self.db.scalars(
            select(DataElement).where(
                DataElement.system_id == system_id, DataElement.category.in_(wanted)
            )
        ):
            ctx = e.context or {}
            if ctx.get("location_kind") == "db_column" and ctx.get("table"):
                found[(str(ctx["table"]), e.name)] = str(e.category)
        return sorted((t, c, cat) for (t, c), cat in found.items())

    def _snapshot(self, system_id: uuid.UUID) -> EvidenceItem | None:
        return self.db.scalars(
            select(EvidenceItem)
            .where(
                EvidenceItem.system_id == system_id,
                EvidenceItem.kind == EvidenceKind.SQLITE_SNAPSHOT,
            )
            .order_by(EvidenceItem.created_at.desc())
        ).first()

    def coverage(self, identifier_type: str) -> tuple[
        list[tuple[System, EvidenceItem, list[tuple[str, str, str]]]],
        list[tuple[uuid.UUID, str, str]],
    ]:
        """The systems the search can cover, and those it cannot with the reason."""
        searchable = []
        skipped: list[tuple[uuid.UUID, str, str]] = []
        for system in self.db.scalars(select(System).order_by(System.name)):
            columns = self.identifier_columns(system.id, identifier_type)
            snapshot = self._snapshot(system.id)
            if snapshot is None:
                skipped.append((system.id, system.name, "no database snapshot on file"))
            elif not columns:
                skipped.append(
                    (
                        system.id,
                        system.name,
                        f"no {identifier_type} column was found in the database",
                    )
                )
            else:
                searchable.append((system, snapshot, columns))
        return searchable, skipped

    def search(self, identifier_type: str, value: str) -> SearchOutcome:
        """`value` is the normalised identifier. It is used as a bound parameter only."""
        searchable, skipped = self.coverage(identifier_type)
        outcome = SearchOutcome(skipped=skipped)
        for system, snapshot, columns in searchable:
            connection = open_snapshot(self.store.read(snapshot.storage_path, snapshot.id))
            try:
                schema = schema_of(connection)
                for table, column, category in columns:
                    if column not in schema.get(table, set()):
                        continue  # the snapshot changed since discovery
                    count = connection.execute(
                        f"SELECT count(*) FROM {quote(table)} WHERE {match_expression(identifier_type, column)} = ?",  # noqa: S608  # nosec B608
                        [value],
                    ).fetchone()[0]
                    if count:
                        outcome.hits.append(
                            Hit(system.id, system.name, table, column, category, int(count))
                        )
            finally:
                connection.close()
            outcome.searched.append((system.id, system.name))
        return outcome

    def rows(
        self, system_id: uuid.UUID, table: str, column: str, identifier_type: str, value: str
    ) -> dict[str, Any] | None:
        """The rows behind one approved result, limited and without binary values."""
        snapshot = self._snapshot(system_id)
        if snapshot is None:
            return None
        connection = open_snapshot(self.store.read(snapshot.storage_path, snapshot.id))
        try:
            schema = schema_of(connection)
            if column not in schema.get(table, set()):
                return None
            cursor = connection.execute(
                f"SELECT * FROM {quote(table)} WHERE {match_expression(identifier_type, column)} = ? LIMIT ?",  # noqa: S608  # nosec B608
                [value, MAX_ROWS_PER_TABLE],
            )
            names = [d[0] for d in cursor.description]
            rows = [
                {
                    n: (v if not isinstance(v, bytes) else "[binary]")
                    for n, v in zip(names, row, strict=True)
                }
                for row in cursor.fetchall()
            ]
            return {"columns": names, "rows": rows}
        finally:
            connection.close()
