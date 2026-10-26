"""Identifier hashing, deadlines, the snapshot search and the response letter (no application)."""

import sqlite3
import uuid
from datetime import date
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.dsar import deadline
from app.dsar.hashing import (
    InvalidIdentifierError,
    matches,
    normalise,
    subject_hash,
    subject_key,
)
from app.dsar.search import match_expression, open_snapshot, quote, schema_of

ENCRYPTION_KEY = "a" * 43 + "="  # 32 bytes in base64 (all 0x69... decoded below)


def settings(**kw: object) -> Settings:
    import base64

    return Settings(
        jwt_secret=SecretStr("j" * 40),
        evidence_encryption_key=SecretStr(base64.b64encode(b"k" * 32).decode()),
        **kw,  # type: ignore[arg-type]
    )


ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")


# -- hashing -------------------------------------------------------------------------------------


def test_the_same_person_gets_the_same_hash_however_the_address_is_typed() -> None:
    key = subject_key(settings())
    a = subject_hash(key, ORG, "email", "Gabriel.MacMorrow156@webpost.example")
    b = subject_hash(key, ORG, "email", "  gabriel.macmorrow156@WEBPOST.example ")
    assert a == b and len(a) == 64
    assert "gabriel" not in a and subject_hash(key, ORG, "email", "other@webpost.example") != a


def test_hashes_depend_on_the_organisation_the_type_and_the_key() -> None:
    key = subject_key(settings())
    base = subject_hash(key, ORG, "email", "a@b.example")
    assert subject_hash(key, uuid.uuid4(), "email", "a@b.example") != base
    assert subject_hash(key, ORG, "phone", "1234567") != subject_hash(key, ORG, "phone", "01234567")
    other = subject_key(settings(subject_hash_key=SecretStr("another secret")))
    assert other != key and subject_hash(other, ORG, "email", "a@b.example") != base


def test_the_key_is_derived_from_the_encryption_key_unless_one_is_set() -> None:
    assert subject_key(settings()) == subject_key(settings())
    assert len(subject_key(settings())) == 32
    explicit = settings(subject_hash_key=SecretStr("x" * 32))
    assert subject_key(explicit) != subject_key(settings())


def test_matches_compares_in_constant_time_and_rejects_others() -> None:
    key = subject_key(settings())
    stored = subject_hash(key, ORG, "email", "a@b.example")
    assert matches(key, ORG, "email", "A@B.example", stored)
    assert not matches(key, ORG, "email", "c@d.example", stored)


@pytest.mark.parametrize(
    "value", ["", "not an email", "a@b", "a b@c.example", "@x.example", "x" * 300 + "@y.example"]
)
def test_invalid_emails_are_refused_without_echoing_them(value: str) -> None:
    with pytest.raises(InvalidIdentifierError) as info:
        normalise("email", value)
    assert value.strip() == "" or value not in str(info.value)


@pytest.mark.parametrize(
    ("raw", "digits"),
    [
        ("+44 20 7946 0958", "442079460958"),
        ("(555) 123-4567", "5551234567"),
        ("020.7946.0958", "02079460958"),
    ],
)
def test_phone_numbers_are_reduced_to_digits(raw: str, digits: str) -> None:
    assert normalise("phone", raw) == digits


@pytest.mark.parametrize("raw", ["12345", "1" * 16, "abc"])
def test_implausible_phone_numbers_are_refused(raw: str) -> None:
    with pytest.raises(InvalidIdentifierError):
        normalise("phone", raw)


def test_unknown_identifier_types_are_refused() -> None:
    with pytest.raises(InvalidIdentifierError):
        normalise("passport", "X123")


# -- deadlines -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("received", "expected"),
    [
        (date(2026, 10, 1), date(2026, 11, 2)),  # 1 November is a Sunday: the next working day
        (date(2026, 1, 15), date(2026, 2, 16)),  # 15 February is a Sunday
        (date(2026, 1, 31), date(2026, 3, 2)),  # 28 February is a Saturday
        (date(2024, 1, 31), date(2024, 2, 29)),  # leap year: the last day of February
        (date(2026, 3, 31), date(2026, 4, 30)),  # April has 30 days
        (date(2026, 12, 15), date(2027, 1, 15)),  # across the year end (a Friday)
        (date(2026, 8, 31), date(2026, 9, 30)),
        (date(2026, 7, 3), date(2026, 8, 3)),  # 3 August is a Monday
    ],
)
def test_the_first_deadline_is_one_month_on_a_working_day(received: date, expected: date) -> None:
    assert deadline.initial_deadline(received) == expected
    assert expected.weekday() < 5


@pytest.mark.parametrize(
    ("received", "months", "expected"),
    [
        (date(2026, 10, 1), 1, date(2026, 12, 1)),
        (date(2026, 10, 1), 2, date(2027, 1, 1)),
        (date(2026, 11, 30), 2, date(2027, 3, 1)),  # 28 February 2027 is a Sunday
        (date(2026, 11, 30), 1, date(2027, 2, 1)),  # 30 January 2027 is a Saturday
        (date(2025, 11, 30), 2, date(2026, 3, 2)),  # 28 February 2026 is a Saturday
    ],
)
def test_an_extension_adds_one_or_two_further_months(
    received: date, months: int, expected: date
) -> None:
    assert deadline.extended_deadline(received, months) == expected


@pytest.mark.parametrize("months", [0, 3, -1])
def test_an_extension_beyond_two_months_is_refused(months: int) -> None:
    with pytest.raises(ValueError):
        deadline.extended_deadline(date(2026, 10, 1), months)


def test_add_months_and_working_days() -> None:
    assert deadline.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert deadline.add_months(date(2026, 1, 31), 13) == date(2027, 2, 28)
    assert deadline.add_months(date(2026, 5, 15), -2) == date(2026, 3, 15)
    assert deadline.next_working_day(date(2026, 10, 3)) == date(2026, 10, 5)
    assert deadline.next_working_day(date(2026, 10, 5)) == date(2026, 10, 5)


def test_extension_rules() -> None:
    received = date(2026, 9, 1)  # first deadline 1 October
    assert deadline.can_extend(received, date(2026, 10, 1), False) == (True, "")
    ok, why = deadline.can_extend(received, date(2026, 10, 2), False)
    assert not ok and "first month" in why
    ok, why = deadline.can_extend(received, date(2026, 9, 10), True)
    assert not ok and "already" in why


def test_deadline_status_levels() -> None:
    deadline_day = date(2026, 10, 20)
    cases = {
        date(2026, 10, 21): ("overdue", True, -1),
        date(2026, 10, 20): ("due_today", False, 0),
        date(2026, 10, 15): ("due_soon", False, 5),
        date(2026, 10, 13): ("due_soon", False, 7),
        date(2026, 10, 12): ("none", False, 8),
    }
    for today, (level, overdue, days) in cases.items():
        s = deadline.deadline_status(deadline_day, today, closed=False)
        assert (s.level, s.overdue, s.days_remaining) == (level, overdue, days), today
    closed = deadline.deadline_status(deadline_day, date(2026, 12, 1), closed=True)
    assert closed.level == "none" and closed.overdue is False


# -- snapshot search -----------------------------------------------------------------------------


def snapshot(tmp_path: Path) -> bytes:
    path = tmp_path / "s.sqlite"
    db = sqlite3.connect(path)
    db.execute(
        'CREATE TABLE "weird ""table""" (id INTEGER PRIMARY KEY, "mail col" TEXT, phone TEXT, blob BLOB)'
    )
    db.executemany(
        (
            'INSERT INTO "weird ""table""" (mail_col_placeholder) VALUES (?)'
            if False
            else 'INSERT INTO "weird ""table""" ("mail col", phone, blob) VALUES (?, ?, ?)'
        ),
        [
            ("Jane@Example.com ", "+44 (20) 7946-0958", b"\x00\x01"),
            ("jane@example.com", "020 7946 0958", None),
            ("other@example.com", "555", None),
        ],
    )
    db.commit()
    db.close()
    return path.read_bytes()


def test_the_snapshot_is_opened_from_memory_and_cannot_be_changed(tmp_path: Path) -> None:
    connection = open_snapshot(snapshot(tmp_path))
    assert list(schema_of(connection)) == ['weird "table"']
    assert schema_of(connection)['weird "table"'] == {"id", "mail col", "phone", "blob"}
    with pytest.raises(sqlite3.OperationalError):
        connection.execute('DELETE FROM "weird ""table"""')
    connection.close()


def test_matching_ignores_case_and_spaces_and_binds_the_value(tmp_path: Path) -> None:
    connection = open_snapshot(snapshot(tmp_path))
    table = quote('weird "table"')
    email = match_expression("email", "mail col")
    assert (
        connection.execute(
            f"SELECT count(*) FROM {table} WHERE {email} = ?", ["jane@example.com"]
        ).fetchone()[0]
        == 2
    )
    # a value that looks like SQL is only ever a value
    evil = "x' OR '1'='1"
    assert (
        connection.execute(f"SELECT count(*) FROM {table} WHERE {email} = ?", [evil]).fetchone()[0]
        == 0
    )
    phone = match_expression("phone", "phone")
    assert (
        connection.execute(
            f"SELECT count(*) FROM {table} WHERE {phone} = ?", ["02079460958"]
        ).fetchone()[0]
        == 1
    )
    assert (
        connection.execute(
            f"SELECT count(*) FROM {table} WHERE {phone} = ?", ["442079460958"]
        ).fetchone()[0]
        == 1  # only the number written with its country code
    )
    connection.close()


def test_names_are_quoted_so_they_cannot_break_out() -> None:
    assert (
        quote("a") == '"a"'
        and quote('a"b') == '"a""b"'
        and quote("a; DROP TABLE x") == '"a; DROP TABLE x"'
    )
