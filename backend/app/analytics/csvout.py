"""CSV export. Cells that a spreadsheet would run as a formula are prefixed so they stay text."""

import csv
import io
from collections.abc import Iterable, Sequence
from typing import Any

FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(FORMULA_STARTS):
        return "'" + value
    return "" if value is None else value


def to_csv(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([safe_cell(h) for h in headers])
    for row in rows:
        writer.writerow([safe_cell(v) for v in row])
    return out.getvalue()
