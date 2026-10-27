"""Billing and metric formulas, with no database: pricing, the revenue definitions, series
aggregation, CSV, the cache and the simulated history generator."""

import random
from datetime import date, timedelta

import pytest

from app.analytics import definitions as d
from app.analytics import series
from app.analytics.cache import MemoryCache, cache_key
from app.analytics.csvout import safe_cell, to_csv
from app.analytics.daily import Inputs, build_rows, systems_on
from app.billing import pricing
from app.db.enums import InvoiceLineKind
from app.seeding import billing_history as history

STARTER = pricing.PlanTerms("starter", 0, 3, 5, 0, 0)
PROFESSIONAL = pricing.PlanTerms("professional", 39_900, 25, 50, 1_500, 800)
ENTERPRISE = pricing.PlanTerms("enterprise", 180_000, 150, 500, 600, 400)


# -- pricing -------------------------------------------------------------------------------------


def test_starter_is_free_and_never_bills_extras() -> None:
    lines = pricing.price_invoice(STARTER, 0, 10, 40, "May 2026")
    assert [line.kind for line in lines] == [InvoiceLineKind.BASE]
    assert pricing.total_cents(lines) == 0


def test_professional_bills_the_base_fee_plus_what_is_beyond_the_allowance() -> None:
    lines = pricing.price_invoice(PROFESSIONAL, 39_900, 28, 60, "May 2026")
    assert [(line.kind, line.quantity, line.unit_cents) for line in lines] == [
        (InvoiceLineKind.BASE, 1, 39_900),
        (InvoiceLineKind.EXTRA_SYSTEMS, 3, 1_500),
        (InvoiceLineKind.EXTRA_REQUESTS, 10, 800),
    ]
    assert pricing.total_cents(lines) == 39_900 + 4_500 + 8_000
    assert all(line.amount_cents == line.quantity * line.unit_cents for line in lines)


@pytest.mark.parametrize(("systems", "requests"), [(25, 50), (0, 0), (24, 49)])
def test_usage_at_or_under_the_allowance_adds_no_lines(systems: int, requests: int) -> None:
    lines = pricing.price_invoice(PROFESSIONAL, 39_900, systems, requests, "x")
    assert len(lines) == 1


def test_the_base_line_uses_the_fee_of_the_subscription_not_the_current_price() -> None:
    lines = pricing.price_invoice(ENTERPRISE, 150_000, 150, 500, "x")
    assert pricing.total_cents(lines) == 150_000


def test_month_helpers() -> None:
    assert pricing.month_bounds(2024, 2) == (date(2024, 2, 1), date(2024, 2, 29))
    assert pricing.parse_month("2026-04") == (date(2026, 4, 1), date(2026, 4, 30))
    assert pricing.previous_month(date(2026, 1, 15)) == (date(2025, 12, 1), date(2025, 12, 31))
    assert pricing.invoice_number(date(2026, 4, 1), 7) == "INV-202604-0007"
    with pytest.raises(ValueError):
        pricing.parse_month("2026-13")


# -- revenue definitions -------------------------------------------------------------------------

D = date


def test_a_subscription_is_in_force_from_its_start_until_the_day_it_ends() -> None:
    sub = d.Sub("a", D(2026, 1, 10), D(2026, 3, 10), 1000)
    assert not sub.in_force(D(2026, 1, 9))
    assert sub.in_force(D(2026, 1, 10)) and sub.in_force(D(2026, 3, 9))
    assert not sub.in_force(D(2026, 3, 10))
    assert d.Sub("a", D(2026, 1, 10), None, 1000).in_force(D(2030, 1, 1))


def test_mrr_accounts_paying_accounts_and_arpa() -> None:
    subs = [
        d.Sub("a", D(2026, 1, 1), None, 40_000),
        d.Sub("b", D(2026, 1, 1), None, 0),
        d.Sub("c", D(2026, 1, 1), D(2026, 2, 1), 180_000),
    ]
    day = D(2026, 1, 15)
    assert d.mrr(subs, day) == 220_000
    assert d.accounts(subs, day) == 3
    assert d.paying_accounts(subs, day) == 2  # the free account does not count
    assert d.arpa(d.mrr(subs, day), d.paying_accounts(subs, day)) == 110_000
    assert d.arpa(0, 0) == 0
    assert d.mrr(subs, D(2026, 2, 1)) == 40_000


def test_movements_are_new_expansion_contraction_and_churn() -> None:
    day = D(2026, 3, 1)
    subs = [
        d.Sub("new", day, None, 40_000),
        d.Sub("up", D(2026, 1, 1), day, 40_000),
        d.Sub("up", day, None, 180_000),
        d.Sub("down", D(2026, 1, 1), day, 180_000),
        d.Sub("down", day, None, 40_000),
        d.Sub("gone", D(2026, 1, 1), day, 40_000),
        d.Sub("same", D(2026, 1, 1), None, 40_000),
    ]
    move = d.movements(subs, day)
    assert (move.new, move.expansion, move.contraction, move.churned) == (
        40_000, 140_000, 140_000, 40_000,
    )  # fmt: skip
    assert move.net_new == 40_000 + 140_000 - 140_000 - 40_000


def test_a_plan_change_on_the_day_of_signup_is_one_new_subscription() -> None:
    day = D(2026, 3, 1)
    subs = [d.Sub("x", day, None, 40_000)]
    assert d.movements(subs, day) == d.Movements(new=40_000)


def test_net_new_mrr_equals_the_change_in_mrr_every_day() -> None:
    rng = random.Random(1)
    subs: list[d.Sub] = []
    for n in range(25):
        start = D(2026, 1, 1) + timedelta(days=rng.randint(0, 120))
        end = start + timedelta(days=rng.randint(1, 60)) if rng.random() < 0.5 else None
        subs.append(d.Sub(f"org{n}", start, end, rng.choice([0, 40_000, 180_000])))
        if end and rng.random() < 0.6:  # upgraded or downgraded on the day it ended
            subs.append(d.Sub(f"org{n}", end, None, rng.choice([0, 40_000, 180_000])))
    day = D(2026, 1, 2)
    while day < D(2026, 7, 1):
        delta = d.mrr(subs, day) - d.mrr(subs, day - timedelta(days=1))
        assert d.movements(subs, day).net_new == delta, day
        day += timedelta(days=1)


def test_gross_churn_is_churned_mrr_of_the_month_over_the_opening_mrr() -> None:
    subs = [
        d.Sub("a", D(2026, 1, 1), D(2026, 3, 10), 10_000),
        d.Sub("b", D(2026, 1, 1), None, 90_000),
    ]
    assert d.gross_churn_bp(subs, D(2026, 3, 9)) == 0
    assert d.gross_churn_bp(subs, D(2026, 3, 31)) == 1000  # 10 000 of 100 000 = 10 percent
    assert d.gross_churn_bp([], D(2026, 3, 31)) is None


def test_net_revenue_retention_follows_the_organisations_of_a_year_ago() -> None:
    today = D(2026, 6, 1)
    year_ago = today - timedelta(days=365)
    subs = [
        d.Sub("grew", D(2024, 1, 1), year_ago + timedelta(days=30), 40_000),
        d.Sub("grew", year_ago + timedelta(days=30), None, 100_000),
        d.Sub("left", D(2024, 1, 1), year_ago + timedelta(days=10), 60_000),
        d.Sub("newcomer", today - timedelta(days=20), None, 500_000),  # not in the cohort
    ]
    # cohort then: grew 40 000 + left 60 000; now: grew 100 000
    assert d.net_revenue_retention_bp(subs, today) == 10_000
    assert d.net_revenue_retention_bp([d.Sub("n", today, None, 1)], today) is None


# -- daily snapshot ------------------------------------------------------------------------------


def test_daily_rows_carry_every_column_from_the_inputs() -> None:
    day = D(2026, 2, 3)
    inputs = Inputs(
        subs=[d.Sub("a", day, None, 40_000), d.Sub("b", D(2026, 1, 1), None, 0)],
        simulated_orgs={"a"},
        usage_revenue={day: 5_000},
        requests={day: 9},
        systems_events={"a": [(D(2026, 2, 1), 4), (D(2026, 2, 10), 8)], "b": [(D(2026, 1, 5), 2)]},
        tokens={day: {"groq": 100, "gemini": 50}},
        failovers={day: 2},
        cache_hits={day: 3},
    )
    row = build_rows(inputs, day, day)[0]
    assert row["mrr_cents"] == 40_000 and row["new_mrr_cents"] == 40_000
    assert row["usage_revenue_cents"] == 5_000 and row["requests"] == 9
    assert row["accounts"] == 2 and row["paying_accounts"] == 1 and row["arpa_cents"] == 40_000
    assert row["systems"] == 4 + 2  # the latest known count of each organisation on that day
    assert row["tokens_by_provider"] == {"groq": 100, "gemini": 50}
    assert (row["failovers"], row["cache_hits"], row["is_simulated"]) == (2, 3, True)
    assert systems_on(inputs, D(2026, 2, 12)) == 8 + 2


# -- series --------------------------------------------------------------------------------------


def _rows(days: int, start: date = D(2026, 1, 1)) -> list[dict[str, object]]:
    return [
        {"metric_date": start + timedelta(days=i), "flow": 10, "stock": i, "bag": {"a": 1, "b": i}}
        for i in range(days)
    ]


def test_flows_are_summed_and_stocks_are_the_last_value_of_each_period() -> None:
    spec = series.Spec(flow=("flow",), stock=("stock",), json_sum=("bag",))
    monthly = series.aggregate(_rows(45), spec, "month")  # type: ignore[arg-type]
    assert [p["period"] for p in monthly] == [D(2026, 1, 1), D(2026, 2, 1)]
    assert monthly[0]["flow"] == 310 and monthly[0]["stock"] == 30
    assert monthly[1]["flow"] == 140 and monthly[1]["stock"] == 44
    assert monthly[0]["bag"] == {"a": 31, "b": sum(range(31))}
    weekly = series.aggregate(_rows(14, D(2026, 1, 5)), spec, "week")  # type: ignore[arg-type]
    assert [p["period"] for p in weekly] == [D(2026, 1, 5), D(2026, 1, 12)]
    assert weekly[0]["flow"] == 70 and weekly[0]["days"] == 7
    assert len(series.aggregate(_rows(10), spec, "day")) == 10  # type: ignore[arg-type]


def test_totals_sum_flows_and_take_stocks_as_of_the_last_day() -> None:
    spec = series.Spec(flow=("flow",), stock=("stock",))
    assert series.totals(_rows(5), spec) == {"flow": 50, "stock": 4}  # type: ignore[arg-type]
    assert series.totals([], spec) == {"flow": None, "stock": None}


def test_the_previous_period_has_the_same_length_and_ends_the_day_before() -> None:
    assert series.previous_period(D(2026, 3, 1), D(2026, 3, 31)) == (D(2026, 1, 29), D(2026, 2, 28))
    assert series.previous_period(D(2026, 3, 5), D(2026, 3, 5)) == (D(2026, 3, 4), D(2026, 3, 4))


def test_change_gives_absolute_and_percent_and_survives_a_zero_or_missing_base() -> None:
    result = series.change(
        {"a": 150, "b": 5, "c": None, "d": 3}, {"a": 100, "b": 0, "c": 4, "d": None}
    )
    assert result["a"] == {"absolute": 50, "percent": 50.0}
    assert result["b"] == {"absolute": 5, "percent": None}
    assert result["c"] == {"absolute": None, "percent": None}
    assert result["d"] == {"absolute": None, "percent": None}


def test_the_range_is_checked() -> None:
    series.check_range(D(2026, 1, 1), D(2026, 1, 1))
    with pytest.raises(series.RangeError):
        series.check_range(D(2026, 2, 1), D(2026, 1, 1))
    with pytest.raises(series.RangeError):
        series.check_range(D(2020, 1, 1), D(2026, 1, 1))


# -- csv and cache -------------------------------------------------------------------------------


def test_csv_cells_that_a_spreadsheet_would_run_are_kept_as_text() -> None:
    assert safe_cell("=SUM(A1)") == "'=SUM(A1)"
    assert safe_cell("+1") == "'+1" and safe_cell("@x") == "'@x" and safe_cell("-2") == "'-2"
    assert safe_cell("plain") == "plain" and safe_cell(None) == "" and safe_cell(5) == 5
    out = to_csv(["a", "=b"], [[1, "=cmd"], [None, "ok"]])
    assert out.splitlines() == ["a,'=b", "1,'=cmd", ",ok"]


def test_a_cached_value_lives_for_sixty_seconds_and_a_bump_drops_everything() -> None:
    now = [1000.0]
    cache = MemoryCache(clock=lambda: now[0])
    key = cache_key(cache, "platform", "revenue", {"start": D(2026, 1, 1)})
    assert cache.get(key) is None
    cache.set(key, b"payload")
    now[0] += 59
    assert cache.get(key) == b"payload"
    now[0] += 2
    assert cache.get(key) is None
    cache.set(key, b"again")
    cache.bump()
    assert cache.get(key) is None
    assert cache_key(cache, "platform", "revenue", {"start": D(2026, 1, 1)}) != key
    assert cache_key(cache, "a", "x", {"p": 1}) != cache_key(cache, "b", "x", {"p": 1})
    assert cache_key(cache, "a", "x", {"p": 1, "q": 2}) == cache_key(
        cache, "a", "x", {"q": 2, "p": 1}
    )


# -- the simulated history generator -------------------------------------------------------------


def _history(seed: int = 42, count: int = 120) -> list[history.OrgPlan]:
    return history.plan_history(random.Random(seed), count, D(2024, 11, 1), D(2026, 10, 26))


def test_the_history_is_the_same_for_the_same_seed_and_differs_for_another() -> None:
    first, second, other = _history(), _history(), _history(seed=7)
    assert [(o.slug, o.signup) for o in first] == [(o.slug, o.signup) for o in second]
    assert [o.slug for o in first] != [o.slug for o in other]


def test_the_history_covers_five_industries_four_regions_and_all_plans() -> None:
    orgs = _history()
    assert len(orgs) == 120 and len({o.slug for o in orgs}) == 120
    assert {o.industry for o in orgs} == set(history.INDUSTRIES)
    assert {o.region for o in orgs} == set(history.REGIONS)
    first_plans = [o.months[0].plan for o in orgs]
    assert set(first_plans) == {"starter", "professional", "enterprise"}
    assert first_plans.count("starter") > first_plans.count("enterprise")


def test_signups_follow_an_s_curve() -> None:
    months = 24
    per_month = [0] * months
    for index in history.signup_months(random.Random(42), 2000, months):
        per_month[index] += 1
    assert sum(per_month[10:14]) > 2 * sum(
        per_month[:4]
    )  # the middle is much faster than the start
    assert sum(per_month[10:14]) > 2 * sum(per_month[-4:])  # and it levels off at the end


def test_starter_churns_more_than_enterprise_and_systems_only_grow() -> None:
    orgs = _history(count=1500)
    churned = {"starter": [0, 0], "enterprise": [0, 0]}
    for org in orgs:
        plan = org.months[0].plan
        if plan in churned:
            churned[plan][0] += any(m.churn_day for m in org.months)
            churned[plan][1] += 1
    starter, enterprise = (churned[p][0] / churned[p][1] for p in ("starter", "enterprise"))
    assert starter > 2 * enterprise
    for org in orgs[:200]:
        counts = [m.systems for m in org.months]
        assert counts == sorted(counts)
    assert any(m.plan and m.plan != org.months[0].plan for org in orgs for m in org.months[1:])
