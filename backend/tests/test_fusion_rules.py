"""The fusion rules on small hand-made facts (no database, no model)."""

from datetime import date

import pytest

from app.fusion.facts import (
    CompanyRules,
    ElementFact,
    PolicyFacts,
    Questionnaire,
    RecipientFact,
    Ref,
    SystemFacts,
    same_vendor,
)
from app.fusion.policy import (
    extract_claims,
    months_between,
    negative_storage_subject,
    parse_policy,
    retention_months,
)
from app.fusion.rules import _months_before, run_rules

REF = Ref("discovery", "e1", "thing")
NOTICE = """# Privacy notice: Shop

## Personal data we collect

- your e-mail address
- your name

## Who we share it with

We do not share your personal data with any third party other than our payment provider.

- Stripe (US): payment processing

## How long we keep it

We keep order records for seven years because tax law requires it. Visit logs are kept for 25 months.

## How we handle your data

- We never store a full IP address.
- Chat transcripts are not stored after the conversation ends.
- No box is ticked for you.
"""


def element(name: str, category: str | None, **kw: object) -> ElementFact:
    defaults: dict[str, object] = {
        "special": False, "location_kind": "form_field", "table": None, "pattern_class": None,
        "checked_by_default": False, "input_type": None, "record_months": None,
        "confidence": 0.95, "reviewed": False, "ref": REF,
    }  # fmt: skip
    return ElementFact(name=name, category=category, **{**defaults, **kw})  # type: ignore[arg-type]


def recipient(
    vendor: str, country: str = "US", role: str = "processor", internal: bool = False
) -> RecipientFact:
    return RecipientFact(vendor, f"{vendor.lower()}.example", role, country, internal, REF)


def questionnaire(**answers: object) -> Questionnaire:
    base = {
        "data_subjects": ["customers"], "retention": "7 years", "last_review_date": "2026-06-01",
        "special_category_condition": "not_applicable", "processors_with_agreement": [],
        "recipients_declared": [], "transfers": [],
    }  # fmt: skip
    return Questionnaire({**base, **answers}, Ref("questionnaire", "q1", "questionnaire.json"))


def facts(**kw: object) -> SystemFacts:
    defaults: dict[str, object] = {
        "system_id": "s1", "name": "Shop", "elements": [], "recipients": [],
        "questionnaire": questionnaire(), "policy": parse_policy(NOTICE, Ref("policy", "p1", "policy.md")),
        "company": None, "adequate": frozenset({"GB", "CH"}), "eea": frozenset({"NL", "DE", "IE"}),
        "as_of": date(2026, 10, 1), "policy_categories": {"contact_email", "name"},
    }  # fmt: skip
    return SystemFacts(**{**defaults, **kw})  # type: ignore[arg-type]


def kinds(f: SystemFacts) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for finding in run_rules(f).findings:
        result.setdefault(finding.type, []).append(finding.subject)
    return result


# -- reading the notice --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "months"),
    [
        ("We keep order records for seven years.", [84]),
        ("Visit records are kept for 25 months.", [25]),
        ("Deleted twelve months after they are closed.", [12]),
        ("10 years", [120]),
        ("Employment records are kept for the duration of employment plus six years.", []),
        ("We keep your subscription until you unsubscribe, then delete it within 30 days.", []),
        ("Accounts until deletion request", []),
        ("7 years for orders (tax law); accounts until deletion request", [84]),
        ("no longer than 24 months after the customer's last interaction", [24]),
    ],
)
def test_retention_periods(text: str, months: list[int]) -> None:
    assert retention_months(text) == months


def test_the_notice_is_reduced_to_what_the_rules_compare() -> None:
    policy = parse_policy(NOTICE, Ref("policy", "p1", "policy.md"))
    assert policy.collected == ["your e-mail address", "your name"]
    assert policy.shared == [("Stripe", "US", "payment processing")]
    assert "seven years" in policy.retention_text
    claims = {(c.kind, c.subject) for c in extract_claims(policy)}
    assert ("exclusive_sharing", None) in claims
    assert ("negative_storage", "full IP address") in claims
    assert ("negative_storage", "Chat transcripts") in claims
    assert ("active_consent", None) in claims


@pytest.mark.parametrize(
    ("sentence", "subject"),
    [
        ("We never store a full IP address.", "full IP address"),
        ("Chat transcripts are not stored after the conversation ends.", "Chat transcripts"),
        ("We do not keep any card numbers.", "card numbers"),
        ("We store your name.", None),
    ],
)
def test_negative_storage_claims(sentence: str, subject: str | None) -> None:
    assert negative_storage_subject(sentence) == subject


def test_months_between_and_before() -> None:
    assert months_between("2022-03", 2026, 10) == 55
    assert _months_before(date(2026, 10, 1), 12) == date(2025, 10, 1)
    assert _months_before(date(2024, 2, 29), 12) == date(2023, 2, 28)
    assert _months_before(date(2026, 1, 15), 2) == date(2025, 11, 15)


def test_vendor_names_match_by_whole_words() -> None:
    assert same_vendor("BrightLens", "BrightLens Agency")
    assert same_vendor("Meta Platforms", "Meta")
    assert not same_vendor("Stripe", "Strip Club")
    assert not same_vendor("", "Stripe")


# -- rules ---------------------------------------------------------------------------------------


def test_nothing_is_reported_for_a_consistent_system() -> None:
    f = facts(
        elements=[element("email", "contact_email"), element("full_name", "name")],
        recipients=[recipient("Stripe", "US")],
        questionnaire=questionnaire(
            recipients_declared=[{"vendor": "Stripe", "country": "US"}],
            processors_with_agreement=["Stripe"],
            transfers=[
                {
                    "recipient": "Stripe",
                    "country": "US",
                    "safeguard": "standard_contractual_clauses",
                }
            ],
        ),
    )
    assert kinds(f) == {}


def test_element_not_in_policy_uses_the_category_not_the_name() -> None:
    f = facts(
        elements=[element("billing_birthdate", "date_of_birth"), element("mail", "contact_email")]
    )
    assert kinds(f) == {"element_not_in_policy": ["date_of_birth"]}


def test_uncertain_classifications_are_left_to_the_review_queue() -> None:
    low = facts(elements=[element("terms", "consent_record", confidence=0.775)])
    assert kinds(low) == {}
    special = facts(elements=[element("diagnosis", "health_data", confidence=0.6, special=True)])
    assert kinds(special)["element_not_in_policy"] == ["health_data"]
    reviewed = facts(elements=[element("x", "preferences", confidence=0.5, reviewed=True)])
    assert "element_not_in_policy" in kinds(reviewed)


def test_cookies_are_reported_separately_and_not_when_the_data_is_already_reported() -> None:
    only_cookie = facts(
        elements=[element("PHPSESSID", "online_identifier", location_kind="cookie")]
    )
    assert kinds(only_cookie) == {"cookie_not_in_policy": ["PHPSESSID"]}
    both = facts(
        elements=[
            element("PHPSESSID", "online_identifier", location_kind="cookie"),
            element("visitor", "online_identifier", location_kind="request_json_key"),
        ]
    )
    assert kinds(both) == {"element_not_in_policy": ["online_identifier"]}


def test_recipient_must_be_in_both_the_notice_and_the_questionnaire() -> None:
    f = facts(
        recipients=[recipient("Stripe"), recipient("Meta Platforms", role="controller"), recipient("Acme", internal=True)],
        questionnaire=questionnaire(
            recipients_declared=[{"vendor": "Stripe"}], processors_with_agreement=["Stripe"],
            transfers=[{"recipient": "Stripe", "safeguard": "scc"}],
        ),
    )  # fmt: skip
    found = kinds(f)
    assert found["undeclared_recipient"] == ["metaplatforms"]
    assert found["third_country_no_safeguard"] == ["metaplatforms"]
    assert "missing_agreement" not in found  # Meta is a controller, Stripe has an agreement


def test_third_countries_eea_adequacy_and_safeguards() -> None:
    q = questionnaire(
        recipients_declared=[{"vendor": v} for v in ("A", "B", "C", "D")],
        processors_with_agreement=["A", "B", "C", "D"],
        transfers=[{"recipient": "D", "safeguard": "binding_corporate_rules"}],
    )
    f = facts(
        questionnaire=q,
        recipients=[
            recipient("A", "NL"),
            recipient("B", "GB"),
            recipient("C", "IN"),
            recipient("D", "IN"),
        ],
    )
    found = kinds(f)
    assert found["third_country_no_safeguard"] == [
        "c"
    ]  # EEA and adequate countries need none; D has BCR
    # the United States has no blanket adequacy: a certification check or a safeguard is needed
    us = facts(questionnaire=q, recipients=[recipient("A", "US")])
    assert kinds(us)["third_country_no_safeguard"] == ["a"]
    unknown = facts(questionnaire=q, recipients=[recipient("A", None)])  # type: ignore[arg-type]
    assert "third_country_no_safeguard" not in kinds(unknown)


def test_a_processor_needs_an_agreement_on_file() -> None:
    f = facts(
        recipients=[recipient("BrightLens Agency", "GB"), recipient("Sentry", "US")],
        questionnaire=questionnaire(
            processors_with_agreement=["BrightLens"], recipients_declared=[{"vendor": "BrightLens"}],
            transfers=[{"recipient": "Sentry", "safeguard": "scc"}],
        ),
    )  # fmt: skip
    assert kinds(f)["missing_agreement"] == ["sentry"]
    covered = facts(
        recipients=[recipient("Sentry", "US")], agreement_vendors={"Sentry"},
        questionnaire=questionnaire(transfers=[{"recipient": "Sentry", "safeguard": "scc"}]),
    )  # fmt: skip
    assert "missing_agreement" not in kinds(covered)


def test_special_category_data_needs_a_recorded_condition() -> None:
    health = element("diagnosis", "health_data", special=True)
    assert kinds(
        facts(elements=[health], questionnaire=questionnaire(special_category_condition=None))
    )["missing_art9_condition"] == ["special_categories"]
    assert "missing_art9_condition" not in kinds(
        facts(
            elements=[health],
            questionnaire=questionnaire(special_category_condition="explicit_consent"),
        )
    )
    assert "missing_art9_condition" not in kinds(
        facts(
            elements=[element("n", "name")],
            questionnaire=questionnaire(special_category_condition=None),
        )
    )


def test_missing_retention_and_stale_review() -> None:
    f = facts(questionnaire=questionnaire(retention=None, last_review_date="2025-09-30"))
    found = kinds(f)
    assert found["missing_retention"] == ["retention"] and found["stale_review"] == [
        "last_review_date"
    ]
    assert "stale_review" not in kinds(
        facts(questionnaire=questionnaire(last_review_date="2025-10-01"))
    )
    assert kinds(facts(questionnaire=questionnaire(last_review_date="garbage")))[
        "stale_review"
    ] == ["last_review_date"]


def test_the_rules_follow_the_comparison_date() -> None:
    q = questionnaire(last_review_date="2026-02-01")
    assert "stale_review" not in kinds(facts(questionnaire=q, as_of=date(2027, 1, 31)))
    assert "stale_review" in kinds(facts(questionnaire=q, as_of=date(2027, 2, 2)))


def test_missing_documents_are_reported() -> None:
    found = kinds(facts(questionnaire=None, policy=None))
    assert found["missing_evidence"] == ["questionnaire", "privacy_notice"]


def test_policy_claims_against_evidence() -> None:
    f = facts(
        recipients=[recipient("Stripe"), recipient("Meta Platforms", role="controller")],
        elements=[
            element("ip", "ip_address", location_kind="db_column", table="visits"),
            element("body", "communications_content", location_kind="db_column", table="messages"),
            element("opt", "consent_record", input_type="checkbox", checked_by_default=True),
        ],
        claim_categories={
            "full IP address": "ip_address",
            "Chat transcripts": "communications_content",
        },
        policy_categories={
            "contact_email",
            "name",
            "ip_address",
            "communications_content",
            "consent_record",
        },
    )
    found = kinds(f)
    assert sorted(found["policy_contradiction"]) == [
        "sharing:metaplatforms",
        "storage:communications_content",
        "storage:ip_address",
    ]
    assert found["consent_defect"] == ["preticked:opt"]


def test_claims_are_not_contradicted_by_data_that_is_only_in_transit() -> None:
    f = facts(
        elements=[element("ip", "ip_address", location_kind="request_json_key")],
        claim_categories={"full IP address": "ip_address"},
        policy_categories={"contact_email", "name", "ip_address"},
    )
    assert "policy_contradiction" not in kinds(f)


def test_unticked_boxes_are_fine() -> None:
    f = facts(
        elements=[
            element("opt", "consent_record", input_type="checkbox", checked_by_default=False)
        ],
        policy_categories={"consent_record", "name"},
    )
    assert "consent_defect" not in kinds(f)


def retention_policy(text: str) -> PolicyFacts:
    return parse_policy(f"## How long we keep it\n\n{text}\n", Ref("policy", "p1", "policy.md"))


def test_records_older_than_the_stated_retention() -> None:
    table = element(
        "created_at", None, location_kind="db_column", table="conversations",
        record_months={"oldest": "2022-03", "newest": "2026-09", "basis": "whole table"},
    )  # fmt: skip
    f = facts(
        policy=retention_policy(
            "Support conversations are deleted twelve months after they are closed."
        ),
        elements=[table],
    )
    assert kinds(f)["retention_conflict"] == ["age:conversations"]
    recent = element(
        "created_at",
        None,
        location_kind="db_column",
        table="conversations",
        record_months={"oldest": "2025-12", "newest": "2026-09", "basis": "whole table"},
    )
    assert "retention_conflict" not in kinds(
        facts(
            policy=retention_policy(
                "Support conversations are deleted twelve months after they are closed."
            ),
            elements=[recent],
        )
    )
    other = element(
        "created_at",
        None,
        location_kind="db_column",
        table="invoices",
        record_months=table.record_months,
    )
    assert "retention_conflict" not in kinds(
        facts(
            policy=retention_policy(
                "Support conversations are deleted twelve months after they are closed."
            ),
            elements=[other],
        )
    )


COMPANY = CompanyRules(
    24,
    "no longer than 24 months",
    [("c1", "We keep consumer data no longer than 24 months.")],
    Ref("company_policy", "d1", "policy"),
)


def test_a_period_over_the_company_limit_is_a_conflict_for_customers() -> None:
    f = facts(
        company=COMPANY,
        policy=retention_policy("We keep order records for seven years."),
        questionnaire=questionnaire(retention="7 years"),
    )
    out = run_rules(f)
    assert [x.key for x in out.findings if x.type == "retention_conflict"] == [
        "retention_conflict:company_limit"
    ]
    assert out.ambiguities == []


def test_the_same_period_for_other_data_subjects_is_put_to_the_model() -> None:
    f = facts(
        company=COMPANY, policy=retention_policy("Appointment records are kept for ten years."),
        questionnaire=questionnaire(retention="10 years", data_subjects=["patients"]),
    )  # fmt: skip
    out = run_rules(f)
    assert not [x for x in out.findings if x.type == "retention_conflict"]
    assert len(out.ambiguities) == 1
    ambiguity = out.ambiguities[0]
    assert "120 months" in ambiguity.statement and ambiguity.passages == COMPANY.passages
    assert ambiguity.finding.type == "retention_conflict"


def test_periods_within_the_limit_or_open_ended_raise_nothing() -> None:
    within = facts(
        company=COMPANY,
        policy=retention_policy("Kept for 12 months."),
        questionnaire=questionnaire(retention="12 months"),
    )
    assert run_rules(within).ambiguities == [] and "retention_conflict" not in kinds(within)
    open_ended = facts(
        company=COMPANY,
        policy=retention_policy("Employment plus six years."),
        questionnaire=questionnaire(retention="Employment plus 6 years"),
    )
    assert "retention_conflict" not in kinds(open_ended) and run_rules(open_ended).ambiguities == []


def test_findings_carry_evidence_references() -> None:
    f = facts(elements=[element("billing_birthdate", "date_of_birth")])
    finding = run_rules(f).findings[0]
    assert {r.kind for r in finding.refs} == {"discovery", "policy"}
    assert all(r.ref_id for r in finding.refs)
