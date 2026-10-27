"""Turn daily rows into a series of days, weeks or months, with totals and the previous period.

Two kinds of figure: a *flow* (new MRR, requests, tokens) is summed over the period; a *stock* (MRR,
accounts, open findings) is the value on the last day of the period."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

Granularity = Literal["day", "week", "month"]
MAX_DAYS = 1100


class RangeError(ValueError):
    pass


@dataclass(frozen=True)
class Spec:
    flow: tuple[str, ...] = ()
    stock: tuple[str, ...] = ()
    json_sum: tuple[str, ...] = ()  # dict of numbers, summed key by key
    json_last: tuple[str, ...] = ()  # dict, taken from the last day

    @property
    def numeric(self) -> tuple[str, ...]:
        return self.flow + self.stock


def check_range(start: date, end: date) -> None:
    if end < start:
        raise RangeError("The end date is before the start date")
    if (end - start).days + 1 > MAX_DAYS:
        raise RangeError(f"The range is longer than {MAX_DAYS} days")


def bucket_start(day: date, granularity: Granularity) -> date:
    if granularity == "week":
        return day - timedelta(days=day.weekday())
    if granularity == "month":
        return day.replace(day=1)
    return day


def previous_period(start: date, end: date) -> tuple[date, date]:
    """The period of the same length that ends the day before `start`."""
    length = (end - start).days + 1
    return start - timedelta(days=length), start - timedelta(days=1)


def aggregate(
    rows: list[dict[str, Any]], spec: Spec, granularity: Granularity
) -> list[dict[str, Any]]:
    buckets: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: r["metric_date"]):
        buckets[bucket_start(row["metric_date"], granularity)].append(row)
    out = []
    for start, items in sorted(buckets.items()):
        last = items[-1]
        point: dict[str, Any] = {
            "period": start,
            "last_day": last["metric_date"],
            "days": len(items),
        }
        for name in spec.flow:
            point[name] = sum(int(r[name] or 0) for r in items)
        for name in spec.stock:
            point[name] = last[name]
        for name in spec.json_sum:
            merged: dict[str, int] = defaultdict(int)
            for r in items:
                for key, value in (r[name] or {}).items():
                    merged[key] += int(value)
            point[name] = dict(sorted(merged.items()))
        for name in spec.json_last:
            point[name] = dict(last[name] or {})
        out.append(point)
    return out


def totals(rows: list[dict[str, Any]], spec: Spec) -> dict[str, Any]:
    """Flows summed over the range, stocks as of its last day."""
    if not rows:
        return {name: None for name in spec.numeric}
    ordered = sorted(rows, key=lambda r: r["metric_date"])
    result: dict[str, Any] = {name: sum(int(r[name] or 0) for r in ordered) for name in spec.flow}
    result.update({name: ordered[-1][name] for name in spec.stock})
    return result


def change(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, value in current.items():
        before = previous.get(name)
        if value is None or before is None:
            out[name] = {"absolute": None, "percent": None}
            continue
        diff = value - before
        out[name] = {"absolute": diff, "percent": round(diff * 100 / before, 2) if before else None}
    return out
