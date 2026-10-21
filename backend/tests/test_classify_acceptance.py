"""Phase 5 acceptance on the reference estate: at least 90 percent category accuracy with no LLM
call, every special category element flagged, vendors resolved from the registry."""

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from app.classify import evaluation
from app.classify.embedder import SentenceTransformerEmbedder
from app.classify.evaluation import HELD_OUT, TUNING, Metrics, Prepared
from app.classify.index import MemoryMatcher
from app.classify.knowledge import DEFAULT_DIR, default_knowledge
from app.classify.vendors import resolve_host

KNOWLEDGE = default_knowledge()
ESTATE = evaluation.ESTATE


@pytest.fixture(scope="module")
def matcher(real_embedder: SentenceTransformerEmbedder) -> MemoryMatcher:
    return MemoryMatcher(KNOWLEDGE, real_embedder)


@pytest.fixture(scope="module")
def prepared(real_embedder: SentenceTransformerEmbedder, matcher: MemoryMatcher) -> list[Prepared]:
    return evaluation.prepare(evaluation.estate_examples(), KNOWLEDGE, real_embedder, matcher)


def metrics_for(items: list[Prepared], knowledge=KNOWLEDGE) -> Metrics:  # type: ignore[no-untyped-def]
    return evaluation.evaluate(items, knowledge)[0]


def test_category_accuracy_is_at_least_ninety_percent_without_an_llm(
    prepared: list[Prepared],
) -> None:
    m = metrics_for(prepared)
    assert m.labelled >= 200
    assert m.accuracy >= 0.90, m.errors
    assert (
        m.wrong <= 2
    ), m.errors  # an unsure element goes to review rather than getting a wrong label
    assert m.technical_false_positives == 0


def test_tuning_and_held_out_systems_are_disjoint_and_both_pass(prepared: list[Prepared]) -> None:
    assert set(TUNING).isdisjoint(HELD_OUT) and len(TUNING) + len(HELD_OUT) == 8
    tuned = metrics_for([p for p in prepared if p.example.system_id in TUNING])
    held = metrics_for([p for p in prepared if p.example.system_id in HELD_OUT])
    assert tuned.accuracy >= 0.9 and held.accuracy >= 0.9, (tuned.errors, held.errors)
    assert held.labelled >= 50


def test_every_special_category_element_in_ground_truth_is_flagged(
    prepared: list[Prepared],
) -> None:
    m = metrics_for(prepared)
    assert m.special_total == 17
    assert m.special_flagged == m.special_total, "a special category element was not escalated"
    assert m.special_strong >= 16  # at most the health-adjacent appointment time is only "near"
    assert m.special_extra <= 6, "too many harmless elements are escalated"


def test_stored_thresholds_record_how_they_were_tuned() -> None:
    config = json.loads(
        (DEFAULT_DIR / "taxonomy" / "classifier_config.json").read_text(encoding="utf-8")
    )
    meta = config["meta"]
    assert config["version"].endswith("tuned")
    assert meta["embedding_model"] == "BAAI/bge-small-en-v1.5"
    assert set(meta["tuned_on"]) == set(TUNING) and set(meta["held_out"]) == set(HELD_OUT)
    assert (
        meta["metrics"]["held_out"]["accuracy"] >= 0.9
        and meta["metrics"]["held_out"]["special_recall"] == 1.0
    )
    assert meta["metrics"]["challenge"]["accuracy"] >= 0.85
    # The stored numbers are what the stored thresholds actually produce.


def test_challenge_set_of_unseen_names(
    real_embedder: SentenceTransformerEmbedder, matcher: MemoryMatcher
) -> None:
    items = evaluation.prepare(evaluation.challenge_examples(), KNOWLEDGE, real_embedder, matcher)
    m = metrics_for(items)
    assert m.labelled >= 70 and m.accuracy >= 0.85, m.errors
    assert m.technical >= 9 and m.technical_false_positives == 0


def test_rules_and_embeddings_each_contribute(prepared: list[Prepared]) -> None:
    t = KNOWLEDGE.thresholds
    rules_only = metrics_for(
        prepared, replace(KNOWLEDGE, thresholds=replace(t, embedding_accept=2.0))
    )
    embedding_only = metrics_for(
        prepared, replace(KNOWLEDGE, thresholds=replace(t, rule_accept=2.0))
    )
    both = metrics_for(prepared)
    print(f"\n[ablation] rules only {rules_only.accuracy:.1%} (wrong {rules_only.wrong}), "
          f"embedding only {embedding_only.accuracy:.1%} (wrong {embedding_only.wrong}), both {both.accuracy:.1%} (wrong {both.wrong})")  # fmt: skip
    assert both.accuracy >= max(rules_only.accuracy, embedding_only.accuracy)
    assert embedding_only.accuracy >= 0.5, "embeddings alone should recover most names"
    assert rules_only.accuracy >= 0.7


def test_classification_code_never_calls_an_llm() -> None:
    import ast

    # Only standard library modules, the project itself, the database layer, YAML and the embedding
    # library may be imported: no model provider and no HTTP client.
    allowed = set(sys.stdlib_module_names) | {
        "app",
        "sqlalchemy",
        "yaml",
        "sentence_transformers",
        "__future__",
    }
    for path in (Path(__file__).resolve().parents[1] / "app" / "classify").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported <= allowed, (path.name, imported - allowed)


def test_vendor_resolution_matches_ground_truth_for_every_estate_host() -> None:
    checked = 0
    for system_id in evaluation.SYSTEM_IDS:
        truth = json.loads((ESTATE / system_id / "ground_truth.json").read_text(encoding="utf-8"))
        for recipient in truth["recipients"]:
            for host in recipient["hosts"]:
                resolution = resolve_host(host, KNOWLEDGE)
                checked += 1
                if recipient["internal"]:
                    assert resolution.internal, host
                else:
                    assert (resolution.vendor, resolution.role, resolution.country) == (
                        recipient["vendor"], recipient["role"], recipient["country"]
                    ), host  # fmt: skip
                    assert not resolution.internal
    assert checked == 19
