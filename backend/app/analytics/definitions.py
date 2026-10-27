"""The revenue metric definitions, as pure functions over subscriptions. Every number the platform
shows is computed here; `docs/architecture.md` states the same definitions in words.

A subscription is *in force* on a day when it has started and has not yet ended
(`start <= day < end`; no end means open ended). Amounts are cents.

    MRR(day)           sum of the base fees of the subscriptions in force
    new MRR            fee of a subscription that starts for an organisation with none ending that day
    expansion MRR      increase when an organisation's subscription is replaced by a dearer one
    contraction MRR    decrease when it is replaced by a cheaper one
    churned MRR        fee of a subscription that ends for an organisation with none starting
    net new MRR        new + expansion - contraction - churned   (= MRR(day) - MRR(day - 1))
    gross churn        churned MRR of the month so far / MRR at the end of the previous month
    net revenue        MRR now of the organisations that paid on this day a year ago / their MRR then
    retention (12 m)
    ARPA               MRR / paying accounts (fee above zero)
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Sub:
    org: str
    start: date
    end: date | None
    fee_cents: int

    def in_force(self, day: date) -> bool:
        return self.start <= day and (self.end is None or day < self.end)


@dataclass(frozen=True)
class Movements:
    new: int = 0
    expansion: int = 0
    contraction: int = 0
    churned: int = 0

    @property
    def net_new(self) -> int:
        return self.new + self.expansion - self.contraction - self.churned


def mrr(subs: Iterable[Sub], day: date) -> int:
    return sum(s.fee_cents for s in subs if s.in_force(day))


def mrr_by_org(subs: Iterable[Sub], day: date) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for s in subs:
        if s.in_force(day):
            totals[s.org] += s.fee_cents
    return dict(totals)


def accounts(subs: Iterable[Sub], day: date) -> int:
    return len({s.org for s in subs if s.in_force(day)})


def paying_accounts(subs: Iterable[Sub], day: date) -> int:
    return sum(1 for fee in mrr_by_org(subs, day).values() if fee > 0)


def arpa(mrr_cents: int, paying: int) -> int:
    return round(mrr_cents / paying) if paying else 0


def movements(subs: Iterable[Sub], day: date) -> Movements:
    """What changed on `day`, organisation by organisation."""
    starting: dict[str, int] = defaultdict(int)
    ending: dict[str, int] = defaultdict(int)
    for s in subs:
        if s.start == day and s.in_force(day):
            starting[s.org] += s.fee_cents
        if s.end == day and s.start < day:
            ending[s.org] += s.fee_cents
    new = expansion = contraction = churned = 0
    for org in set(starting) | set(ending):
        has_new, has_old = org in starting, org in ending
        if has_new and has_old:
            delta = starting[org] - ending[org]
            if delta > 0:
                expansion += delta
            elif delta < 0:
                contraction += -delta
        elif has_new:
            new += starting[org]
        else:
            churned += ending[org]
    return Movements(new, expansion, contraction, churned)


def gross_churn_bp(subs: list[Sub], day: date) -> int | None:
    """Churned MRR of the month so far over the MRR at the end of the previous month, in basis points."""
    first = day.replace(day=1)
    opening = mrr(subs, first - timedelta(days=1))
    if opening <= 0:
        return None
    churned = sum(
        movements(subs, first + timedelta(days=i)).churned for i in range((day - first).days + 1)
    )
    return round(churned * 10_000 / opening)


def net_revenue_retention_bp(subs: list[Sub], day: date) -> int | None:
    """MRR today of the organisations that were paying a year ago, over their MRR then."""
    then = day - timedelta(days=365)
    cohort = {org: fee for org, fee in mrr_by_org(subs, then).items() if fee > 0}
    start_total = sum(cohort.values())
    if start_total <= 0:
        return None
    now = mrr_by_org(subs, day)
    return round(sum(now.get(org, 0) for org in cohort) * 10_000 / start_total)
