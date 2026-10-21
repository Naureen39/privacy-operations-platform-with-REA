"""Combining the rule layer and the embedding match into one decision, without any LLM.

1. A technical name (timestamp, status, tracker site id) with no personal-data word is not
   personal data.
2. A confident, unambiguous rule result is accepted. An embedding that agrees raises confidence.
3. Otherwise a clear embedding match (similarity and margin over the next category) is accepted.
4. Anything plausible but short of those thresholds stays unclassified and is queued for review.
"""

from dataclasses import dataclass, field

from app.classify.features import ElementFeatures
from app.classify.knowledge import Knowledge
from app.classify.rules import RuleEngine, RuleHit


@dataclass
class Decision:
    category: str | None
    confidence: float
    method: str  # rules | rules+embedding | embedding | non_personal | unclassified
    reasons: list[str] = field(default_factory=list)
    candidates: list[tuple[str, float]] = field(default_factory=list)
    needs_review: bool = False
    embedding_scores: list[tuple[str, float]] = field(default_factory=list)


def _rank(hits: dict[str, RuleHit]) -> list[tuple[str, float]]:
    return sorted(((c, h.score) for c, h in hits.items()), key=lambda item: item[1], reverse=True)


def decide(
    features: ElementFeatures,
    rules: RuleEngine,
    knowledge: Knowledge,
    embedding_scores: list[tuple[str, float]],
    hits: dict[str, RuleHit] | None = None,
) -> Decision:
    t = knowledge.thresholds
    hits = hits if hits is not None else rules.evaluate(features)
    ranked_rules = _rank(hits)
    rule_best = ranked_rules[0] if ranked_rules else (None, 0.0)
    rule_second = ranked_rules[1][1] if len(ranked_rules) > 1 else 0.0
    emb_best = embedding_scores[0] if embedding_scores else (None, 0.0)
    emb_second = embedding_scores[1][1] if len(embedding_scores) > 1 else 0.0

    candidates: dict[str, float] = {}
    for category, score in ranked_rules[:3]:
        candidates[category] = max(candidates.get(category, 0.0), score)
    for category, score in embedding_scores[:3]:
        candidates[category] = max(candidates.get(category, 0.0), score)
    top = sorted(candidates.items(), key=lambda item: item[1], reverse=True)[:3]

    if rules.non_personal(features) and rule_best[1] < t.rule_accept:
        return Decision(
            None,
            0.0,
            "non_personal",
            ["technical name without a personal data word"],
            candidates=top,
            embedding_scores=embedding_scores[:3],
        )

    reasons: list[str] = []
    if (
        rule_best[0]
        and rule_best[1] >= t.rule_accept
        and rule_best[1] - rule_second < t.rule_margin
        and len(ranked_rules) > 1
    ):
        # Rules tie between categories (a user id that holds e-mail addresses): the embedding breaks the tie.
        tied = {c for c, s in ranked_rules if rule_best[1] - s < t.rule_margin}
        by_embedding = [(c, s) for c, s in embedding_scores if c in tied]
        if by_embedding and by_embedding[0][1] >= t.embedding_accept - 0.1:
            category = by_embedding[0][0]
            confidence = round(min(0.95, (rule_best[1] + by_embedding[0][1]) / 2), 3)
            reasons.extend(hits[category].reasons)
            reasons.append(
                f"rules tied between {sorted(tied)}; embedding prefers {category} ({by_embedding[0][1]:.2f})"
            )
            return Decision(
                category,
                confidence,
                "rules+embedding",
                reasons,
                candidates=top,
                embedding_scores=embedding_scores[:3],
            )
    if (
        rule_best[0]
        and rule_best[1] >= t.rule_accept
        and rule_best[1] - rule_second >= t.rule_margin
    ):
        category = rule_best[0]
        confidence = rule_best[1]
        reasons.extend(hits[category].reasons)
        method = "rules"
        if emb_best[0] == category and emb_best[1] >= t.embedding_accept:
            confidence = min(0.99, confidence + 0.03)
            method = "rules+embedding"
            reasons.append(f"embedding agrees ({emb_best[1]:.2f})")
        return Decision(
            category,
            round(confidence, 3),
            method,
            reasons,
            candidates=top,
            embedding_scores=embedding_scores[:3],
        )

    if (
        emb_best[0]
        and emb_best[1] >= t.embedding_accept
        and emb_best[1] - emb_second >= t.embedding_margin
    ):
        category = emb_best[0]
        confidence = min(0.95, emb_best[1])
        method = "embedding"
        reasons.append(
            f"nearest taxonomy entry {emb_best[1]:.2f}, margin {emb_best[1] - emb_second:.2f}"
        )
        if rule_best[0] == category:
            confidence = min(0.97, confidence + 0.05)
            method = "rules+embedding"
            reasons.extend(hits[category].reasons)
        return Decision(
            category,
            round(confidence, 3),
            method,
            reasons,
            candidates=top,
            embedding_scores=embedding_scores[:3],
        )

    plausible = max(rule_best[1], emb_best[1]) >= t.review_floor
    return Decision(
        None,
        0.0,
        "unclassified",
        ["no category met the thresholds"] if plausible else ["no matching category"],
        needs_review=plausible,
        candidates=top,
        embedding_scores=embedding_scores[:3],
    )
