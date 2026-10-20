"""Value pattern detection and masking.

Sample values from evidence are inspected only inside the discovery step to decide which
pattern class a data element has (e-mail, IP address, payment card and so on). Only the
class and a shape-preserving mask are kept; the values themselves are never stored or sent on.
"""

import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
IPV4 = re.compile(r"^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)$")
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")
URL = re.compile(r"^https?://", re.IGNORECASE)
IBAN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$")
PHONE = re.compile(r"^\+?[\d\s().\-]{7,25}(?:x\d{1,6})?$")
HEX_TOKEN = re.compile(r"^(?=.*[a-fA-F])[0-9a-fA-F]{16,}$")
PASSWORD_HASH = re.compile(r"^(\$2[abxy]\$|\$argon2|\$pbkdf2|\$scrypt)")
COORDINATE = re.compile(r"^-?\d{1,3}\.\d{3,}$")


def luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2 == 1:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    return total % 10 == 0


def iban_valid(value: str) -> bool:
    rearranged = value[4:] + value[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def detect_pattern(value: Any) -> str | None:
    """Classify one value. Returns None when no pattern applies."""
    if value is None or isinstance(value, bool):
        return "boolean" if isinstance(value, bool) else None
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    text = str(value).strip()
    if not text:
        return None
    if EMAIL.match(text):
        return "email"
    if PASSWORD_HASH.match(text):
        return "password_hash"
    if URL.match(text):
        return "url"
    if UUID.match(text):
        return "uuid"
    if IPV4.match(text):
        return "ip_address"
    compact = text.replace(" ", "").upper()
    if IBAN.match(compact) and iban_valid(compact):
        return "iban"
    digits = re.sub(r"[ -]", "", text)
    if digits.isdigit() and 13 <= len(digits) <= 19 and luhn_valid(digits):
        return "payment_card"
    if DATETIME.match(text):
        return "datetime"
    if DATE.match(text):
        return "date"
    if re.fullmatch(r"[0-9a-fA-F]{64}", text):
        return "sha256_hash"
    if HEX_TOKEN.match(text):
        return "hex_token"
    if COORDINATE.match(text):
        return "coordinate"
    if PHONE.match(text) and 7 <= sum(c.isdigit() for c in text) <= 15 and not DATE.match(text):
        return "phone"
    if re.fullmatch(r"-?\d+", text):
        return "integer"
    if re.fullmatch(r"-?\d+\.\d+", text):
        return "number"
    if text.lower() in {"true", "false"}:
        return "boolean"
    if len(text) >= 40 or len(text.split()) >= 7:
        return "free_text"
    return None


def dominant_pattern(values: Iterable[Any], minimum_share: float = 0.6) -> tuple[str | None, int]:
    """The pattern most samples share (at least `minimum_share` of the non-empty ones)."""
    counts: Counter[str] = Counter()
    total = 0
    for value in values:
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        total += 1
        pattern = detect_pattern(value)
        if pattern:
            counts[pattern] += 1
    if not total or not counts:
        return None, total
    pattern, count = counts.most_common(1)[0]
    return (pattern, total) if count / total >= minimum_share else (None, total)


def mask_shape(value: Any, limit: int = 40) -> str:
    """Replace letters with 'x' and digits with '9', keeping punctuation and length."""
    text = str(value)
    masked = re.sub(r"[A-Za-z]", "x", re.sub(r"\d", "9", text))
    return masked[:limit] + ("..." if len(masked) > limit else "")


def masked_samples(values: Iterable[Any], count: int = 3) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        shape = mask_shape(value)
        if shape not in seen:
            seen.append(shape)
        if len(seen) >= count:
            break
    return seen
