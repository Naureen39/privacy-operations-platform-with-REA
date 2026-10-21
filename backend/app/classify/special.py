"""Article 9 detection. Anything that matches or is near a special category is escalated for human
review whatever the classifier's confidence.

Strong: the element is itself special category data (decided category, or its name or label
matches a special category synonym). Near: it is probably not special on its own but touches one
(a patient's contact detail, a column in a table that also holds health data, or an embedding
that sits close to a special category).
"""

from dataclasses import dataclass

from app.classify.features import ElementFeatures
from app.classify.knowledge import Knowledge
from app.classify.normalize import contains_sequence, expand, split_identifier

# Words that point at a special category only weakly (they often qualify something else).
WEAK_SPECIAL_WORDS = {"patient", "origin", "party", "condition", "clinical", "sick", "religious"}


# Categories whose meaning depends on where they sit. A name or an IBAN is the same in any table, but
# an appointment time, a doctor or an unclassified column next to health data may reveal health.
CONTEXT_DEPENDENT = {
    "purchase_history",
    "browsing_behavior",
    "consent_record",
    "preferences",
    "employment_data",
    "communications_content",
    "geolocation",
}


@dataclass(frozen=True)
class SpecialResult:
    level: str  # strong | near
    category_id: str
    label: str
    reason: str


def _special_by_words(features: ElementFeatures, knowledge: Knowledge) -> SpecialResult | None:
    texts = [features.tokens, split_identifier(features.label or "")]
    for tokens in texts:
        words = tokens + expand(tokens)
        for special in knowledge.special.values():
            for synonym in special.synonyms:
                syn = split_identifier(synonym)
                if not syn:
                    continue
                matched = contains_sequence(tokens, syn) or contains_sequence(words, syn)
                if not matched:
                    continue
                weak = len(syn) == 1 and syn[0] in WEAK_SPECIAL_WORDS
                if weak:
                    return SpecialResult(
                        "near",
                        special.id,
                        special.label,
                        f"weak word '{synonym}' in the name or label",
                    )
                return SpecialResult(
                    "strong",
                    special.id,
                    special.label,
                    f"matches special category word '{synonym}'",
                )
    return None


def detect_special(
    features: ElementFeatures,
    category: str | None,
    embedding_scores: list[tuple[str, float]],
    knowledge: Knowledge,
    table_special: dict[str, tuple[str, str]],
    technical: bool = False,
) -> SpecialResult | None:
    """`table_special` maps a table name to (special category id, label) when another column of
    that table is strong special category data."""
    if category and knowledge.categories[category].special_category:
        special = knowledge.special.get(category)
        label = special.label if special else knowledge.categories[category].label
        return SpecialResult("strong", category, label, "classified as a special category")
    by_words = _special_by_words(features, knowledge)
    if by_words:
        return by_words

    threshold = knowledge.thresholds.special_near
    scores = dict(embedding_scores)
    special_best = max(
        ((c, s) for c, s in scores.items() if knowledge.categories[c].special_category),
        key=lambda i: i[1],
        default=None,
    )
    other_best = max(
        (s for c, s in scores.items() if not knowledge.categories[c].special_category), default=0.0
    )
    if special_best and special_best[1] >= threshold and special_best[1] >= other_best - 0.10:
        special = knowledge.special.get(special_best[0])
        label = special.label if special else knowledge.categories[special_best[0]].label
        return SpecialResult(
            "near",
            special_best[0],
            label,
            f"embedding is close to {special_best[0]} ({special_best[1]:.2f})",
        )

    if (
        features.table
        and features.table in table_special
        and not technical
        and (category is None or category in CONTEXT_DEPENDENT)
    ):
        special_id, label = table_special[features.table]
        return SpecialResult("near", special_id, label, f"same table as {special_id} data")
    return None
