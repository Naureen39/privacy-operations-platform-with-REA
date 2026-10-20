"""Value sources for form fields and database columns of the estate systems.

A source string is one of:
    person.<column>            a column of synthetic_people.csv
    person.email_if:<flag>     the e-mail address when the person has the flag, else NULL
    gen.<name>                 a generated value (see GENERATORS)
    const.<text>               a literal
    auto                       auto increment primary key (handled by the store)

Every generator is deterministic: it derives its randomness from the supplied generator.
"""

import hashlib
import random
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from common import REFERENCE_DATE

Person = dict[str, str]
REFERENCE = datetime.fromisoformat(REFERENCE_DATE + "T00:00:00")

SUBJECTS = [
    "Where is my order",
    "Wrong item delivered",
    "Refund not received",
    "Cannot log in to my account",
    "Change my delivery address",
    "Question about an invoice",
    "Product arrived damaged",
    "Cancel my subscription",
    "Update my contact details",
    "Delivery date question",
]
CHAT_LINES = [
    "Hello, I placed an order last week and have not received an update.",
    "Thanks for getting back to me, that works for me.",
    "Could you confirm the delivery date please?",
    "The package arrived but one item is missing.",
    "I would like to change the address on my account.",
    "Please cancel the order if it has not shipped yet.",
    "I tried the reset link but it has expired.",
    "Great, thank you for the quick help.",
]
JOB_TITLES = [
    "Head of Operations", "Procurement Manager", "Store Owner", "Finance Director",
    "IT Manager", "Marketing Lead", "Office Manager", "Operations Analyst",
]  # fmt: skip
COMPANY_PREFIX = [
    "Harbour",
    "Maple",
    "Summit",
    "Cedar",
    "Bluebird",
    "Ironwood",
    "Lantern",
    "Willow",
]
COMPANY_SUFFIX = [
    "Trading Ltd",
    "Supplies GmbH",
    "Retail BV",
    "Partners SARL",
    "Group Ltd",
    "Stores Ltd",
]
LEAD_SOURCES = ["web_form", "trade_show", "referral", "newsletter", "partner"]
STAGES = ["prospecting", "qualification", "proposal", "negotiation", "closed_won", "closed_lost"]
SYMPTOMS = [
    "persistent cough", "lower back pain", "headaches", "skin rash", "fatigue",
    "joint stiffness", "sleep problems", "dizziness",
]  # fmt: skip
REASONS = [
    "routine check-up", "follow-up appointment", "vaccination", "blood pressure review",
    "physiotherapy assessment", "allergy consultation", "test results discussion",
]  # fmt: skip
DIAGNOSES = [
    "seasonal allergy", "mild hypertension", "lumbar strain", "contact dermatitis",
    "vitamin D deficiency", "tension headache", "no abnormality detected",
]  # fmt: skip
DOCTORS = ["Dr. A. Okafor", "Dr. L. Brandt", "Dr. M. Duval", "Dr. S. Haddad", "Dr. P. Visser"]
INSURERS = ["Evergreen Health Cover", "Northstar Mutual", "Clearwater Insurance", "Unity Care Fund"]
DEPARTMENTS = [
    "Store Operations",
    "Logistics",
    "Finance",
    "Customer Care",
    "Clinic Administration",
    "IT",
]
MANAGERS = ["R. Fontaine", "T. Albrecht", "K. Moran", "J. de Vries", "H. Whitlock"]
NATIONALITIES = ["Irish", "British", "German", "French", "Dutch", "Polish", "Spanish"]
ETHNIC_ORIGINS = [
    "White", "Asian", "Black or African", "Mixed or multiple", "Other", "Prefer not to say",
]  # fmt: skip
DISABILITY = [
    "none",
    "none",
    "none",
    "none",
    "none",
    "prefer not to say",
    "mobility impairment",
    "hearing impairment",
]
USER_AGENTS = [
    ("Windows 11", "Chrome 124", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    ("macOS 14", "Safari 17", "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"),
    ("Android 14", "Chrome Mobile 124", "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"),
    ("iOS 17", "Safari Mobile 17", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"),
    ("Ubuntu 22.04", "Firefox 125", "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0"),
]  # fmt: skip
PAGES = [
    "/",
    "/shop/",
    "/shop/product/linen-shirt/",
    "/cart/",
    "/checkout/",
    "/about/",
    "/contact/",
    "/blog/spring-sale/",
]
REFERRERS = [
    "",
    "https://search.example/?q=northbridge",
    "https://social.example/post/812",
    "https://newsletter.northbridge.example/",
]
CITY_COORDS = {  # rough centre points, used with a small jitter
    "IE": (53.35, -6.26), "GB": (51.51, -0.13), "DE": (52.52, 13.40), "FR": (48.86, 2.35), "NL": (52.37, 4.90),
}  # fmt: skip


def _hex(*parts: object, length: int = 16) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:length]


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


def date_between(rng: random.Random, days_back_max: int, days_back_min: int = 0) -> datetime:
    days = rng.randint(days_back_min, days_back_max)
    return REFERENCE - timedelta(days=days, seconds=rng.randint(0, 86399))


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def sample_password(person: Person) -> str:
    return f"Sample-{_hex(person['person_id'], 'pw', length=10)}"


def password_hash(person: Person) -> str:
    return (
        "$2y$10$"
        + _hex(person["person_id"], "pwhash", length=40)
        + _hex(person["person_id"], "salt", length=13)
    )


def coords(person: Person, rng: random.Random) -> tuple[float, float]:
    lat, lon = CITY_COORDS[person["country"]]
    return round(lat + rng.uniform(-0.2, 0.2), 5), round(lon + rng.uniform(-0.3, 0.3), 5)


GENERATORS: dict[str, Callable[[Person, random.Random], Any]] = {
    "order_total": lambda p, r: round(r.uniform(9, 380), 2),
    "currency": lambda p, r: "EUR",
    "order_status": lambda p, r: r.choice(["completed", "completed", "processing", "refunded"]),
    "recent_ts": lambda p, r: iso(date_between(r, 730)),
    "old_ts": lambda p, r: iso(date_between(r, 1460)),
    "last_30_days_ts": lambda p, r: iso(date_between(r, 30)),
    "sample_password": lambda p, r: sample_password(p),
    "password_hash": lambda p, r: password_hash(p),
    "visitor_id": lambda p, r: _hex(p["person_id"], "visitor"),
    "device_id": lambda p, r: _hex(p["person_id"], "device", length=12),
    "ticket_subject": lambda p, r: r.choice(SUBJECTS),
    "chat_line": lambda p, r: r.choice(CHAT_LINES),
    "ticket_status": lambda p, r: r.choice(["resolved", "resolved", "open", "closed"]),
    "company": lambda p, r: f"{r.choice(COMPANY_PREFIX)} {r.choice(COMPANY_SUFFIX)}",
    "job_title": lambda p, r: r.choice(JOB_TITLES),
    "lead_source": lambda p, r: r.choice(LEAD_SOURCES),
    "crm_note": lambda p, r: r.choice(
        [
            "Interested in bulk pricing.",
            "Asked for a callback next quarter.",
            "Met at the spring trade show.",
            "",
        ]
    ),
    "stage": lambda p, r: r.choice(STAGES),
    "amount": lambda p, r: round(r.uniform(500, 25000), 2),
    "seniority": lambda p, r: r.choice(["junior", "mid", "senior", "executive"]),
    "company_size": lambda p, r: r.choice(["1-10", "11-50", "51-200", "201-1000"]),
    "reason": lambda p, r: r.choice(REASONS),
    "symptoms": lambda p, r: r.choice(SYMPTOMS),
    "diagnosis": lambda p, r: r.choice(DIAGNOSES),
    "doctor": lambda p, r: r.choice(DOCTORS),
    "insurer": lambda p, r: r.choice(INSURERS),
    "insurance_number": lambda p, r: "INS-" + _hex(p["person_id"], "ins", length=9).upper(),
    "appointment_ts": lambda p, r: iso(date_between(r, 400)),
    "appointment_status": lambda p, r: r.choice(["completed", "completed", "booked", "cancelled"]),
    "interests": lambda p, r: ",".join(
        sorted(r.sample(["new-arrivals", "sale", "events", "home", "kids"], r.randint(1, 3)))
    ),
    "department": lambda p, r: r.choice(DEPARTMENTS),
    "manager": lambda p, r: r.choice(MANAGERS),
    "hours": lambda p, r: round(r.choice([6, 7, 7.5, 8, 8, 8.5, 9]), 1),
    "work_date": lambda p, r: date_between(r, 90).strftime("%Y-%m-%d"),
    "clock_event": lambda p, r: r.choice(["clock_in", "clock_out"]),
    "lat": lambda p, r: coords(p, r)[0],
    "lon": lambda p, r: coords(p, r)[1],
    "nationality": lambda p, r: r.choice(NATIONALITIES),
    "disability": lambda p, r: r.choice(DISABILITY),
    "union_member": lambda p, r: r.choice(["yes", "no", "no", "no"]),
    "ethnic_origin": lambda p, r: r.choice(ETHNIC_ORIGINS),
    "emergency_name": lambda p, r: f"{r.choice(['Sam', 'Alex', 'Jordan', 'Robin', 'Casey'])} {p['last_name']}",
    "emergency_phone": lambda p, r: f"+44 7700 900{r.randint(100, 999)}",
    "os": lambda p, r: r.choice(USER_AGENTS)[0],
    "browser": lambda p, r: r.choice(USER_AGENTS)[1],
    "user_agent": lambda p, r: USER_AGENTS[
        int(_hex(p["person_id"], "ua", length=4), 16) % len(USER_AGENTS)
    ][2],
    "page": lambda p, r: r.choice(PAGES),
    "referrer": lambda p, r: r.choice(REFERRERS),
    "actions": lambda p, r: r.randint(1, 12),
    "one": lambda p, r: 1,
    "zero": lambda p, r: 0,
    "true_text": lambda p, r: "yes",
    "tracking_hash": lambda p, r: sha256_hex(p["email"]),
    "phone_hash": lambda p, r: sha256_hex(p["phone"]),
}


def resolve(source: str, person: Person, rng: random.Random) -> Any:
    if source.startswith("person.email_if:"):
        flag = source.split(":", 1)[1]
        return person["email"] if person.get(flag) == "1" else None
    if source.startswith("person."):
        return person[source.split(".", 1)[1]]
    if source.startswith("gen."):
        return GENERATORS[source.split(".", 1)[1]](person, rng)
    if source.startswith("const."):
        return source.split(".", 1)[1]
    raise ValueError(f"unknown source {source!r}")
