"""The classifier without a database: features in, decisions out."""

from dataclasses import dataclass

from app.classify.decide import Decision, decide
from app.classify.embedder import Embedder
from app.classify.features import ElementFeatures
from app.classify.index import Matcher, category_scores
from app.classify.knowledge import Knowledge
from app.classify.rules import RuleEngine
from app.classify.special import SpecialResult, detect_special


@dataclass
class ElementResult:
    features: ElementFeatures
    description: str
    vector: list[float]
    decision: Decision
    special: SpecialResult | None


class Classifier:
    def __init__(self, knowledge: Knowledge, embedder: Embedder, matcher: Matcher) -> None:
        self.knowledge = knowledge
        self.embedder = embedder
        self.matcher = matcher
        self.rules = RuleEngine(knowledge)

    def classify(self, features: list[ElementFeatures]) -> list[ElementResult]:
        """Classify the elements of one system (table level inferences stay inside the batch)."""
        if not features:
            return []
        descriptions = [f.description() for f in features]
        vectors = self.embedder.embed(descriptions)
        scores = [category_scores(m) for m in self.matcher.top(vectors)]
        decisions = [
            decide(f, self.rules, self.knowledge, s) for f, s in zip(features, scores, strict=True)
        ]

        first_pass = [
            detect_special(f, d.category, s, self.knowledge, {}, d.method == "non_personal")
            for f, d, s in zip(features, decisions, scores, strict=True)
        ]
        table_special = {
            f.table: (sp.category_id, sp.label)
            for f, sp in zip(features, first_pass, strict=True)
            if sp and sp.level == "strong" and f.table
        }
        results = []
        for f, d, s, desc, vec in zip(
            features, decisions, scores, descriptions, vectors, strict=True
        ):
            special = detect_special(
                f, d.category, s, self.knowledge, table_special, d.method == "non_personal"
            )
            results.append(ElementResult(f, desc, vec, d, special))
        return results
