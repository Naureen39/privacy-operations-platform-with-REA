"""The platform wide daily snapshot (`daily_metrics`). The rows are computed from the tenant tables
with a connection that can read every organisation (the database owner, in a worker); the API only
reads the result. `build_rows` is pure so every formula can be tested on hand-made data."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Engine, text

from app.analytics import definitions as d

FAILED = ("error", "rate_limited", "schema_failure")


@dataclass
class Inputs:
    subs: list[d.Sub] = field(default_factory=list)
    simulated_orgs: set[str] = field(default_factory=set)
    usage_revenue: dict[date, int] = field(default_factory=dict)  # by invoice period end
    requests: dict[date, int] = field(default_factory=dict)
    systems_events: dict[str, list[tuple[date, int]]] = field(
        default_factory=dict
    )  # per org, by date
    tokens: dict[date, dict[str, int]] = field(default_factory=dict)
    failovers: dict[date, int] = field(default_factory=dict)
    cache_hits: dict[date, int] = field(default_factory=dict)


def systems_on(inputs: Inputs, day: date) -> int:
    total = 0
    for events in inputs.systems_events.values():
        known = [qty for when, qty in events if when <= day]
        if known:
            total += known[-1]
    return total


def build_rows(inputs: Inputs, start: date, end: date) -> list[dict[str, Any]]:
    for events in inputs.systems_events.values():
        events.sort()
    rows = []
    day = start
    while day <= end:
        move = d.movements(inputs.subs, day)
        total = d.mrr(inputs.subs, day)
        paying = d.paying_accounts(inputs.subs, day)
        in_force = [s for s in inputs.subs if s.in_force(day)]
        rows.append(
            {
                "metric_date": day,
                "mrr_cents": total,
                "new_mrr_cents": move.new,
                "expansion_mrr_cents": move.expansion,
                "contraction_mrr_cents": move.contraction,
                "churned_mrr_cents": move.churned,
                "usage_revenue_cents": inputs.usage_revenue.get(day, 0),
                "accounts": len({s.org for s in in_force}),
                "systems": systems_on(inputs, day),
                "requests": inputs.requests.get(day, 0),
                "tokens_by_provider": inputs.tokens.get(day, {}),
                "failovers": inputs.failovers.get(day, 0),
                "cache_hits": inputs.cache_hits.get(day, 0),
                "is_simulated": any(s.org in inputs.simulated_orgs for s in in_force),
                "paying_accounts": paying,
                "arpa_cents": d.arpa(total, paying),
                "nrr_bp": d.net_revenue_retention_bp(inputs.subs, day),
                "gross_churn_bp": d.gross_churn_bp(inputs.subs, day),
            }
        )
        day += timedelta(days=1)
    return rows


def load_inputs(engine: Engine) -> Inputs:
    """Read what the snapshot needs from every organisation."""
    inputs = Inputs()
    with engine.connect() as conn:
        for org, started, ended, fee, simulated in conn.execute(
            text(
                "SELECT org_id, started_at, ended_at, base_fee_cents, is_simulated FROM subscriptions"
            )
        ):
            inputs.subs.append(d.Sub(str(org), started, ended, fee))
            if simulated:
                inputs.simulated_orgs.add(str(org))
        for period_end, amount in conn.execute(
            text(
                "SELECT i.period_end, sum(l.amount_cents) FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id "
                "WHERE l.kind IN ('extra_systems', 'extra_requests') AND i.status <> 'void' GROUP BY i.period_end"
            )
        ):
            inputs.usage_revenue[period_end] = int(amount)
        for day, total in conn.execute(
            text(
                "SELECT (occurred_at AT TIME ZONE 'UTC')::date, sum(quantity) FROM usage_events WHERE kind = 'requests_processed' GROUP BY 1"
            )
        ):
            inputs.requests[day] = inputs.requests.get(day, 0) + int(total)
        for org, day, qty in conn.execute(
            text(
                "SELECT org_id, (occurred_at AT TIME ZONE 'UTC')::date, quantity FROM usage_events WHERE kind = 'active_systems' ORDER BY occurred_at"
            )
        ):
            inputs.systems_events.setdefault(str(org), []).append((day, int(qty)))
        tokens: dict[date, dict[str, int]] = defaultdict(dict)
        for day, provider, total in conn.execute(
            text(
                "SELECT (occurred_at AT TIME ZONE 'UTC')::date, coalesce(provider, 'unknown'), sum(quantity) FROM usage_events WHERE kind = 'tokens_used' GROUP BY 1, 2"
            )
        ):
            tokens[day][provider] = int(total)
        inputs.tokens = dict(tokens)
        for day, failed, hits in conn.execute(
            text(
                "SELECT (created_at AT TIME ZONE 'UTC')::date, count(*) FILTER (WHERE status IN ('error', 'rate_limited', 'schema_failure')), "
                "count(*) FILTER (WHERE cache_hit) FROM llm_calls GROUP BY 1"
            )
        ):
            inputs.failovers[day], inputs.cache_hits[day] = int(failed), int(hits)
    return inputs


COLUMNS = (
    "metric_date", "mrr_cents", "new_mrr_cents", "expansion_mrr_cents", "contraction_mrr_cents",
    "churned_mrr_cents", "usage_revenue_cents", "accounts", "systems", "requests", "tokens_by_provider",
    "failovers", "cache_hits", "is_simulated", "paying_accounts", "arpa_cents", "nrr_bp", "gross_churn_bp",
)  # fmt: skip


def rebuild(
    engine: Engine, start: date, end: date, overlay: dict[date, dict[str, int]] | None = None
) -> int:
    """Compute and store the snapshot for a range of days (replacing what is there). `overlay` lets
    the demonstration seed add simulated operations figures (failovers, cache hits) for days that
    have no call log."""
    import json

    rows = build_rows(load_inputs(engine), start, end)
    for row in rows:
        extra = (overlay or {}).get(row["metric_date"], {})
        for key in ("failovers", "cache_hits"):
            if not row[key] and key in extra:
                row[key] = extra[key]
    names = ", ".join(COLUMNS)
    values = ", ".join(f":{c}" for c in COLUMNS)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS if c != "metric_date")
    # the column list is the module constant above, never user input
    sql = text(
        f"INSERT INTO daily_metrics ({names}) VALUES ({values}) ON CONFLICT (metric_date) DO UPDATE SET {updates}"  # noqa: S608  # nosec B608
    )
    with engine.begin() as conn:
        for row in rows:
            conn.execute(sql, {**row, "tokens_by_provider": json.dumps(row["tokens_by_provider"])})
    return len(rows)
