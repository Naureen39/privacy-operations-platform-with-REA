"""Prices a month of usage. Pure functions, no database."""

import calendar
from dataclasses import dataclass
from datetime import date

from app.db.enums import InvoiceLineKind


@dataclass(frozen=True)
class PlanTerms:
    code: str
    monthly_fee_cents: int
    included_systems: int
    included_requests: int
    extra_system_cents: int
    extra_request_cents: int


@dataclass(frozen=True)
class LineSpec:
    kind: InvoiceLineKind
    description: str
    quantity: int
    unit_cents: int

    @property
    def amount_cents(self) -> int:
        return self.quantity * self.unit_cents


def price_invoice(
    terms: PlanTerms, base_fee_cents: int, systems: int, requests: int, label: str
) -> list[LineSpec]:
    """The base fee of the subscription, plus systems and requests beyond what the plan includes.
    A plan with no price for extras (Starter) bills nothing for them; the usage report flags the
    overage so the customer can move up."""
    lines = [
        LineSpec(
            InvoiceLineKind.BASE, f"{terms.code.capitalize()} plan, {label}", 1, base_fee_cents
        )
    ]
    extra_systems = max(0, systems - terms.included_systems)
    if extra_systems and terms.extra_system_cents:
        lines.append(
            LineSpec(
                InvoiceLineKind.EXTRA_SYSTEMS,
                f"{extra_systems} systems beyond the {terms.included_systems} included",
                extra_systems,
                terms.extra_system_cents,
            )
        )
    extra_requests = max(0, requests - terms.included_requests)
    if extra_requests and terms.extra_request_cents:
        lines.append(
            LineSpec(
                InvoiceLineKind.EXTRA_REQUESTS,
                f"{extra_requests} requests beyond the {terms.included_requests} included",
                extra_requests,
                terms.extra_request_cents,
            )
        )
    return lines


def total_cents(lines: list[LineSpec]) -> int:
    return sum(line.amount_cents for line in lines)


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """First and last day of a calendar month."""
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def parse_month(value: str) -> tuple[date, date]:
    year, month = value.split("-")
    return month_bounds(int(year), int(month))


def invoice_number(period_start: date, sequence: int) -> str:
    return f"INV-{period_start:%Y%m}-{sequence:04d}"


def previous_month(day: date) -> tuple[date, date]:
    first = day.replace(day=1)
    end = date.fromordinal(first.toordinal() - 1)
    return end.replace(day=1), end
