from dataclasses import replace

import pytest

from app.classify.decide import decide
from app.classify.embedder import DIMENSIONS, HashingEmbedder
from app.classify.engine import Classifier
from app.classify.features import ElementFeatures
from app.classify.index import MemoryMatcher, build_entries, category_scores
from app.classify.knowledge import default_knowledge, load_knowledge
from app.classify.normalize import contains_sequence, expand, split_identifier, strip_prefixes
from app.classify.rules import RuleEngine
from app.classify.special import detect_special
from app.classify.vendors import resolve_host

KNOWLEDGE = default_knowledge()
RULES = RuleEngine(KNOWLEDGE)


def features(name: str, **kwargs: object) -> ElementFeatures:
    return ElementFeatures(name=name, location_kind=str(kwargs.pop("location_kind", "request_json_key")), **kwargs)  # type: ignore[arg-type]


def classify_by_rules(name: str, **kwargs: object) -> str | None:
    """Decision with the embedding silenced, so that only the rule layer decides."""
    return decide(features(name, **kwargs), RULES, KNOWLEDGE, []).category


# --- names --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "tokens"),
    [
        ("billingEmail", ["billing", "email"]),
        ("billing_email", ["billing", "email"]),
        ("billing[email]", ["billing", "email"]),
        ("Billing-Email", ["billing", "email"]),
        ("contact.phone_number", ["contact", "phone", "number"]),
        ("address_1", ["address"]),
        ("HTTPStatusCode", ["http", "status", "code"]),
        ("ud[em]", ["ud", "em"]),
    ],
)
def test_split_identifier(name: str, tokens: list[str]) -> None:
    assert split_identifier(name) == tokens


def test_expand_and_prefixes() -> None:
    assert expand(["dob"]) == ["date", "of", "birth"] and expand(["tel", "no"]) == [
        "telephone",
        "no",
    ]
    assert strip_prefixes(["billing", "email"], ("billing",)) == ["email"]
    assert strip_prefixes(["billing"], ("billing",)) == ["billing"]  # never strip to nothing
    assert contains_sequence(["a", "b", "c"], ["b", "c"]) and not contains_sequence(
        ["a", "c", "b"], ["b", "c"]
    )


def test_description_contains_names_and_types_but_no_values() -> None:
    f = features(
        "billing_birthdate",
        label="Date of birth",
        autocomplete="bday",
        input_type="date",
        pattern_class="date",
        table="customers",
    )
    text = f.description()
    assert (
        "birthdate" in text
        and "labelled Date of birth" in text
        and "asks for date of birth" in text
    )
    assert "values look like date" in text and "in table customers" in text


# --- rule layer ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("billing_email", "contact_email"),
        ("subscriber_email", "contact_email"),
        ("phone", "contact_phone"),
        ("first_name", "name"),
        ("postcode", "postal_address"),
        ("ip_address", "ip_address"),  # beats the "address" word
        ("password_hash", "authentication_credentials"),
        ("order_total", "purchase_history"),
        ("diagnosis", "health_data"),
        ("union_member", "trade_union_membership"),
        ("ethnic_origin", "racial_ethnic_origin"),
    ],
)
def test_rules_decide_on_known_names(name: str, category: str) -> None:
    assert classify_by_rules(name) == category


def test_value_patterns_and_input_types_decide() -> None:
    assert classify_by_rules("x", pattern_class="email") == "contact_email"
    assert classify_by_rules("x", pattern_class="iban") == "bank_account"
    assert classify_by_rules("x", pattern_class="payment_card") == "payment_card"
    assert classify_by_rules("x", input_type="tel") == "contact_phone"
    assert classify_by_rules("x", input_type="password") == "authentication_credentials"
    assert classify_by_rules("x", autocomplete="bday") == "date_of_birth"
    assert classify_by_rules("x", autocomplete="section-shipping address-line1") == "postal_address"
    assert (
        classify_by_rules("when", pattern_class="date", input_type="date") is None
    )  # no birth word
    assert classify_by_rules("dob", pattern_class="date") == "date_of_birth"
    assert classify_by_rules("cookie_x", location_kind="cookie") == "online_identifier"


def test_a_value_pattern_beats_a_misleading_name() -> None:
    # `user_id` normally means an identifier, but these values are e-mail addresses.
    assert classify_by_rules("user_id") == "online_identifier"
    d = decide(
        features("user_id", pattern_class="email"),
        RULES,
        KNOWLEDGE,
        [("contact_email", 0.8), ("online_identifier", 0.7)],
    )
    assert d.category == "contact_email" and d.method == "rules+embedding"


def test_generic_words_do_not_decide_alone() -> None:
    assert classify_by_rules("contact_number") is None
    assert classify_by_rules("sort_order") is None
    assert (
        classify_by_rules("name_of_thing") is None or classify_by_rules("name_of_thing") == "name"
    )  # weak at most


@pytest.mark.parametrize(
    "name", ["created_at", "updated_ts", "status", "idsite", "http_status", "row_version"]
)
def test_technical_names_are_not_personal_data(name: str) -> None:
    d = decide(features(name), RULES, KNOWLEDGE, [("purchase_history", 0.7)])
    assert d.category is None and d.method == "non_personal"


def test_technical_name_with_personal_values_is_still_personal() -> None:
    assert (
        decide(features("id", pattern_class="hex_token"), RULES, KNOWLEDGE, []).method
        != "non_personal"
    )
    assert (
        decide(features("id", pattern_class="email"), RULES, KNOWLEDGE, []).category
        == "contact_email"
    )


# --- decisions ----------------------------------------------------------------------------------
def test_embedding_decides_when_rules_do_not() -> None:
    d = decide(
        features("zzzz"), RULES, KNOWLEDGE, [("geolocation", 0.82), ("browsing_behavior", 0.7)]
    )
    assert (d.category, d.method) == ("geolocation", "embedding") and 0.7 < d.confidence <= 0.95


def test_a_narrow_margin_or_low_similarity_stays_unclassified_for_review() -> None:
    narrow = decide(
        features("zzzz"), RULES, KNOWLEDGE, [("geolocation", 0.8), ("browsing_behavior", 0.79)]
    )
    assert narrow.category is None and narrow.method == "unclassified" and narrow.needs_review
    weak = decide(features("zzzz"), RULES, KNOWLEDGE, [("geolocation", 0.4)])
    assert weak.category is None and not weak.needs_review  # nothing plausible: no review noise


def test_thresholds_come_from_the_configuration() -> None:
    t = KNOWLEDGE.thresholds
    assert (
        0.5 <= t.rule_accept <= 0.95 and 0 < t.rule_margin < 0.3 and 0.5 < t.embedding_accept < 0.95
    )
    stricter = replace(KNOWLEDGE, thresholds=replace(t, embedding_accept=0.99))
    assert (
        decide(
            features("zzzz"), RULES, stricter, [("geolocation", 0.9), ("browsing_behavior", 0.5)]
        ).category
        is None
    )


# --- special categories -------------------------------------------------------------------------
def special(name: str, category: str | None = None, **kwargs: object) -> tuple[str, str] | None:
    result = detect_special(features(name, **kwargs), category, [], KNOWLEDGE, {})
    return (result.level, result.category_id) if result else None


def test_special_categories_by_words_and_category() -> None:
    assert special("diagnosis") == ("strong", "health_data")
    assert special("union_member") == ("strong", "trade_union_membership")
    assert special("x", label="Ethnic origin (optional)") == ("strong", "racial_ethnic_origin")
    assert special("x", category="biometric_data") == ("strong", "biometric_data")
    assert special("patient_email") == ("near", "health_data")  # a weak word only
    assert special("email") is None and special("created_at") is None


def test_columns_next_to_special_data_are_escalated_when_context_dependent() -> None:
    table = {"appointments": ("health_data", "Data concerning health")}
    near = detect_special(
        features("appointment_at", table="appointments"), None, [], KNOWLEDGE, table
    )
    assert near and near.level == "near" and "same table" in near.reason
    # An e-mail address means the same in any table; a technical column is not escalated either.
    assert (
        detect_special(
            features("email", table="appointments"), "contact_email", [], KNOWLEDGE, table
        )
        is None
    )
    assert (
        detect_special(
            features("status", table="appointments"), None, [], KNOWLEDGE, table, technical=True
        )
        is None
    )


def test_embedding_close_to_a_special_category_is_escalated() -> None:
    near = detect_special(
        features("zzzz"), None, [("health_data", 0.9), ("name", 0.6)], KNOWLEDGE, {}
    )
    assert near and near.level == "near" and near.category_id == "health_data"
    assert (
        detect_special(features("zzzz"), None, [("name", 0.9), ("health_data", 0.7)], KNOWLEDGE, {})
        is None
    )


# --- vendors ------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("host", "vendor", "role", "country"),
    [
        ("api.stripe.com", "Stripe", "processor", "US"),
        ("js.stripe.com", "Stripe", "processor", "US"),
        ("www.facebook.com", "Meta Platforms", "joint_controller", "US"),
        ("o4501.ingest.sentry.io", "Sentry", "processor", "US"),
        ("enrich.leadscope.example", "LeadScope Data", "processor", "IN"),
        ("cal.bookwell.example", "BookWell Scheduling", "processor", "NL"),
        ("FONTS.GOOGLEAPIS.COM.", "Google Fonts", "processor", "US"),
    ],
)
def test_vendor_resolution(host: str, vendor: str, role: str, country: str) -> None:
    r = resolve_host(host, KNOWLEDGE)
    assert (r.vendor, r.role, r.country, r.internal, r.known) == (
        vendor,
        role,
        country,
        False,
        True,
    )


def test_internal_unknown_and_lookalike_hosts() -> None:
    assert resolve_host("analytics.northbridge.example", KNOWLEDGE).internal
    assert resolve_host("northbridge.example", KNOWLEDGE).internal
    unknown = resolve_host("tracker.mystery-vendor.test", KNOWLEDGE)
    assert not unknown.known and unknown.vendor is None
    # A host that merely ends with a vendor's name is not that vendor.
    assert not resolve_host("notstripe.com", KNOWLEDGE).known
    assert not resolve_host("stripe.com.evil.test", KNOWLEDGE).known


# --- knowledge files ----------------------------------------------------------------------------
def test_knowledge_files_are_consistent() -> None:
    assert len(KNOWLEDGE.categories) >= 30 and len(KNOWLEDGE.special) == 8
    assert {c.id for c in KNOWLEDGE.categories.values() if c.special_category} == set(
        KNOWLEDGE.special
    )
    assert all(c.synonyms and c.definition for c in KNOWLEDGE.categories.values())
    assert load_knowledge().version == KNOWLEDGE.version
    entries = build_entries(KNOWLEDGE)
    assert {e.category_id for e in entries} == set(KNOWLEDGE.categories)
    assert len({(e.category_id, e.text) for e in entries}) == len(entries)  # no duplicates
    assert sum(e.kind == "label" for e in entries) == len(KNOWLEDGE.categories)


def test_classifier_runs_end_to_end_with_a_test_embedder() -> None:
    """Plumbing only: the hashing embedder has no sense of meaning."""
    embedder = HashingEmbedder()
    classifier = Classifier(KNOWLEDGE, embedder, MemoryMatcher(KNOWLEDGE, embedder))
    results = classifier.classify(
        [
            features("billing_email", location_kind="form_field", input_type="email"),
            features("diagnosis", table="visits"),
        ]
    )
    assert results[0].decision.category == "contact_email" and results[0].special is None
    assert results[1].special and results[1].special.level == "strong"
    assert len(results[0].vector) == DIMENSIONS
    assert classifier.classify([]) == []
    scores = category_scores(MemoryMatcher(KNOWLEDGE, embedder).top([results[0].vector])[0])
    assert scores == sorted(scores, key=lambda s: s[1], reverse=True)
