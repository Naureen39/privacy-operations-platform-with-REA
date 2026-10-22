"""Fill a record of processing from the facts of a system, with Jinja templates for the text and a
citation for every field. The model contributes only the purposes and a lawful basis suggestion."""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.fusion.facts import Ref, SystemFacts, same_vendor
from app.llm.schemas import PurposeAndBasis

TEMPLATES = Path(__file__).resolve().parent / "templates"
NOTICE = "Draft for review by a qualified privacy professional. Not legal advice."

REQUIRED_FIELDS = (
    "name",
    "purposes",
    "data_subjects",
    "data_categories",
    "recipients",
    "transfers",
    "retention",
    "security_measures",
    "lawful_basis",
    "owner_user_id",
    "next_review_date",
)
# `recipients` and `transfers` may legitimately be empty lists: the record then says "none".
MAY_BE_EMPTY = ("recipients", "transfers")

_env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    undefined=StrictUndefined,
    autoescape=False,  # noqa: S701  (plain text for a database field, a spreadsheet and a PDF)
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=False,
)


def render(template: str, **values: Any) -> str:
    return _env.get_template(template).render(**values).strip()


@dataclass
class Draft:
    fields: dict[str, Any]
    citations: dict[str, list[dict[str, str | None]]]
    special_categories: list[str] = field(default_factory=list)
    suggestion: dict[str, Any] | None = None


def summary_text(fields: dict[str, Any], labels: dict[str, str], special: list[str]) -> str:
    """One readable paragraph for the register and the review screen."""
    return render(
        "summary.j2",
        name=fields.get("name") or "",
        categories=[labels.get(c, c) for c in fields.get("data_categories") or []],
        subjects=fields.get("data_subjects") or [],
        recipients=[r.get("vendor", "") for r in fields.get("recipients") or []],
        special=[labels.get(c, c) for c in special],
        retention=fields.get("retention"),
    )


def completeness(fields: dict[str, Any], special_categories: list[str]) -> list[str]:
    """Required fields that are empty. The Article 9 condition is required when special category
    data was found."""
    missing = []
    for name in REQUIRED_FIELDS:
        value = fields.get(name)
        if name in MAY_BE_EMPTY and value is not None:
            continue
        if value in (None, "", []):
            missing.append(name)
    if special_categories and not fields.get("special_category_condition"):
        missing.append("special_category_condition")
    return missing


def build_draft(
    facts: SystemFacts,
    owner_user_id: str | None,
    labels: dict[str, str],
    suggestion: PurposeAndBasis | None = None,
) -> Draft:
    q, policy = facts.questionnaire, facts.policy
    fields: dict[str, Any] = {"name": facts.name, "owner_user_id": owner_user_id}
    cites: dict[str, list[Ref]] = {"name": [Ref("system", facts.system_id, "system name")]}
    cites["owner_user_id"] = [Ref("system", facts.system_id, "system owner")]

    # data subjects
    fields["data_subjects"] = list(q.data_subjects) if q else []
    cites["data_subjects"] = [q.ref] if q else []

    # data categories: what discovery found, with the questionnaire's own list as a second source
    found: dict[str, Ref] = {}
    for e in facts.elements:
        if e.category:
            found.setdefault(e.category, e.ref)
    declared = [str(c) for c in (q.answers.get("data_categories_declared") or [])] if q else []
    fields["data_categories"] = sorted(set(found) | set(declared))
    cites["data_categories"] = [
        *(found[c] for c in sorted(found)),
        *([q.ref] if q and declared else []),
    ]
    special = sorted({e.category or e.name for e in facts.elements if e.special})

    # recipients and transfers
    recipients, transfers = [], []
    transfer_refs: list[Ref] = []
    recipient_refs: list[Ref] = []
    seen: set[str] = set()
    # a stable order, so the same facts always give the same record (and no phantom version)
    for r in sorted(facts.recipients, key=lambda x: (x.key, x.domain)):
        if r.internal or r.key in seen:
            continue
        seen.add(r.key)
        in_policy = policy is not None and any(same_vendor(r.label, v) for v, _, _ in policy.shared)
        in_q = q is not None and any(same_vendor(r.label, v) for v in q.declared_vendors)
        purpose = _purpose_for(facts, r.label)
        recipient_refs.append(r.ref)
        recipients.append(
            {
                "vendor": r.label,
                "domain": r.domain,
                "role": r.role,
                "country": r.country,
                "purpose": purpose,
                "declared": in_policy and in_q,
                "text": render(
                    "recipient.j2", vendor=r.label, role=r.role, country=r.country,
                    purpose=purpose, declared=in_policy and in_q,
                ),
            }
        )  # fmt: skip
        country = (r.country or "").upper()
        if country and country not in facts.eea:
            safeguard = next(
                (str(t.get("safeguard") or "") for t in (q.transfers if q else []) if same_vendor(r.label, str(t.get("recipient", "")))),
                "",
            )  # fmt: skip
            if country in facts.adequate:
                mechanism, gap = "adequacy decision", False
            elif safeguard:
                mechanism, gap = safeguard.replace("_", " "), False
            else:
                mechanism, gap = "none recorded", True
            transfer_refs.append(r.ref)
            transfers.append(
                {
                    "recipient": r.label, "country": country, "mechanism": mechanism, "gap": gap,
                    "text": render("transfer.j2", recipient=r.label, country=country, mechanism=mechanism, gap=gap),
                }
            )  # fmt: skip
    fields["recipients"], fields["transfers"] = recipients, transfers
    cites["recipients"] = [
        *recipient_refs,
        *([q.ref] if q else []),
        *([policy.ref] if policy else []),
    ]
    cites["transfers"] = [*transfer_refs, *([q.ref] if q else [])] or ([q.ref] if q else [])

    # retention, security, special category condition, lawful basis, purposes
    retention = (q.retention if q else "") or (policy.retention_text if policy else "")
    fields["retention"] = retention.strip() or None
    cites["retention"] = [q.ref] if q and q.retention else ([policy.ref] if policy else [])
    measures = [str(m) for m in (q.answers.get("security_measures") or [])] if q else []
    fields["security_measures"] = render("security.j2", measures=measures) if measures else None
    cites["security_measures"] = [q.ref] if q else []
    fields["special_category_condition"] = (q.special_category_condition or None) if q else None
    cites["special_category_condition"] = [q.ref] if q else []

    declared_purposes = [str(p) for p in (q.answers.get("purposes") or [])] if q else []
    declared_basis = str(q.answers.get("lawful_basis") or "") if q else ""
    purposes, basis = list(declared_purposes), declared_basis
    cites["purposes"] = [q.ref] if q and declared_purposes else []
    cites["lawful_basis"] = [q.ref] if q and declared_basis else []
    suggestion_meta: dict[str, Any] | None = None
    if suggestion is not None:
        merged = list(dict.fromkeys([*declared_purposes, *suggestion.purposes]))
        purposes = merged[:8]
        note = Ref("assistant", None, f"Suggested for review: {suggestion.basis_rationale}")
        cites["purposes"].append(note)
        if not basis or basis == "not_applicable":
            basis = suggestion.lawful_basis
            cites["lawful_basis"].append(note)
        suggestion_meta = {
            "lawful_basis": suggestion.lawful_basis,
            "rationale": suggestion.basis_rationale,
            "needs_review": suggestion.needs_review,
        }
    fields["purposes"], fields["lawful_basis"] = purposes, basis or None

    # review date: twelve months after the last review (or after the comparison date)
    last = q.last_review if q else None
    due = _add_months(last or facts.as_of, 12)
    if due < facts.as_of:
        due = _add_months(facts.as_of, 1)  # overdue: ask for a review within a month
    fields["next_review_date"] = due.isoformat()
    cites["next_review_date"] = (
        [q.ref] if q else [Ref("system", facts.system_id, "comparison date")]
    )

    return Draft(
        fields,
        {k: [r.as_dict() for r in v] for k, v in cites.items()},
        special_categories=special,
        suggestion=suggestion_meta,
    )


def _purpose_for(facts: SystemFacts, vendor: str) -> str | None:
    if facts.policy:
        for name, _, purpose in facts.policy.shared:
            if same_vendor(vendor, name):
                return purpose
    if facts.questionnaire:
        for entry in facts.questionnaire.answers.get("recipients_declared") or []:
            if same_vendor(vendor, str(entry.get("vendor", ""))):
                return str(entry.get("purpose") or "") or None
    return None


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
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
    ][month - 1]
    return date(year, month, min(day.day, last))
