"""Score the findings against the contradictions seeded in the reference estate."""

import json
from dataclasses import dataclass, field
from pathlib import Path

DATASETS = Path(__file__).resolve().parents[3] / "datasets"
SEEDED_FILE = DATASETS / "expected" / "contradictions.json"
# Finding types that claim a contradiction or gap. Review items ("retention_review") and missing
# evidence are not claims and are not scored.
SCORED_TYPES = frozenset(
    {
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
    }
)

Pair = tuple[str, str]  # (system id, finding type)


def load_seeded(path: Path = SEEDED_FILE) -> dict[str, set[Pair]]:
    """Seeded contradiction id -> the (system, type) pairs a correct run reports for it."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {c["id"]: {(c["system"], t) for t in c["types"]} for c in data["items"]}


@dataclass
class Score:
    seeded_ids: int
    found_ids: int
    seeded_pairs: int
    true_pairs: int
    reported_pairs: int
    missed: list[str] = field(default_factory=list)
    extra: list[Pair] = field(default_factory=list)

    @property
    def recall(self) -> float:
        """Share of seeded contradictions with every expected finding type reported."""
        return self.found_ids / self.seeded_ids if self.seeded_ids else 0.0

    @property
    def pair_recall(self) -> float:
        return self.true_pairs / self.seeded_pairs if self.seeded_pairs else 0.0

    @property
    def precision(self) -> float:
        return self.true_pairs / self.reported_pairs if self.reported_pairs else 0.0


def score(reported: set[Pair], seeded: dict[str, set[Pair]] | None = None) -> Score:
    seeded = seeded or load_seeded()
    reported = {p for p in reported if p[1] in SCORED_TYPES}
    expected = set().union(*seeded.values())
    missed = sorted(cid for cid, pairs in seeded.items() if not pairs <= reported)
    return Score(
        seeded_ids=len(seeded),
        found_ids=len(seeded) - len(missed),
        seeded_pairs=len(expected),
        true_pairs=len(reported & expected),
        reported_pairs=len(reported),
        missed=missed,
        extra=sorted(reported - expected),
    )
