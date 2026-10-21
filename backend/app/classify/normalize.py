"""Turning field, column and parameter names into comparable words."""

import re

# Abbreviations common in form fields, database columns and tracking parameters.
ABBREVIATIONS = {
    "dob": "date of birth",
    "bday": "birthday",
    "tel": "telephone",
    "ph": "phone",
    "addr": "address",
    "eml": "email",
    "em": "email",
    "fname": "first name",
    "lname": "last name",
    "zip": "postal code",
    "pwd": "password",
    "pass": "password",
    "ip": "ip address",
    "ua": "user agent",
    "cc": "card",
    "num": "number",
    "nr": "number",
    "msg": "message",
    "usr": "user",
    "uid": "user id",
    "ssn": "social security number",
    "ts": "timestamp",
    "lat": "latitude",
    "lon": "longitude",
    "lng": "longitude",
}

# HTML `autocomplete` tokens and what they ask for, in words.
AUTOCOMPLETE_WORDS = {
    "name": "full name",
    "given-name": "first name",
    "additional-name": "middle name",
    "family-name": "last name",
    "email": "email address",
    "tel": "telephone number",
    "tel-national": "telephone number",
    "bday": "date of birth",
    "bday-day": "date of birth",
    "sex": "gender",
    "street-address": "street address",
    "address-line1": "street address",
    "address-line2": "street address",
    "address-level1": "state or region",
    "address-level2": "city",
    "postal-code": "postal code",
    "country": "country",
    "country-name": "country",
    "organization": "company",
    "organization-title": "job title",
    "username": "username",
    "new-password": "password",
    "current-password": "password",
    "cc-number": "payment card number",
    "cc-exp": "payment card expiry",
    "cc-csc": "payment card security code",
    "cc-name": "name on payment card",
    "one-time-code": "one time code",
}

WORD = re.compile(r"[a-z]+|\d+")


def split_identifier(name: str) -> list[str]:
    """`billingEmail`, `billing_email`, `billing[email]` and `Billing-Email` all give [billing, email]."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    tokens = WORD.findall(spaced.lower())
    return [t for t in tokens if not t.isdigit()]


def expand(tokens: list[str]) -> list[str]:
    words: list[str] = []
    for token in tokens:
        words.extend(ABBREVIATIONS.get(token, token).split())
    return words


def phrase(name: str) -> str:
    return " ".join(split_identifier(name))


def strip_prefixes(tokens: list[str], prefixes: tuple[str, ...]) -> list[str]:
    """Drop leading qualifiers (billing, customer, work...), keeping at least one token."""
    core = list(tokens)
    while len(core) > 1 and core[0] in prefixes:
        core = core[1:]
    return core


def contains_sequence(haystack: list[str], needle: list[str]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[i : i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1)
    )
