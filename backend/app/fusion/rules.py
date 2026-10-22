"""The fusion rules. Each takes the facts of one system and returns findings with evidence. Nothing
here calls a model: conflicts the rules cannot settle are returned as `Ambiguity` for the service
to put to `adjudicate_conflict`."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from app.fusion.facts import (
    ElementFact,
    RecipientFact,
    Ref,
    SystemFacts,
    same_vendor,
    slug,
)
from app.fusion.policy import (
    extract_claims,
    months_between,
    retention_months,
    stem,
)

CUSTOMER_WORDS = ("customer", "consumer", "shopper", "client")
# Below this a category is a guess and belongs in the classification review queue, not in a
# finding addressed to the system owner (special category data is always reported).
MIN_CONFIDENCE = 0.80
CONSENT_NAME_WORDS = ("consent", "optin", "opt_in", "marketing", "newsletter", "subscribe")


@dataclass
class RawFinding:
    type: str
    severity: str  # low | medium | high | critical
    subject: str
    title: str
    description: str
    suggested_fix: str
    refs: list[Ref] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.type}:{self.subject}"


@dataclass
class Ambiguity:
    """A statement the rules cannot settle; the model gets it with the top 3 policy passages."""

    type: str  # the finding type to raise if the model says the statement is contradicted
    subject: str
    statement: str
    detail: str
    passages: list[tuple[str, str]]
    finding: RawFinding  # raised when contradicted; softened to a review item when undetermined


@dataclass
class RuleOutput:
    findings: list[RawFinding] = field(default_factory=list)
    ambiguities: list[Ambiguity] = field(default_factory=list)


FINDING_TYPES = (
    "element_not_in_policy",
    "undeclared_recipient",
    "third_country_no_safeguard",
    "missing_agreement",
    "missing_art9_condition",
    "missing_retention",
    "stale_review",
    "policy_contradiction",
    "retention_conflict",
    "consent_defect",
    "cookie_not_in_policy",
    "retention_review",
    "missing_evidence",
)


def run_rules(facts: SystemFacts) -> RuleOutput:
    out = RuleOutput()
    for rule in RULES:
        rule(facts, out)
    return out


# -- helpers -------------------------------------------------------------------------------------


def external(facts: SystemFacts) -> list[RecipientFact]:
    seen: dict[str, RecipientFact] = {}
    for r in facts.recipients:
        if not r.internal:
            seen.setdefault(r.key, r)
    return list(seen.values())


def declared_in_policy(facts: SystemFacts, recipient: RecipientFact) -> bool:
    if facts.policy is None:
        return False
    names = [v for v, _, _ in facts.policy.shared]
    return any(same_vendor(recipient.label, n) for n in names)


def declared_in_questionnaire(facts: SystemFacts, recipient: RecipientFact) -> bool:
    if facts.questionnaire is None:
        return False
    return any(same_vendor(recipient.label, n) for n in facts.questionnaire.declared_vendors)


# -- rules ---------------------------------------------------------------------------------------


def missing_evidence(facts: SystemFacts, out: RuleOutput) -> None:
    for what, present in (("questionnaire", facts.questionnaire), ("privacy notice", facts.policy)):
        if present is None:
            out.findings.append(
                RawFinding(
                    "missing_evidence", "medium", what.replace(" ", "_"),
                    f"No {what} on file for {facts.name}",
                    f"The comparison needs the {what}; without it some checks cannot run.",
                    f"Upload the {what} as evidence and run the comparison again.",
                )
            )  # fmt: skip


def element_not_in_policy(facts: SystemFacts, out: RuleOutput) -> None:
    if facts.policy is None:
        return
    seen: dict[str, ElementFact] = {}
    cookies: dict[str, ElementFact] = {}
    for e in facts.elements:
        if not e.category or e.category in facts.policy_categories:
            continue
        if not (e.special or e.reviewed or (e.confidence or 0) >= MIN_CONFIDENCE):
            continue
        (cookies if e.location_kind == "cookie" else seen).setdefault(e.category, e)
    for category, e in sorted(cookies.items()):
        if category in seen:
            continue  # the same kind of data is already reported from a form or request
        out.findings.append(
            RawFinding(
                "cookie_not_in_policy", "low", e.name,
                f"Cookie '{e.name}' is not described in the privacy notice",
                f"Discovery found the cookie '{e.name}' ({category.replace('_', ' ')}). Cookies are "
                "usually described in a cookie notice, so this is reported separately and at low severity.",
                "Describe the cookie in the privacy or cookie notice, or confirm it is strictly necessary.",
                [e.ref, facts.policy.ref],
            )
        )  # fmt: skip
    for category, e in sorted(seen.items()):
        out.findings.append(
            RawFinding(
                "element_not_in_policy", "high" if e.special else "medium", category,
                f"{category.replace('_', ' ').capitalize()} is collected but not in the privacy notice",
                f"Discovery found '{e.name}' ({e.location_kind.replace('_', ' ')}) classified as "
                f"{category.replace('_', ' ')}. The notice does not list this kind of data.",
                "Add the data to the notice (and to the record), or stop collecting it.",
                [e.ref, facts.policy.ref],
            )
        )  # fmt: skip


def undeclared_recipient(facts: SystemFacts, out: RuleOutput) -> None:
    for r in external(facts):
        in_policy, in_q = declared_in_policy(facts, r), declared_in_questionnaire(facts, r)
        if in_policy and in_q:
            continue
        where = [
            w
            for w, ok in (("the privacy notice", in_policy), ("the questionnaire", in_q))
            if not ok
        ]
        refs = [r.ref]
        if facts.questionnaire:
            refs.append(facts.questionnaire.ref)
        if facts.policy:
            refs.append(facts.policy.ref)
        out.findings.append(
            RawFinding(
                "undeclared_recipient", "high", r.key,
                f"{r.label} receives data but is not declared",
                f"Traffic or code shows data going to {r.domain} ({r.label}"
                + (f", {r.country}" if r.country else "")
                + f"). It is missing from {' and '.join(where)}.",
                "Declare the recipient, check the legal basis and any agreement, or remove the integration.",
                refs,
            )
        )  # fmt: skip


def third_country_no_safeguard(facts: SystemFacts, out: RuleOutput) -> None:
    for r in external(facts):
        country = (r.country or "").upper()
        if not country or country in facts.eea or country in facts.adequate:
            continue
        transfers = facts.questionnaire.transfers if facts.questionnaire else []
        safeguard = next(
            (
                str(t.get("safeguard") or "")
                for t in transfers
                if same_vendor(r.label, str(t.get("recipient", "")))
            ),
            "",
        )
        if safeguard:
            continue
        refs = [r.ref] + ([facts.questionnaire.ref] if facts.questionnaire else [])
        out.findings.append(
            RawFinding(
                "third_country_no_safeguard", "high", r.key,
                f"Transfer to {r.label} ({country}) has no recorded safeguard",
                f"{r.label} is in {country}, which is outside the EEA and has no adequacy decision that "
                "applies without further checks. No safeguard is recorded for the transfer.",
                "Record the safeguard (standard contractual clauses, binding corporate rules or another "
                "Article 46 mechanism) and the transfer assessment, or stop the transfer.",
                refs,
            )
        )  # fmt: skip


def missing_agreement(facts: SystemFacts, out: RuleOutput) -> None:
    on_file = list(facts.questionnaire.agreements) if facts.questionnaire else []
    on_file += sorted(facts.agreement_vendors)
    for r in external(facts):
        if r.role != "processor" or any(same_vendor(r.label, v) for v in on_file):
            continue
        out.findings.append(
            RawFinding(
                "missing_agreement", "high", r.key,
                f"No processor agreement on file for {r.label}",
                f"{r.label} acts as a processor but no data processing agreement is recorded.",
                "Put an Article 28 agreement in place and record it.",
                [r.ref] + ([facts.questionnaire.ref] if facts.questionnaire else []),
            )
        )  # fmt: skip


def missing_art9_condition(facts: SystemFacts, out: RuleOutput) -> None:
    special = [e for e in facts.elements if e.special]
    if not special or facts.questionnaire is None or facts.questionnaire.special_category_condition:
        return
    kinds = sorted({(e.category or e.name).replace("_", " ") for e in special})
    out.findings.append(
        RawFinding(
            "missing_art9_condition", "critical", "special_categories",
            "Special category data without a recorded Article 9 condition",
            "Discovery found " + ", ".join(kinds) + ". The questionnaire records no Article 9(2) condition.",
            "Record the Article 9(2) condition that applies (and the Article 6 basis), or stop processing the data.",
            [special[0].ref, facts.questionnaire.ref],
        )
    )  # fmt: skip


def missing_retention(facts: SystemFacts, out: RuleOutput) -> None:
    if facts.questionnaire is not None and not facts.questionnaire.retention:
        out.findings.append(
            RawFinding(
                "missing_retention", "medium", "retention", "No retention period recorded",
                "The questionnaire gives no retention period.",
                "Record how long each kind of data is kept and when it is deleted.",
                [facts.questionnaire.ref],
            )
        )  # fmt: skip


def stale_review(facts: SystemFacts, out: RuleOutput) -> None:
    if facts.questionnaire is None:
        return
    reviewed = facts.questionnaire.last_review
    limit = _months_before(facts.as_of, 12)
    if reviewed is None:
        out.findings.append(
            RawFinding(
                "stale_review", "low", "last_review_date", "No review date recorded",
                "The questionnaire has no valid last review date.",
                "Review the record and enter the date.", [facts.questionnaire.ref],
            )
        )  # fmt: skip
    elif reviewed < limit:
        out.findings.append(
            RawFinding(
                "stale_review", "low", "last_review_date",
                f"Record last reviewed on {reviewed.isoformat()}",
                f"The last review is more than twelve months before {facts.as_of.isoformat()}.",
                "Review the record with the system owner and update the date.",
                [facts.questionnaire.ref],
            )
        )  # fmt: skip


def policy_claims(facts: SystemFacts, out: RuleOutput) -> None:
    if facts.policy is None:
        return
    for claim in extract_claims(facts.policy):
        if claim.kind == "exclusive_sharing":
            for r in external(facts):
                if not declared_in_policy(facts, r):
                    out.findings.append(
                        RawFinding(
                            "policy_contradiction", "high", f"sharing:{r.key}",
                            f"The notice limits sharing, yet {r.label} receives data",
                            f"The notice says: \"{claim.sentence}\" Discovery shows data going to "
                            f"{r.domain} ({r.label}), which the notice does not name.",
                            "Correct the notice or stop the transfer to this recipient.",
                            [facts.policy.ref, r.ref],
                        )
                    )  # fmt: skip
        elif claim.kind == "negative_storage" and claim.subject:
            category = facts.claim_categories.get(claim.subject)
            stored = [e for e in facts.elements if e.stored and category and e.category == category]
            if stored and category:
                e = stored[0]
                out.findings.append(
                    RawFinding(
                        "policy_contradiction", "high", f"storage:{category}",
                        f"The notice says {claim.subject} is not stored, but it is",
                        f"The notice says: \"{claim.sentence}\" Discovery found '{e.name}' "
                        f"({category.replace('_', ' ')}) in the database column {e.table}.{e.name}.",
                        "Stop storing the data, or correct the notice.",
                        [facts.policy.ref, e.ref],
                    )
                )  # fmt: skip
        elif claim.kind == "active_consent":
            boxes = [
                e for e in facts.elements
                if e.checked_by_default and e.input_type == "checkbox" and _is_consent_box(e)
            ]  # fmt: skip
            for e in boxes:
                out.findings.append(
                    RawFinding(
                        "consent_defect", "high", f"preticked:{e.name}",
                        f"Consent box '{e.name}' is ticked by default",
                        f"The notice says: \"{claim.sentence}\" The form field '{e.name}' is checked "
                        "before the person does anything.",
                        "Leave the box unticked so consent is an active choice.",
                        [facts.policy.ref, e.ref],
                    )
                )  # fmt: skip


def _is_consent_box(e: ElementFact) -> bool:
    name = e.name.lower()
    return e.category == "consent_record" or any(w in name for w in CONSENT_NAME_WORDS)


def retention_checks(facts: SystemFacts, out: RuleOutput) -> None:
    periods: list[int] = []
    sources: list[Ref] = []
    if facts.policy:
        periods += retention_months(facts.policy.retention_text)
        sources.append(facts.policy.ref)
    if facts.questionnaire:
        periods += retention_months(facts.questionnaire.retention)
        sources.append(facts.questionnaire.ref)

    # 1. records older than the period the notice promises
    if facts.policy:
        for sentence in _retention_sentences(facts):
            limits = retention_months(sentence)
            if not limits:
                continue
            words = {stem(w) for w in _words(sentence)}
            for e in facts.elements:
                if not e.record_months or not e.table or stem(e.table) not in words:
                    continue
                age = months_between(e.record_months["oldest"], facts.as_of.year, facts.as_of.month)
                if age > max(limits) + 1:
                    out.findings.append(
                        RawFinding(
                            "retention_conflict", "medium", f"age:{e.table}",
                            f"Records in '{e.table}' are older than the stated retention",
                            f"The notice says: \"{sentence}\" The oldest record in '{e.table}' dates from "
                            f"{e.record_months['oldest']} ({age} months before {facts.as_of.isoformat()}; "
                            f"{e.record_months['basis']}).",
                            "Delete data past its period, or correct the stated period.",
                            [facts.policy.ref, e.ref],
                        )
                    )  # fmt: skip
                    break

    # 2. a period longer than the organisation's own limit
    company = facts.company
    if company is None or company.retention_months is None or not periods:
        return
    longest = max(periods)
    if longest <= company.retention_months:
        return
    subjects = facts.questionnaire.data_subjects if facts.questionnaire else []
    finding = RawFinding(
        "retention_conflict",
        "medium",
        "company_limit",
        f"Retention of {longest} months exceeds the company limit of {company.retention_months}",
        f"{facts.name} keeps data for up to {longest} months. The company policy says: "
        f'"{company.retention_text}"',
        "Shorten the period, or record the written approval the company policy requires.",
        [*sources, company.ref],
    )
    if any(w in s.lower() for s in subjects for w in CUSTOMER_WORDS):
        out.findings.append(finding)
    else:
        out.ambiguities.append(
            Ambiguity(
                "retention_conflict", "company_limit",
                f"{facts.name} keeps data of {', '.join(subjects) or 'its data subjects'} for up to {longest} months",
                f"Does the company retention limit of {company.retention_months} months apply to these data subjects?",
                company.passages[:3], finding,
            )
        )  # fmt: skip


def _retention_sentences(facts: SystemFacts) -> list[str]:
    import re

    assert facts.policy is not None  # noqa: S101
    return [s for s in re.split(r"(?<=[.!?])\s+", facts.policy.retention_text) if s]


def _words(text: str) -> list[str]:
    import re

    return re.findall(r"[a-z]+", text.lower())


def _months_before(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    last = [
        31,
        29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ][month]
    return date(year, month + 1, min(day.day, last))


RULES: list[Callable[[SystemFacts, RuleOutput], None]] = [
    missing_evidence,
    element_not_in_policy,
    undeclared_recipient,
    third_country_no_safeguard,
    missing_agreement,
    missing_art9_condition,
    missing_retention,
    stale_review,
    policy_claims,
    retention_checks,
]

__all__ = ["Ambiguity", "RawFinding", "RuleOutput", "run_rules", "slug"]
