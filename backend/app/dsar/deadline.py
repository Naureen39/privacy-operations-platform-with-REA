"""Article 12(3) deadlines: one month from receipt, extendable by up to two further months for
complex or numerous requests. A deadline that falls on a weekend moves to the next working day
(Regulation 1182/71). Public holidays differ by country and are not modelled."""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

MAX_EXTENSION_MONTHS = 2
OPEN_STATES_EXCLUDED = ("responded", "closed", "rejected")


def add_months(day: date, months: int) -> date:
    """The corresponding calendar date, or the last day of the month when there is none."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def next_working_day(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def initial_deadline(received: date) -> date:
    return next_working_day(add_months(received, 1))


def extended_deadline(received: date, extension_months: int) -> date:
    if not 1 <= extension_months <= MAX_EXTENSION_MONTHS:
        raise ValueError("An extension is one or two further months")
    return next_working_day(add_months(received, 1 + extension_months))


@dataclass(frozen=True)
class DeadlineStatus:
    days_remaining: int
    overdue: bool
    level: str  # none | due_soon | due_today | overdue


def deadline_status(
    deadline: date, today: date, closed: bool, reminder_days: int = 7
) -> DeadlineStatus:
    days = (deadline - today).days
    if closed:
        return DeadlineStatus(days, False, "none")
    if days < 0:
        return DeadlineStatus(days, True, "overdue")
    if days == 0:
        return DeadlineStatus(days, False, "due_today")
    if days <= reminder_days:
        return DeadlineStatus(days, False, "due_soon")
    return DeadlineStatus(days, False, "none")


def can_extend(received: date, today: date, already_extended: bool) -> tuple[bool, str]:
    if already_extended:
        return False, "The deadline has already been extended once"
    if today > initial_deadline(received):
        return False, "An extension must be told to the person within the first month"
    return True, ""
