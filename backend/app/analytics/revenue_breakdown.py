"""Platform wide revenue breakdowns for the revenue dashboard: MRR by plan, industry and region,
subscription against usage revenue, customers and ARPA, unit economics, cohort retention and the
top customers. `build` is pure over `Inputs`; `rebuild` loads them with a connection that can read
every organisation (a worker) and stores one row in `revenue_breakdowns`."""

import calendar
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Engine, text

from app.analytics import definitions as d

MONTHS = 24
TOP = 10
COHORT_ROWS = 12
INVOICES = 200


@dataclass(frozen=True)
class OrgInfo:
    name: str
    industry: str
    region: str


@dataclass(frozen=True)
class PlanSub:
    org: str
    plan: str
    start: date
    end: date | None
    fee_cents: int

    def in_force(self, day: date) -> bool:
        return self.start <= day and (self.end is None or day < self.end)


@dataclass
class Inputs:
    orgs: dict[str, OrgInfo] = field(default_factory=dict)
    subs: list[PlanSub] = field(default_factory=list)
    systems: dict[str, list[tuple[date, int]]] = field(default_factory=dict)  # per org, by date
    usage_revenue: dict[str, int] = field(default_factory=dict)  # "YYYY-MM" -> cents
    tokens: dict[str, int] = field(default_factory=dict)  # "YYYY-MM" -> tokens
    invoices: list[dict[str, Any]] = field(default_factory=list)  # newest first


def month_end(first: date, as_of: date) -> date:
    last = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
    return min(last, as_of)


def month_starts(as_of: date, count: int = MONTHS) -> list[date]:
    out = []
    current = as_of.replace(day=1)
    for _ in range(count):
        out.append(current)
        current = (current - timedelta(days=1)).replace(day=1)
    return list(reversed(out))


def _label(first: date) -> str:
    return f"{first:%Y-%m}"


def _systems_on(events: list[tuple[date, int]], day: date) -> int:
    known = [qty for when, qty in sorted(events) if when <= day]
    return known[-1] if known else 0


def build(inputs: Inputs, as_of: date) -> dict[str, Any]:
    months = month_starts(as_of)
    ends = [month_end(m, as_of) for m in months]
    labels = [_label(m) for m in months]
    plans = sorted({s.plan for s in inputs.subs})

    def mrr_where(day: date, key: Any) -> int:
        return sum(s.fee_cents for s in inputs.subs if s.in_force(day) and key(s))

    by_plan = {p: [mrr_where(e, lambda s, p=p: s.plan == p) for e in ends] for p in plans}
    industries = sorted({o.industry for o in inputs.orgs.values()})
    regions = sorted({o.region for o in inputs.orgs.values()})

    def by_attr(attr: str, values: list[str]) -> dict[str, list[int]]:
        return {
            v: [
                mrr_where(
                    e,
                    lambda s, v=v: getattr(inputs.orgs.get(s.org, OrgInfo("", "", "")), attr) == v,
                )
                for e in ends
            ]
            for v in values
        }

    subs_cents = [sum(by_plan[p][i] for p in plans) for i in range(len(months))]
    usage_cents = [inputs.usage_revenue.get(label, 0) for label in labels]

    d_subs = [d.Sub(s.org, s.start, s.end, s.fee_cents) for s in inputs.subs]
    accounts, arpa, per_system, tokens_per_system = [], [], [], []
    for i, e in enumerate(ends):
        paying = d.paying_accounts(d_subs, e)
        accounts.append(d.accounts(d_subs, e))
        arpa.append(d.arpa(subs_cents[i], paying))
        systems = sum(_systems_on(ev, e) for ev in inputs.systems.values())
        per_system.append(round(subs_cents[i] / systems) if systems else 0)
        tokens_per_system.append(round(inputs.tokens.get(labels[i], 0) / systems) if systems else 0)

    # cohorts: organisations grouped by the month of their first paying subscription
    first_paid: dict[str, date] = {}
    for s in sorted(inputs.subs, key=lambda x: x.start):
        if s.fee_cents > 0 and s.org not in first_paid:
            first_paid[s.org] = s.start.replace(day=1)
    cohort_months = [m for m in months if any(v == m for v in first_paid.values())][-COHORT_ROWS:]
    cohort_labels, sizes, retention = [], [], []
    for cm in cohort_months:
        members = [o for o, m in first_paid.items() if m == cm]
        row: list[int | None] = []
        for k in range(len(months)):
            idx = months.index(cm) + k
            if idx >= len(months):
                row.append(None)
                continue
            alive = sum(1 for o in members if mrr_where(ends[idx], lambda s, o=o: s.org == o) > 0)
            row.append(round(alive * 100 / len(members)))
        cohort_labels.append(_label(cm))
        sizes.append(len(members))
        retention.append(row)

    # top customers by MRR on the last day, with the last 12 months as a sparkline
    now = {o: v for o, v in d.mrr_by_org(d_subs, as_of).items() if v > 0}
    top = []
    for org, value in sorted(now.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP]:
        info = inputs.orgs.get(org, OrgInfo(org, "", ""))
        current = next(s for s in inputs.subs if s.org == org and s.in_force(as_of))
        top.append(
            {
                "name": info.name,
                "industry": info.industry,
                "region": info.region,
                "plan": current.plan,
                "mrr_cents": value,
                "series": [mrr_where(e, lambda s, org=org: s.org == org) for e in ends[-12:]],
            }
        )

    return {
        "as_of": as_of.isoformat(),
        "months": labels,
        "mrr_by_plan": by_plan,
        "mrr_by_industry": by_attr("industry", industries),
        "mrr_by_region": by_attr("region", regions),
        "subscription_revenue_cents": subs_cents,
        "usage_revenue_cents": usage_cents,
        "accounts": accounts,
        "arpa_cents": arpa,
        "revenue_per_system_cents": per_system,
        "tokens_per_system": tokens_per_system,
        "cohorts": {"labels": cohort_labels, "sizes": sizes, "retention": retention},
        "top_customers": top,
        "recent_invoices": inputs.invoices[:INVOICES],
    }


def load_inputs(engine: Engine) -> Inputs:
    inputs = Inputs()
    with engine.connect() as conn:
        for oid, name, industry, region in conn.execute(
            text("SELECT id, name, industry, region FROM organizations")
        ):
            inputs.orgs[str(oid)] = OrgInfo(name, industry or "Other", region or "Other")
        for org, code, started, ended, fee in conn.execute(
            text(
                "SELECT s.org_id, p.code, s.started_at, s.ended_at, s.base_fee_cents "
                "FROM subscriptions s JOIN plans p ON p.id = s.plan_id"
            )
        ):
            inputs.subs.append(PlanSub(str(org), code, started, ended, int(fee)))
        for org, day, qty in conn.execute(
            text(
                "SELECT org_id, (occurred_at AT TIME ZONE 'UTC')::date, quantity FROM usage_events "
                "WHERE kind = 'active_systems' ORDER BY occurred_at"
            )
        ):
            inputs.systems.setdefault(str(org), []).append((day, int(qty)))
        for month, amount in conn.execute(
            text(
                "SELECT to_char(i.period_end, 'YYYY-MM'), sum(l.amount_cents) FROM invoice_lines l "
                "JOIN invoices i ON i.id = l.invoice_id WHERE l.kind IN ('extra_systems', "
                "'extra_requests') AND i.status <> 'void' GROUP BY 1"
            )
        ):
            inputs.usage_revenue[month] = int(amount)
        for month, total in conn.execute(
            text(
                "SELECT to_char(occurred_at AT TIME ZONE 'UTC', 'YYYY-MM'), sum(quantity) "
                "FROM usage_events WHERE kind = 'tokens_used' GROUP BY 1"
            )
        ):
            inputs.tokens[month] = int(total)
        for number, org, period_end, status, total in conn.execute(
            text(
                "SELECT i.number, o.name, i.period_end, i.status, i.total_cents FROM invoices i "
                "JOIN organizations o ON o.id = i.org_id ORDER BY i.period_end DESC, i.number DESC "
                "LIMIT :n"
            ),
            {"n": INVOICES},
        ):
            inputs.invoices.append(
                {
                    "number": number,
                    "organization": org,
                    "period_end": period_end.isoformat(),
                    "status": status,
                    "total_cents": int(total),
                }
            )
    return inputs


def rebuild(engine: Engine, as_of: date, simulated: bool | None = None) -> dict[str, Any]:
    """Compute the breakdowns as of a day and store them (replacing that day's row)."""
    payload = build(load_inputs(engine), as_of)
    with engine.begin() as conn:
        flag = (
            simulated
            if simulated is not None
            else bool(
                conn.execute(text("SELECT bool_or(is_simulated) FROM subscriptions")).scalar()
            )
        )
        conn.execute(
            text(
                "INSERT INTO revenue_breakdowns (as_of, payload, is_simulated) "
                "VALUES (:d, CAST(:p AS jsonb), :s) ON CONFLICT (as_of) DO UPDATE SET "
                "payload = EXCLUDED.payload, is_simulated = EXCLUDED.is_simulated, "
                "computed_at = now()"
            ),
            {"d": as_of, "p": json.dumps(payload), "s": flag},
        )
        conn.execute(text("DELETE FROM revenue_breakdowns WHERE as_of < :d"), {"d": as_of})
    return payload
