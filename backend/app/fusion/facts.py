"""The inputs of the fusion rules, free of any database or model so the rules can be unit tested."""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class Ref:
    """Where a statement or finding comes from. Every fact keeps one."""

    kind: str  # questionnaire | policy | discovery | company_policy | agreement
    ref_id: str | None
    detail: str

    def as_dict(self) -> dict[str, str | None]:
        return {"kind": self.kind, "id": self.ref_id, "detail": self.detail}


@dataclass(frozen=True)
class ElementFact:
    name: str
    category: str | None
    special: bool
    location_kind: str
    table: str | None
    pattern_class: str | None
    checked_by_default: bool
    input_type: str | None
    record_months: dict[str, str] | None  # oldest, newest, basis (timestamp columns)
    confidence: float | None
    reviewed: bool  # a person accepted or overrode the classification
    ref: Ref

    @property
    def stored(self) -> bool:
        """True for data held in a database, as opposed to data only seen in transit."""
        return self.location_kind == "db_column"


@dataclass(frozen=True)
class RecipientFact:
    vendor: str | None
    domain: str
    role: str  # controller | processor | joint_controller | unknown
    country: str | None
    internal: bool
    ref: Ref
    category: str | None = None  # vendor registry category, for example data_enrichment
    purpose: str | None = None

    @property
    def key(self) -> str:
        return slug(self.vendor or self.domain)

    @property
    def label(self) -> str:
        return self.vendor or self.domain


@dataclass
class Questionnaire:
    answers: dict[str, Any]
    ref: Ref

    @property
    def retention(self) -> str:
        return str(self.answers.get("retention") or "").strip()

    @property
    def special_category_condition(self) -> str:
        return str(self.answers.get("special_category_condition") or "").strip()

    @property
    def declared_vendors(self) -> list[str]:
        return [str(r.get("vendor", "")) for r in self.answers.get("recipients_declared") or []]

    @property
    def agreements(self) -> list[str]:
        return [str(v) for v in self.answers.get("processors_with_agreement") or []]

    @property
    def transfers(self) -> list[dict[str, Any]]:
        return [t for t in self.answers.get("transfers") or [] if isinstance(t, dict)]

    @property
    def data_subjects(self) -> list[str]:
        return [str(v) for v in self.answers.get("data_subjects") or []]

    @property
    def last_review(self) -> date | None:
        try:
            return date.fromisoformat(str(self.answers.get("last_review_date")))
        except ValueError:
            return None


@dataclass
class PolicyFacts:
    """A privacy notice reduced to what the rules compare."""

    sections: dict[str, list[str]]  # heading -> paragraphs
    collected: list[str]  # bullets under "Personal data we collect"
    shared: list[tuple[str, str | None, str]]  # vendor, country, purpose
    retention_text: str
    ref: Ref

    def sentences(self) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        for heading, paragraphs in self.sections.items():
            for paragraph in paragraphs:
                for line in paragraph.splitlines():
                    for sentence in re.split(r"(?<=[.!?])\s+", line.lstrip("-* ").strip()):
                        if sentence:
                            found.append((heading, sentence))
        return found


@dataclass
class CompanyRules:
    """Limits taken from the organisation wide policy."""

    retention_months: int | None
    retention_text: str
    passages: list[tuple[str, str]]  # (passage id, text) of the retention clause
    ref: Ref


@dataclass
class SystemFacts:
    system_id: str
    name: str
    elements: list[ElementFact]
    recipients: list[RecipientFact]
    questionnaire: Questionnaire | None
    policy: PolicyFacts | None
    company: CompanyRules | None
    agreement_vendors: set[str] = field(default_factory=set)
    adequate: frozenset[str] = frozenset()
    eea: frozenset[str] = frozenset()
    as_of: date = field(default_factory=date.today)
    policy_categories: set[str] = field(default_factory=set)  # categories named by the notice
    claim_categories: dict[str, str | None] = field(
        default_factory=dict
    )  # claim subject -> category


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def same_vendor(a: str, b: str) -> bool:
    """'BrightLens' matches 'BrightLens Agency'; 'Stripe' does not match 'Stripe Atlas Ltd' by luck:
    one name must contain the other as whole words."""
    ta, tb = set(re.findall(r"[a-z0-9]+", a.lower())), set(re.findall(r"[a-z0-9]+", b.lower()))
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta
