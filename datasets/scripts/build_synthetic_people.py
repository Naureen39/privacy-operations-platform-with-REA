"""Generate 2,000 synthetic people with a fixed seed.

    uv run python datasets/scripts/build_synthetic_people.py

Every value is generated. E-mail addresses use reserved ".example" domains, IP addresses come
from the 198.18.0.0/15 benchmarking range, and the national identifiers use a made-up format.
Names, phone numbers and IBANs come from Faker and are random: any resemblance to a real
person is coincidental. People are spread across the estate systems with realistic overlap.
"""

import csv
import sys
import unicodedata
from pathlib import Path

from faker import Faker

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS_DIR, SEED, has_banned_word, rng_for  # noqa: E402

PEOPLE_COUNT = 2000
# Faker occasionally draws a common name that is also a product name. Such draws are skipped,
# so that no generated value reads as a mention of a tool (see common.has_banned_word).
LOCALES = {
    "en_IE": "IE",
    "en_GB": "GB",
    "de_DE": "DE",
    "fr_FR": "FR",
    "nl_NL": "NL",
}
EMAIL_DOMAINS = [
    "mail.example",
    "inbox.example",
    "webpost.example",
    "postbox.example",
    "letter.example",
]
SYSTEM_FLAGS = [
    "in_web_shop",
    "in_web_analytics",
    "in_helpdesk",
    "in_crm",
    "in_clinic_portal",
    "in_newsletter",
    "in_staff_desktop",
    "in_hr_onboarding",
]
COLUMNS = [
    "person_id",
    "first_name",
    "last_name",
    "full_name",
    "email",
    "phone",
    "date_of_birth",
    "gender",
    "street_address",
    "city",
    "postal_code",
    "country",
    "iban",
    "national_id",
    "ip_address",
    "employee_id",
    *SYSTEM_FLAGS,
]


def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def memberships(person_index: int) -> dict[str, int]:
    r = rng_for("membership", person_index)
    employee = r.random() < 0.06
    shop = r.random() < (0.55 if not employee else 0.6)
    newsletter = r.random() < (0.55 if shop else 0.25)
    helpdesk = r.random() < (0.28 if shop else 0.06)
    crm = r.random() < (0.45 if newsletter else 0.25)
    clinic = r.random() < 0.15
    analytics = shop or newsletter or r.random() < 0.6
    return {
        "in_web_shop": int(shop),
        "in_web_analytics": int(analytics),
        "in_helpdesk": int(helpdesk),
        "in_crm": int(crm),
        "in_clinic_portal": int(clinic),
        "in_newsletter": int(newsletter),
        "in_staff_desktop": int(employee),
        "in_hr_onboarding": int(employee),
    }


def build_people(count: int = PEOPLE_COUNT) -> list[dict[str, object]]:
    Faker.seed(SEED)
    fake = Faker(list(LOCALES))
    people: list[dict[str, object]] = []
    employee_counter = 0
    for index in range(count):
        locale = list(LOCALES)[index % len(LOCALES)]
        gen = fake[locale]
        r = rng_for("person", index)
        first, last = gen.first_name(), gen.last_name()
        while has_banned_word(f"{first} {last}"):
            first, last = gen.first_name(), gen.last_name()
        street, city = gen.street_address(), gen.city()
        while has_banned_word(f"{street} {city}"):
            street, city = gen.street_address(), gen.city()
        flags = memberships(index)
        employee_id = ""
        if flags["in_hr_onboarding"]:
            employee_counter += 1
            employee_id = f"NB{employee_counter:04d}"
        dob = gen.date_of_birth(minimum_age=18, maximum_age=80)
        n = index  # unique host number inside 198.18.0.0/15
        ip = f"198.{18 + (n // 65024)}.{(n // 254) % 256}.{n % 254 + 1}"
        people.append(
            {
                "person_id": f"P{index + 1:05d}",
                "first_name": first,
                "last_name": last,
                "full_name": f"{first} {last}",
                "email": f"{ascii_fold(first)}.{ascii_fold(last)}{index + 1}@{r.choice(EMAIL_DOMAINS)}".replace(
                    " ", ""
                ),
                "phone": gen.phone_number(),
                "date_of_birth": dob.isoformat(),
                "gender": r.choice(["female", "male", "non-binary"]),
                "street_address": street.replace("\n", ", "),
                "city": city,
                "postal_code": gen.postcode(),
                "country": LOCALES[locale],
                "iban": gen.iban(),
                "national_id": f"NB-{LOCALES[locale]}-{r.randrange(10**8):08d}",
                "ip_address": ip,
                "employee_id": employee_id,
                **flags,
            }
        )
    return people


def write_csv(people: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(people)


def load_people(path: Path | None = None) -> list[dict[str, str]]:
    path = path or DATASETS_DIR / "people" / "synthetic_people.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    people = build_people()
    out = DATASETS_DIR / "people" / "synthetic_people.csv"
    write_csv(people, out)
    counts = {flag: sum(int(p[flag]) for p in people) for flag in SYSTEM_FLAGS}  # type: ignore[call-overload]
    print(f"wrote {out} ({len(people)} people)")
    for flag, total in counts.items():
        print(f"  {flag:<18} {total}")


if __name__ == "__main__":
    main()
