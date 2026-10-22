"""Screening: score a processing activity against the impact assessment criteria.

Each criterion is judged from the record, the discovered evidence and what an analyst has stated
about scale and purpose. A criterion is `met`, `not met`, or `unknown` when the evidence cannot
say (scale is the usual case). Two or more criteria met means an assessment is likely required;
criteria that are unknown are listed so a person can supply them.
"""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.classify.knowledge import DEFAULT_DIR
from app.fusion.facts import ElementFact, RecipientFact, Ref

CRITERIA_FILE = DEFAULT_DIR / "taxonomy" / "dpia_criteria.json"

# Data that is highly personal besides the Article 9 categories (see the criteria file).
SENSITIVE_CATEGORIES = frozenset({"criminal_data", "national_id", "bank_account"})
MONITORING_CATEGORIES = frozenset({"geolocation", "browsing_behavior"})
BIOMETRIC_CATEGORIES = frozenset({"biometric_data", "genetic_data"})
ENRICHMENT_CATEGORIES = frozenset({"enrichment", "data_broker"})
LARGE_SCALE_SUBJECTS = 1000  # data subjects; a round number, since the guidelines give none
LARGE_SCALE_COUNTRIES = 3

VULNERABLE_WORDS = re.compile(
    r"\b(patient|employee|staff|worker|child|children|minor|pupil|student|elderly|resident)s?\b",
    re.IGNORECASE,
)
KEYWORDS: dict[str, re.Pattern[str]] = {
    "evaluation_scoring": re.compile(
        r"(profiling|profiled|credit scor\w*|scoring|predict\w*|performance review|behaviou?ral (?:analysis|analytics))",
        re.IGNORECASE,
    ),
    "automated_decisions": re.compile(
        r"(automated (?:decision|approval|rejection)|automatic(?:ally)? (?:approv|reject|declin)\w*|auto[- ]?(?:approv|reject)\w*)",
        re.IGNORECASE,
    ),
    "systematic_monitoring": re.compile(
        r"(surveillance|cctv|video monitoring|monitoring of (?:staff|employees|visitors)|track(?:ing)? (?:the )?(?:location|movements))",
        re.IGNORECASE,
    ),
    "combining_datasets": re.compile(
        r"(enrich\w*|data matching|match(?:ed|ing)? (?:with|against)|added from|combin\w+ (?:with|data))",
        re.IGNORECASE,
    ),
    "innovative_technology": re.compile(
        r"(machine learning|artificial intelligence|facial recognition|biometric|internet of things|\biot\b)",
        re.IGNORECASE,
    ),
    "prevents_exercise_of_rights": re.compile(
        r"(eligibility (?:check|decision)|blacklist|denylist|access decision)", re.IGNORECASE
    ),
}
NEGATION = re.compile(r"\b(no|not|never|without|do not|does not|don't|neither)\b", re.IGNORECASE)
NUMBER_WORDS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
COUNTRIES = re.compile(
    r"\b(\d+|two|three|four|five|six|seven|eight|nine|ten)\s+countries\b", re.IGNORECASE
)


@dataclass(frozen=True)
class Criterion:
    id: str
    label: str
    description: str


@dataclass(frozen=True)
class CriteriaSet:
    version: int
    threshold: int
    rule: str
    criteria: tuple[Criterion, ...]


def load_criteria(path: Path = CRITERIA_FILE) -> CriteriaSet:
    data = json.loads(path.read_text(encoding="utf-8"))
    return CriteriaSet(
        version=int(data["version"]),
        threshold=int(data["threshold"]),
        rule=str(data["threshold_rule"]),
        criteria=tuple(Criterion(c["id"], c["label"], c["description"]) for c in data["criteria"]),
    )


@dataclass
class Scale:
    """What the evidence cannot show and an analyst states."""

    data_subjects_estimate: int | None = None
    countries: int | None = None
    flags: list[str] = field(default_factory=list)  # criteria an analyst asserts apply

    def as_dict(self) -> dict[str, Any]:
        return {
            "data_subjects_estimate": self.data_subjects_estimate,
            "countries": self.countries,
            "flags": sorted(set(self.flags)),
        }


@dataclass
class ScreeningInput:
    name: str
    description: str
    data_subjects: list[str]
    purposes: list[str]
    extra_text: list[str]  # sentences of the notice that describe purposes and handling
    elements: list[ElementFact]
    recipients: list[RecipientFact]
    special_categories: list[str]
    categories: list[str]
    scale: Scale
    activity_ref: Ref
    system_ref: Ref | None = None


@dataclass
class CriterionResult:
    id: str
    label: str
    met: bool | None  # None: the evidence cannot say
    basis: str
    refs: list[Ref] = field(default_factory=list)
    needs: str | None = None  # what to supply when unknown

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "label": self.label, "met": self.met, "basis": self.basis,
            "refs": [r.as_dict() for r in self.refs], "needs": self.needs,
        }  # fmt: skip


@dataclass
class Screening:
    results: list[CriterionResult]
    threshold: int

    @property
    def met(self) -> int:
        return sum(1 for r in self.results if r.met)

    @property
    def unknown(self) -> int:
        return sum(1 for r in self.results if r.met is None)

    @property
    def required(self) -> bool:
        return self.met >= self.threshold

    @property
    def undecided(self) -> bool:
        """Not required on what is known, but unknown criteria could change that."""
        return not self.required and self.met + self.unknown >= self.threshold

    def met_ids(self) -> list[str]:
        return [r.id for r in self.results if r.met]


def countries_in(text: str) -> int | None:
    match = COUNTRIES.search(text)
    if not match:
        return None
    raw = match.group(1).lower()
    return int(raw) if raw.isdigit() else NUMBER_WORDS.get(raw)


def keyword_hits(pattern: re.Pattern[str], texts: list[str]) -> list[str]:
    """Sentences that name the keyword and do not negate it ("we do not use profiling")."""
    hits = []
    for text in texts:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            match = pattern.search(sentence)
            if match and not NEGATION.search(sentence[: match.start()]):
                hits.append(sentence.strip())
    return hits


def screen(inp: ScreeningInput, criteria: CriteriaSet) -> Screening:
    texts = [inp.description, *inp.purposes, *inp.extra_text]
    results = [_judge(c, inp, texts) for c in criteria.criteria]
    return Screening(results, criteria.threshold)


def _judge(c: Criterion, inp: ScreeningInput, texts: list[str]) -> CriterionResult:
    result = _rule(c, inp, texts)
    if c.id in inp.scale.flags and not result.met:
        return CriterionResult(
            c.id,
            c.label,
            True,
            "Stated by an analyst",
            [Ref("manual", None, "stated by an analyst")],
        )
    return result


def _rule(c: Criterion, inp: ScreeningInput, texts: list[str]) -> CriterionResult:
    cid = c.id

    def out(
        met: bool | None, basis: str, refs: Iterable[Ref] = (), needs: str | None = None
    ) -> CriterionResult:
        return CriterionResult(cid, c.label, met, basis, list(refs), needs)

    if cid == "sensitive_data":
        special = sorted(set(inp.special_categories))
        other = sorted(SENSITIVE_CATEGORIES & set(inp.categories))
        if special or other:
            kinds = ", ".join(x.replace("_", " ") for x in [*special, *other])
            refs = [e.ref for e in inp.elements if e.special or e.category in SENSITIVE_CATEGORIES][
                :3
            ]
            return out(True, f"Handles {kinds}", refs)
        return out(
            False, "No special category, criminal, national identifier or bank account data found"
        )

    if cid == "vulnerable_subjects":
        found = sorted(
            {
                m.group(0).lower()
                for s in inp.data_subjects
                for m in [VULNERABLE_WORDS.search(s)]
                if m
            }
        )
        if found:
            return out(True, f"Data subjects include {', '.join(found)}", [inp.activity_ref])
        return out(False, "Data subjects are " + (", ".join(inp.data_subjects) or "not stated"))

    if cid == "systematic_monitoring":
        stored = [e for e in inp.elements if e.stored and e.category in MONITORING_CATEGORIES]
        if stored:
            names = sorted({(e.category or "").replace("_", " ") for e in stored})
            return out(
                True,
                f"Stores {', '.join(names)} about people ('{stored[0].name}' in {stored[0].table})",
                [e.ref for e in stored[:3]],
            )
        hits = keyword_hits(KEYWORDS[cid], texts)
        if hits:
            return out(True, f'Described as monitoring: "{hits[0][:160]}"', [inp.activity_ref])
        return out(
            False, "No stored location or browsing behaviour and no monitoring purpose described"
        )

    if cid == "large_scale":
        estimate = inp.scale.data_subjects_estimate
        countries = inp.scale.countries or countries_in(inp.description)
        reasons = []
        if estimate is not None and estimate >= LARGE_SCALE_SUBJECTS:
            reasons.append(f"about {estimate} data subjects")
        if countries is not None and countries >= LARGE_SCALE_COUNTRIES:
            reasons.append(f"{countries} countries")
        if reasons:
            return out(True, "Large scale: " + " and ".join(reasons), [inp.activity_ref])
        if estimate is None and countries is None:
            return out(
                None,
                "Nothing in the evidence shows how many people are affected",
                needs="Enter an estimate of the number of data subjects and the countries covered",
            )
        return out(
            False,
            f"About {estimate if estimate is not None else 'an unknown number of'} data subjects"
            + (f" in {countries} countries" if countries else ""),
        )

    if cid == "combining_datasets":
        enriching = [
            r
            for r in inp.recipients
            if not r.internal and (r.category or "") in ENRICHMENT_CATEGORIES
        ]
        if enriching:
            return out(
                True,
                f"{enriching[0].label} adds data from other sources (enrichment)",
                [r.ref for r in enriching],
            )
        hits = keyword_hits(KEYWORDS[cid], texts)
        if hits:
            return out(
                True, f'Data from other sources is added: "{hits[0][:160]}"', [inp.activity_ref]
            )
        return out(False, "No enrichment, matching or combination with other sources found")

    if cid == "innovative_technology":
        if BIOMETRIC_CATEGORIES & set(inp.categories):
            return out(
                True,
                "Handles biometric or genetic data",
                [e.ref for e in inp.elements if e.category in BIOMETRIC_CATEGORIES][:2],
            )
        hits = keyword_hits(KEYWORDS[cid], texts)
        if hits:
            return out(True, f'Uses new technology: "{hits[0][:160]}"', [inp.activity_ref])
        return out(False, "No biometric data and no new technology described")

    # criteria judged from the description of the purpose
    hits = keyword_hits(KEYWORDS[cid], texts)
    if hits:
        return out(True, f'Described in the record: "{hits[0][:160]}"', [inp.activity_ref])
    return out(False, "Nothing in the purposes or notice points to this")
