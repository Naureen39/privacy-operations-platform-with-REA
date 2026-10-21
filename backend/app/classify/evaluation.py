"""Evaluation and threshold tuning for the classifier on the reference estate.

Candidates come from the built in discovery parsers over the estate's evidence and are labelled
from the estate ground truth. The tuning set and the held-out set are disjoint systems, and the
challenge set (hand written names) is never used to choose thresholds.
"""

import json
import tempfile
from dataclasses import dataclass, field, replace
from itertools import product
from pathlib import Path
from typing import Any

from app.classify.decide import Decision, decide
from app.classify.embedder import Embedder
from app.classify.features import ElementFeatures
from app.classify.index import Matcher, category_scores
from app.classify.knowledge import Knowledge, Thresholds
from app.classify.rules import RuleEngine
from app.classify.special import SpecialResult, detect_special
from app.core.config import Settings
from app.db.enums import EvidenceKind
from app.discovery.candidates import ElementCandidate
from app.discovery.executor import Executor

DATASETS = Path(__file__).resolve().parents[3] / "datasets"
ESTATE = DATASETS / "estate"
SYSTEM_IDS = (
    "web_shop", "web_analytics", "helpdesk", "crm", "clinic_portal", "newsletter", "staff_desktop", "hr_onboarding",
)  # fmt: skip
# Held out from tuning: a modeled analytics product, a modeled CRM and the Electron client.
HELD_OUT = ("web_analytics", "crm", "staff_desktop")
TUNING = tuple(s for s in SYSTEM_IDS if s not in HELD_OUT)

FILES = [
    (EvidenceKind.HAR, "capture.har"),
    (EvidenceKind.WEBSITE, "website_snapshot.html"),
    (EvidenceKind.JAVASCRIPT_BUNDLE, None),
    (EvidenceKind.SQLITE_SNAPSHOT, "snapshot.sqlite"),
]


@dataclass
class Example:
    system_id: str
    features: ElementFeatures
    category: (
        str | None
    )  # ground truth category; None when the candidate is not a labelled location
    special: bool
    technical: bool = False  # a name that must not be classified as personal data


def _location_key(location: dict[str, str]) -> tuple[str, ...]:
    if location["kind"] == "db_column":
        return ("db_column", location["table"], location["column"])
    return (location["kind"], location["name"])


def _candidate_key(candidate: ElementCandidate) -> tuple[str, ...]:
    if candidate.location_kind == "db_column":
        return ("db_column", candidate.context["table"], candidate.name)
    return (candidate.location_kind, candidate.name)


def estate_examples(estate: Path = ESTATE) -> list[Example]:
    examples: list[Example] = []
    with tempfile.TemporaryDirectory() as staging:
        executor = Executor(Settings(rea_enabled=False, rea_input_dir=staging), None)
        for system_id in SYSTEM_IDS:
            truth = json.loads(
                (estate / system_id / "ground_truth.json").read_text(encoding="utf-8")
            )
            labels = {
                _location_key(loc): (e["category"], e["special_category"])
                for e in truth["data_elements"]
                for loc in e["locations"]
            }
            seen: set[tuple[str, str, str]] = set()
            own_host: str | None = None
            for kind, name in FILES:
                filename = name or (
                    "main.bundle.js" if system_id == "staff_desktop" else "app.bundle.js"
                )
                data = (estate / system_id / "evidence" / filename).read_bytes()
                for extraction in executor.process(kind, filename, data, own_host):
                    for note in extraction.notes:
                        if note.startswith("own_host=") and note != "own_host=None":
                            own_host = note.split("=", 1)[1]
                    for candidate in extraction.elements:
                        identity = (candidate.location_kind, candidate.path, candidate.name)
                        if identity in seen:
                            continue
                        seen.add(identity)
                        category, special = labels.get(_candidate_key(candidate), (None, False))
                        examples.append(
                            Example(
                                system_id,
                                ElementFeatures.from_context(
                                    candidate.name,
                                    {**candidate.context, "location_kind": candidate.location_kind},
                                    data_type=candidate.data_type,
                                    pattern_class=candidate.pattern_class,
                                    source_kind=kind.value,
                                ),
                                category,
                                special,
                            )
                        )
    return examples


def challenge_examples(path: Path | None = None) -> list[Example]:
    data = json.loads(
        (path or DATASETS / "evaluation" / "classification_challenge.json").read_text(
            encoding="utf-8"
        )
    )
    return [
        Example(
            "challenge",
            ElementFeatures(name=i["name"], location_kind="request_json_key"),
            i["category"],
            False,
            technical=i["category"] is None,
        )
        for i in data["items"]
    ]


@dataclass
class Prepared:
    """Everything that does not depend on the thresholds, computed once."""

    example: Example
    scores: list[tuple[str, float]]
    hits: dict[str, Any]


def prepare(
    examples: list[Example], knowledge: Knowledge, embedder: Embedder, matcher: Matcher
) -> list[Prepared]:
    rules = RuleEngine(knowledge)
    vectors = embedder.embed([e.features.description() for e in examples])
    scores = [category_scores(m) for m in matcher.top(vectors)]
    return [
        Prepared(e, s, rules.evaluate(e.features)) for e, s in zip(examples, scores, strict=True)
    ]


@dataclass
class Metrics:
    labelled: int = 0
    correct: int = 0
    wrong: int = 0
    abstained: int = 0
    technical: int = 0
    technical_false_positives: int = 0
    special_total: int = 0
    special_flagged: int = 0
    special_strong: int = 0
    special_extra: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.labelled if self.labelled else 1.0

    @property
    def coverage(self) -> float:
        return (self.correct + self.wrong) / self.labelled if self.labelled else 1.0

    @property
    def special_recall(self) -> float:
        return self.special_flagged / self.special_total if self.special_total else 1.0

    def objective(self) -> float:
        """Correct answers count, wrong ones cost three times as much (unclassified goes to review),
        and a missed special category is unacceptable."""
        score = (
            self.correct
            - 3 * self.wrong
            - 0.5 * self.technical_false_positives
            - 0.15 * self.special_extra
        )
        return score - (1000 if self.special_flagged < self.special_total else 0)


def evaluate(
    prepared: list[Prepared], knowledge: Knowledge
) -> tuple[Metrics, list[tuple[Prepared, Decision, SpecialResult | None]]]:
    rules = RuleEngine(knowledge)
    decisions = [decide(p.example.features, rules, knowledge, p.scores, p.hits) for p in prepared]
    first = [
        detect_special(
            p.example.features, d.category, p.scores, knowledge, {}, d.method == "non_personal"
        )
        for p, d in zip(prepared, decisions, strict=True)
    ]
    table_special: dict[tuple[str, str], tuple[str, str]] = {}
    for p, sp in zip(prepared, first, strict=True):
        if sp and sp.level == "strong" and p.example.features.table:
            table_special[(p.example.system_id, p.example.features.table)] = (
                sp.category_id,
                sp.label,
            )
    metrics = Metrics()
    detail = []
    for p, d in zip(prepared, decisions, strict=True):
        per_system = {t: v for (sid, t), v in table_special.items() if sid == p.example.system_id}
        sp = detect_special(
            p.example.features,
            d.category,
            p.scores,
            knowledge,
            per_system,
            d.method == "non_personal",
        )
        ex = p.example
        detail.append((p, d, sp))
        if ex.category:
            metrics.labelled += 1
            if d.category == ex.category:
                metrics.correct += 1
            elif d.category is None:
                metrics.abstained += 1
                metrics.errors.append(
                    f"{ex.system_id}:{ex.features.name}: unclassified (wanted {ex.category})"
                )
            else:
                metrics.wrong += 1
                metrics.errors.append(
                    f"{ex.system_id}:{ex.features.name}: {d.category} (wanted {ex.category})"
                )
        if ex.technical:
            metrics.technical += 1
            if d.category:
                metrics.technical_false_positives += 1
        if ex.special:
            metrics.special_total += 1
            metrics.special_flagged += bool(sp)
            metrics.special_strong += bool(sp and sp.level == "strong")
        elif sp and ex.category is not None:
            metrics.special_extra += 1
    return metrics, detail


GRID = {
    "rule_accept": (0.75, 0.8, 0.85),
    "rule_margin": (0.04, 0.08, 0.12),
    "embedding_accept": (0.66, 0.70, 0.74, 0.78),
    "embedding_margin": (0.02, 0.04, 0.06),
    "special_near": (0.70, 0.74, 0.78, 0.82, 0.86),
}


def tune(prepared: list[Prepared], knowledge: Knowledge) -> tuple[Thresholds, Metrics]:
    """Grid search on the prepared tuning examples; ties go to the stricter (higher) thresholds."""
    best: tuple[float, tuple[float, ...], Thresholds, Metrics] | None = None
    for values in product(*GRID.values()):
        overrides: dict[str, Any] = dict(zip(GRID, values, strict=True))
        candidate = replace(knowledge.thresholds, **overrides)
        metrics, _ = evaluate(prepared, replace(knowledge, thresholds=candidate))
        key = (metrics.objective(), values)
        if best is None or key > (best[0], best[1]):
            best = (metrics.objective(), values, candidate, metrics)
    if best is None:
        raise ValueError("nothing to tune")
    return best[2], best[3]
