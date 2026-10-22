"""Reading a privacy notice: its sections, the lists the rules compare, retention periods and the
claims that evidence can contradict."""

import re
from dataclasses import dataclass

from app.fusion.facts import PolicyFacts, Ref
from app.knowledge.chunking import markdown_blocks

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "eighteen": 18,
    "twenty": 20, "thirty": 30, "thirty six": 36, "forty": 40, "fifty": 50, "sixty": 60,
    "twenty four": 24, "twenty-four": 24, "thirty-six": 36, "twenty five": 25,
}  # fmt: skip
_NUMBER = "|".join(sorted((re.escape(w) for w in NUMBER_WORDS), key=len, reverse=True))
_PERIOD = re.compile(rf"\b(\d+|{_NUMBER})[ -]+(year|month)s?\b", re.IGNORECASE)
_OPEN_ENDED = re.compile(r"\b(plus|until|for the duration|as long as|while)\b", re.IGNORECASE)

_SHARE_SECTION = re.compile(r"who we share", re.IGNORECASE)
_COLLECT_SECTION = re.compile(r"data we collect|information we collect", re.IGNORECASE)
_RETENTION_SECTION = re.compile(r"how long|retention|keep it", re.IGNORECASE)
_VENDOR_BULLET = re.compile(
    r"^[-*]\s*(?P<vendor>[^()]+?)\s*(?:\((?P<cc>[A-Za-z]{2})\))?\s*:\s*(?P<purpose>.+)$"
)

_EXCLUSIVE_SHARING = re.compile(
    r"\b(do not|don't|never|will not)\s+(sell\s+or\s+)?share\b[^.]*"
    r"\b(anyone|any third part(?:y|ies)|third part(?:y|ies)|other than|except|outside)\b",
    re.IGNORECASE,
)
_NEGATIVE_STORAGE = [
    re.compile(r"\bnever store\s+(?:(?:an|any|the|a)\s+)?(?P<what>[^.,;]+)", re.IGNORECASE),
    re.compile(
        r"\bdo(?:es)? not (?:store|keep|retain)\s+(?:(?:an|any|the|a)\s+)?(?P<what>[^.,;]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?P<what>[^.,;]+?)\s+(?:is|are)\s+not\s+(?:stored|kept|retained|saved|recorded)\b",
        re.IGNORECASE,
    ),
]
_CONSENT_PROMISE = re.compile(
    r"(no box is ticked|not (?:be )?(?:pre-?ticked|pre-?selected|ticked for you)|"
    r"active opt[ -]?in|pre-?ticked boxes are not used|unticked)",
    re.IGNORECASE,
)


def parse_policy(text: str, ref: Ref) -> PolicyFacts:
    _, blocks = markdown_blocks(text)
    sections: dict[str, list[str]] = {}
    for block in blocks:
        sections.setdefault(block.heading or "", []).append(block.text)
    collected: list[str] = []
    shared: list[tuple[str, str | None, str]] = []
    retention: list[str] = []
    for heading, paragraphs in sections.items():
        for paragraph in paragraphs:
            lines = [ln.strip() for ln in paragraph.splitlines()]
            if _COLLECT_SECTION.search(heading):
                collected += [ln.lstrip("-* ").strip() for ln in lines if ln.startswith(("-", "*"))]
            if _SHARE_SECTION.search(heading):
                for line in lines:
                    match = _VENDOR_BULLET.match(line)
                    if match:
                        shared.append(
                            (
                                match["vendor"].strip(),
                                (match["cc"] or "").upper() or None,
                                match["purpose"].strip(),
                            )
                        )
            if _RETENTION_SECTION.search(heading):
                retention.append(paragraph)
    return PolicyFacts(sections, collected, shared, " ".join(retention), ref)


def retention_months(text: str) -> list[int]:
    """Every fixed period in months. A period tied to something open ended ("employment plus 6
    years", "until you unsubscribe") is not a limit that can be compared, so it is skipped."""
    periods: list[int] = []
    for sentence in re.split(r"(?<=[.;])\s+", text):
        if _OPEN_ENDED.search(sentence) and not re.search(
            r"\bfor\s+(?:\d+|\w+)\s+(?:year|month)", sentence, re.I
        ):
            continue
        for match in _PERIOD.finditer(sentence):
            raw, unit = match.group(1).lower(), match.group(2).lower()
            value = int(raw) if raw.isdigit() else NUMBER_WORDS.get(raw.replace("-", " "), 0)
            if value:
                periods.append(value * 12 if unit == "year" else value)
    return periods


def has_exclusive_sharing_claim(sentence: str) -> bool:
    return bool(_EXCLUSIVE_SHARING.search(sentence))


def negative_storage_subject(sentence: str) -> str | None:
    """'we never store a full IP address' -> 'full IP address'."""
    for pattern in _NEGATIVE_STORAGE:
        match = pattern.search(sentence)
        if match:
            subject = re.sub(r"\b(after|before|once|when|if)\b.*$", "", match["what"], flags=re.I)
            return subject.strip(" ,.;") or None
    return None


def promises_active_consent(sentence: str) -> bool:
    return bool(_CONSENT_PROMISE.search(sentence))


def months_between(earlier: str, as_of_year: int, as_of_month: int) -> int:
    """Whole months from 'YYYY-MM' to the given month."""
    year, month = (int(part) for part in earlier.split("-"))
    return (as_of_year - year) * 12 + (as_of_month - month)


def stem(word: str) -> str:
    word = word.lower()
    for suffix in ("ies", "es", "s"):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


@dataclass(frozen=True)
class Claim:
    section: str
    sentence: str
    kind: str  # exclusive_sharing | negative_storage | active_consent
    subject: str | None = None


def extract_claims(policy: PolicyFacts) -> list[Claim]:
    claims: list[Claim] = []
    for section, sentence in policy.sentences():
        if has_exclusive_sharing_claim(sentence):
            claims.append(Claim(section, sentence, "exclusive_sharing"))
        subject = negative_storage_subject(sentence)
        if subject:
            claims.append(Claim(section, sentence, "negative_storage", subject))
        if promises_active_consent(sentence):
            claims.append(Claim(section, sentence, "active_consent"))
    return claims
