"""The breakdowns behind the compliance dashboard that a daily snapshot cannot give: findings
opened and closed over time, lawful bases, data categories by system, the flow from systems to
vendors to countries, request volume and response times, record freshness, discovery confidence and
the operations figures (tokens, failovers, cache hits, REA run time). Computed live from the
organisation's own rows, inside its tenant session."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.series import Granularity, bucket_start
from app.billing.usage import day_end, day_start
from app.db.enums import ActivityStatus, FindingStatus, LlmCallStatus
from app.db.models import (
    AccessRequest,
    DataElement,
    DiscoveryEvidence,
    Dpia,
    EvidenceItem,
    Finding,
    LlmCall,
    ProcessingActivity,
    Recipient,
    System,
)
from app.fusion.loader import load_adequacy

FRESHNESS_BUCKETS = (
    "overdue",
    "0-30 days",
    "31-90 days",
    "91-180 days",
    "over 180 days",
    "no date",
)
CONFIDENCE_BINS = [(0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
TOP_CATEGORIES = 12
FAILED = (LlmCallStatus.ERROR, LlmCallStatus.RATE_LIMITED, LlmCallStatus.SCHEMA_FAILURE)


def _day(value: datetime | None) -> date | None:
    return value.date() if value else None


def _periods(start: date, end: date, granularity: Granularity) -> list[date]:
    out, day = [], bucket_start(start, granularity)
    while day <= end:
        out.append(day)
        if granularity == "day":
            day += timedelta(days=1)
        elif granularity == "week":
            day += timedelta(days=7)
        else:
            day = (day + timedelta(days=32)).replace(day=1)
    return out


def findings_flow(db: Session, start: date, end: date, granularity: Granularity) -> dict[str, Any]:
    periods = _periods(start, end, granularity)
    opened: dict[date, int] = defaultdict(int)
    closed: dict[date, int] = defaultdict(int)
    rows = db.scalars(
        select(Finding).where(
            Finding.created_at < day_end(end),
            (Finding.resolved_at.is_(None)) | (Finding.resolved_at >= day_start(start)),
        )
    )
    open_now: dict[str, dict[str, int]] = {"severity": defaultdict(int), "type": defaultdict(int)}
    for f in rows:
        created = _day(f.created_at)
        if created and start <= created <= end:
            opened[bucket_start(created, granularity)] += 1
        resolved = _day(f.resolved_at)
        if resolved and start <= resolved <= end:
            closed[bucket_start(resolved, granularity)] += 1
        if f.status in (FindingStatus.OPEN, FindingStatus.ACKNOWLEDGED):
            open_now["severity"][f.severity.value] += 1
            open_now["type"][f.type] += 1
    return {
        "periods": [p.isoformat() for p in periods],
        "opened": [opened[p] for p in periods],
        "closed": [closed[p] for p in periods],
        "net": [opened[p] - closed[p] for p in periods],
        "open_by_severity": dict(sorted(open_now["severity"].items())),
        "open_by_type": dict(sorted(open_now["type"].items())),
    }


def lawful_bases(db: Session) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for basis in db.scalars(
        select(ProcessingActivity.lawful_basis).where(
            ProcessingActivity.status != ActivityStatus.ARCHIVED
        )
    ):
        counts[basis or "not recorded"] += 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def category_heatmap(db: Session) -> dict[str, Any]:
    names = {s.id: s.name for s in db.scalars(select(System))}
    rows = db.execute(
        select(DataElement.system_id, DataElement.category, func.count())
        .where(DataElement.category.is_not(None), DataElement.review_status != "rejected")
        .group_by(DataElement.system_id, DataElement.category)
    ).all()
    totals: dict[str, int] = defaultdict(int)
    for _, category, n in rows:
        totals[str(category)] += n
    categories = [c for c, _ in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))][
        :TOP_CATEGORIES
    ]
    systems = sorted({names[s] for s, _, _ in rows if s in names})
    cells = [[names[s], c, int(n)] for s, c, n in rows if s in names and c in categories]
    return {"systems": systems, "categories": categories, "cells": cells}


def data_flow(db: Session) -> dict[str, Any]:
    adequate, eea = load_adequacy()
    safe = adequate | eea
    names = {s.id: s.name for s in db.scalars(select(System))}
    links: dict[tuple[str, str, str], int] = defaultdict(int)  # (kind, source, target)
    gaps: set[str] = set()
    for r in db.scalars(select(Recipient)):
        if (r.context or {}).get("internal") or r.system_id not in names:
            continue
        vendor = r.vendor or r.domain
        country = r.country or "unknown"
        links[("system", names[r.system_id], vendor)] += 1
        links[("country", vendor, country)] += 1
        if country not in safe and country != "unknown" and not r.safeguard:
            gaps.add(vendor)
    nodes: dict[str, str] = {}
    out_links = []
    for (kind, source, target), n in sorted(links.items()):
        nodes.setdefault(source, "system" if kind == "system" else "vendor")
        nodes.setdefault(target, "vendor" if kind == "system" else "country")
        out_links.append({"source": source, "target": target, "value": n})
    return {
        "nodes": [{"name": n, "kind": k, "gap": n in gaps} for n, k in sorted(nodes.items())],
        "links": out_links,
        "gaps": sorted(gaps),
    }


def request_volume(db: Session, start: date, end: date, granularity: Granularity) -> dict[str, Any]:
    periods = _periods(start, end, granularity)
    received: dict[date, int] = defaultdict(int)
    days_taken: dict[date, list[int]] = defaultdict(list)
    on_time = answered = 0
    for r in db.scalars(select(AccessRequest)):
        if start <= r.received_date <= end:
            received[bucket_start(r.received_date, granularity)] += 1
        responded = _day(r.responded_at)
        if responded and start <= responded <= end:
            days_taken[bucket_start(responded, granularity)].append(
                (responded - r.received_date).days
            )
            answered += 1
            on_time += int(responded <= r.deadline_date)
    return {
        "periods": [p.isoformat() for p in periods],
        "received": [received[p] for p in periods],
        "median_days": [median(days_taken[p]) if days_taken[p] else None for p in periods],
        "answered": answered,
        "on_time_rate": round(on_time * 100 / answered, 1) if answered else None,
    }


def assessments_by_status(db: Session) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for status in db.scalars(select(Dpia.status)):
        counts[status.value] += 1
    return dict(sorted(counts.items()))


def freshness(db: Session, today: date) -> dict[str, int]:
    counts = dict.fromkeys(FRESHNESS_BUCKETS, 0)
    for due in db.scalars(
        select(ProcessingActivity.next_review_date).where(
            ProcessingActivity.status != ActivityStatus.ARCHIVED
        )
    ):
        if due is None:
            counts["no date"] += 1
            continue
        left = (due - today).days
        key = (
            "overdue"
            if left < 0
            else (
                "0-30 days"
                if left <= 30
                else (
                    "31-90 days"
                    if left <= 90
                    else "91-180 days" if left <= 180 else "over 180 days"
                )
            )
        )
        counts[key] += 1
    return counts


def confidence_distribution(db: Session) -> dict[str, int]:
    bins = {f"{lo:.1f}-{min(hi, 1.0):.1f}": 0 for lo, hi in CONFIDENCE_BINS}
    labels = list(bins)
    for value in db.scalars(
        select(DataElement.confidence).where(DataElement.confidence.is_not(None))
    ):
        if value is None:
            continue
        for (lo, hi), label in zip(CONFIDENCE_BINS, labels, strict=True):
            if lo <= float(value) < hi:
                bins[label] += 1
                break
    return bins


def operations(db: Session, start: date, end: date) -> dict[str, Any]:
    window = (LlmCall.created_at >= day_start(start), LlmCall.created_at < day_end(end))
    names = {s.id: s.name for s in db.scalars(select(System))}
    tokens: dict[str, dict[str, int]] = defaultdict(dict)
    for system_id, provider, total in db.execute(
        select(
            LlmCall.system_id, LlmCall.provider, func.sum(LlmCall.tokens_in + LlmCall.tokens_out)
        )
        .where(*window, LlmCall.cache_hit.is_(False))
        .group_by(LlmCall.system_id, LlmCall.provider)
    ):
        tokens[names.get(system_id, "Organization wide") if system_id else "Organization wide"][
            provider
        ] = int(total or 0)
    calls = db.scalar(select(func.count()).select_from(LlmCall).where(*window)) or 0
    hits = (
        db.scalar(
            select(func.count()).select_from(LlmCall).where(*window, LlmCall.cache_hit.is_(True))
        )
        or 0
    )
    failovers = (
        db.scalar(
            select(func.count()).select_from(LlmCall).where(*window, LlmCall.status.in_(FAILED))
        )
        or 0
    )
    rea_by_kind: dict[str, list[int]] = defaultdict(list)
    mix: dict[str, int] = defaultdict(int)
    run_window = (
        DiscoveryEvidence.created_at >= day_start(start),
        DiscoveryEvidence.created_at < day_end(end),
    )
    for kind, extractor, ms in db.execute(
        select(EvidenceItem.kind, DiscoveryEvidence.extractor, DiscoveryEvidence.duration_ms)
        .join(EvidenceItem, EvidenceItem.id == DiscoveryEvidence.evidence_item_id)
        .where(*run_window)
    ):
        mix[extractor] += 1
        if ms is not None:
            rea_by_kind[str(getattr(kind, "value", kind))].append(int(ms))
    return {
        "tokens_by_system": {k: dict(sorted(v.items())) for k, v in sorted(tokens.items())},
        "calls": int(calls),
        "cache_hit_rate": round(hits * 100 / calls, 1) if calls else None,
        "failovers": int(failovers),
        "rea_ms_by_kind": {k: round(sum(v) / len(v)) for k, v in sorted(rea_by_kind.items())},
        "extractor_mix": dict(sorted(mix.items())),
    }


def compute(
    db: Session, start: date, end: date, granularity: Granularity, today: date
) -> dict[str, Any]:
    return {
        "start": start,
        "end": end,
        "granularity": granularity,
        "findings": findings_flow(db, start, end, granularity),
        "lawful_bases": lawful_bases(db),
        "category_heatmap": category_heatmap(db),
        "data_flow": data_flow(db),
        "requests": request_volume(db, start, end, granularity),
        "assessments": assessments_by_status(db),
        "freshness": freshness(db, today),
        "confidence": confidence_distribution(db),
        "operations": operations(db, start, end),
    }
