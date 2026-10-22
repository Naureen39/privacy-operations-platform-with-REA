"""Screening criteria, the risk matrix and the catalogue (no database, no model)."""

import json

import pytest

from app.dpia import matrix
from app.dpia.draft import CATALOGUE
from app.dpia.screening import (
    KEYWORDS,
    Scale,
    ScreeningInput,
    countries_in,
    keyword_hits,
    load_criteria,
    screen,
)
from app.fusion.facts import ElementFact, RecipientFact, Ref

CRITERIA = load_criteria()
REF = Ref("discovery", "e1", "thing")
ACTIVITY_REF = Ref("record", "a1", "record")


def element(
    name: str, category: str, *, stored: bool = True, special: bool = False, table: str = "t"
) -> ElementFact:
    return ElementFact(
        name=name, category=category, special=special,
        location_kind="db_column" if stored else "third_party_param", table=table if stored else None,
        pattern_class=None, checked_by_default=False, input_type=None, record_months=None,
        confidence=0.95, reviewed=False, ref=REF,
    )  # fmt: skip


def recipient(vendor: str, category: str | None = None, internal: bool = False) -> RecipientFact:
    return RecipientFact(
        vendor, f"{vendor.lower()}.example", "processor", "US", internal, REF, category
    )


def screening(**kw: object) -> ScreeningInput:
    base: dict[str, object] = {
        "name": "Shop", "description": "", "data_subjects": ["customers"], "purposes": ["Order fulfilment"],
        "extra_text": [], "elements": [], "recipients": [], "special_categories": [], "categories": [],
        "scale": Scale(data_subjects_estimate=50, countries=1), "activity_ref": ACTIVITY_REF,
    }  # fmt: skip
    return ScreeningInput(**{**base, **kw})  # type: ignore[arg-type]


def results(**kw: object) -> dict[str, bool | None]:
    return {r.id: r.met for r in screen(screening(**kw), CRITERIA).results}


def test_the_criteria_file_is_loaded_with_its_threshold() -> None:
    assert CRITERIA.threshold == 2 and CRITERIA.version == 1
    assert [c.id for c in CRITERIA.criteria] == [
        "evaluation_scoring", "automated_decisions", "systematic_monitoring", "sensitive_data",
        "large_scale", "combining_datasets", "vulnerable_subjects", "innovative_technology",
        "prevents_exercise_of_rights",
    ]  # fmt: skip
    assert "two or more criteria" in CRITERIA.rule.lower()


def test_a_plain_activity_meets_nothing() -> None:
    result = screen(screening(), CRITERIA)
    assert result.met == 0 and result.unknown == 0 and not result.required and not result.undecided
    assert all(r.basis for r in result.results)


def test_sensitive_data_from_special_categories_or_other_highly_personal_data() -> None:
    assert results(special_categories=["health_data"])["sensitive_data"] is True
    assert results(categories=["national_id"])["sensitive_data"] is True
    assert results(categories=["bank_account"])["sensitive_data"] is True
    assert results(categories=["payment_card", "name"])["sensitive_data"] is False


@pytest.mark.parametrize(
    ("subjects", "met"),
    [
        (["patients"], True),
        (["employees"], True),
        (["staff"], True),
        (["children"], True),
        (["customers"], False),
        (["website visitors", "subscribers"], False),
        ([], False),
    ],
)
def test_vulnerable_subjects(subjects: list[str], met: bool) -> None:
    assert results(data_subjects=subjects)["vulnerable_subjects"] is met


def test_monitoring_needs_stored_location_or_browsing_data() -> None:
    assert (
        results(elements=[element("clock_in_location", "geolocation")])["systematic_monitoring"]
        is True
    )
    assert results(elements=[element("page", "browsing_behavior")])["systematic_monitoring"] is True
    # seen only in a request to a third party: not monitoring by this system
    assert (
        results(elements=[element("action_name", "browsing_behavior", stored=False)])[
            "systematic_monitoring"
        ]
        is False
    )
    assert results(purposes=["CCTV surveillance of the car park"])["systematic_monitoring"] is True


def test_large_scale_from_people_countries_or_unknown() -> None:
    assert results(scale=Scale(data_subjects_estimate=1000))["large_scale"] is True
    assert results(scale=Scale(data_subjects_estimate=999))["large_scale"] is False
    assert results(scale=Scale(countries=3))["large_scale"] is True
    assert (
        results(scale=Scale(), description="Online store for consumers in five countries.")[
            "large_scale"
        ]
        is True
    )
    unknown = screen(screening(scale=Scale()), CRITERIA)
    scale = next(r for r in unknown.results if r.id == "large_scale")
    assert scale.met is None and "estimate" in (scale.needs or "")
    assert unknown.unknown == 1


def test_unknown_criteria_make_a_borderline_activity_undecided() -> None:
    result = screen(screening(scale=Scale(), data_subjects=["patients"]), CRITERIA)
    assert result.met == 1 and result.unknown == 1 and not result.required and result.undecided
    decided = screen(
        screening(scale=Scale(data_subjects_estimate=10), data_subjects=["patients"]), CRITERIA
    )
    assert not decided.undecided


def test_combining_datasets_from_enrichment_vendors_or_text() -> None:
    assert (
        results(recipients=[recipient("LeadScope Data", "enrichment")])["combining_datasets"]
        is True
    )
    assert (
        results(recipients=[recipient("LeadScope Data", "enrichment", internal=True)])[
            "combining_datasets"
        ]
        is False
    )
    assert (
        results(extra_text=["seniority and company size added from business data sources"])[
            "combining_datasets"
        ]
        is True
    )
    assert results(recipients=[recipient("Stripe", "payments")])["combining_datasets"] is False


def test_innovative_technology() -> None:
    assert results(categories=["biometric_data"])["innovative_technology"] is True
    assert results(purposes=["Facial recognition at the entrance"])["innovative_technology"] is True
    assert results()["innovative_technology"] is False


@pytest.mark.parametrize(
    ("criterion", "text"),
    [
        ("evaluation_scoring", "We use profiling to rank leads."),
        ("evaluation_scoring", "Credit scoring of applicants"),
        ("automated_decisions", "Automated decision making approves loans"),
        ("prevents_exercise_of_rights", "Eligibility check for the discount scheme"),
    ],
)
def test_keyword_criteria_use_the_purposes(criterion: str, text: str) -> None:
    assert results(purposes=[text])[criterion] is True


def test_a_profile_page_is_not_profiling_and_negation_is_respected() -> None:
    assert (
        results(description="Desktop client for staff to view their profile")["evaluation_scoring"]
        is False
    )
    assert (
        results(extra_text=["We do not use profiling or automated decision making."])[
            "evaluation_scoring"
        ]
        is False
    )
    assert results(extra_text=["We never use automated decisions."])["automated_decisions"] is False
    assert keyword_hits(
        KEYWORDS["evaluation_scoring"], ["No scoring is done. But we use scoring for fraud."]
    ) == ["But we use scoring for fraud."]


def test_an_analyst_can_state_a_criterion_the_evidence_cannot_show() -> None:
    out = screen(
        screening(scale=Scale(data_subjects_estimate=10, flags=["automated_decisions"])), CRITERIA
    )
    by_id = {r.id: r for r in out.results}
    assert (
        by_id["automated_decisions"].met is True
        and by_id["automated_decisions"].refs[0].kind == "manual"
    )
    assert by_id["evaluation_scoring"].met is False


def test_two_criteria_mean_an_assessment_is_likely_required() -> None:
    one = screen(screening(data_subjects=["patients"]), CRITERIA)
    two = screen(
        screening(data_subjects=["patients"], special_categories=["health_data"]), CRITERIA
    )
    assert not one.required and one.met == 1
    assert (
        two.required
        and two.met == 2
        and sorted(two.met_ids()) == ["sensitive_data", "vulnerable_subjects"]
    )


@pytest.mark.parametrize(
    ("text", "n"),
    [
        ("in five countries", 5),
        ("across 12 countries", 12),
        ("one country", None),
        ("worldwide", None),
        ("in three Countries", 3),
    ],
)
def test_countries_in_a_description(text: str, n: int | None) -> None:
    assert countries_in(text) == n


def test_matrix_bands_cover_every_cell() -> None:
    bands = {(lk, s): matrix.level(lk, s) for lk in range(1, 6) for s in range(1, 6)}
    assert bands[(1, 1)] == "low" and bands[(2, 2)] == "low" and bands[(1, 5)] == "medium"
    assert bands[(3, 3)] == "medium" and bands[(3, 4)] == "high" and bands[(4, 4)] == "very_high"
    assert bands[(5, 5)] == "very_high" and bands[(2, 5)] == "high" and bands[(3, 5)] == "high"
    assert {matrix.level(lk, s) for lk in range(1, 6) for s in range(1, 6)} == set(matrix.LEVELS)
    assert matrix.worst(["low", "high", "medium"]) == "high" and matrix.worst([]) is None


def test_the_matrix_grid_puts_severity_on_rows_and_likelihood_on_columns() -> None:
    cells = matrix.grid([(1, 5), (5, 1), (3, 3), (3, 3)])
    assert cells[0][0] == 1  # severity 5, likelihood 1: top left
    assert cells[4][4] == 1  # severity 1, likelihood 5: bottom right
    assert cells[2][2] == 2 and sum(map(sum, cells)) == 4


def test_the_risk_catalogue_covers_every_criterion_and_the_gaps() -> None:
    ids = {c.id for c in CRITERIA.criteria}
    assert ids <= set(CATALOGUE) and {"transfer_gap", "agreement_gap"} <= set(CATALOGUE)
    for key, entry in CATALOGUE.items():
        assert 1 <= entry["likelihood"] <= 5 and 1 <= entry["severity"] <= 5, key
        assert entry["title"] and entry["mitigation"] and entry["articles"] and entry["query"], key
        assert len(entry["title"]) < 300
        assert chr(0x2014) not in json.dumps(entry) and chr(0x2013) not in json.dumps(entry)
