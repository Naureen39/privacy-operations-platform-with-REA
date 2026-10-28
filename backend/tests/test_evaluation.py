"""The evaluation: every figure of docs/evaluation.md, measured on the reference estate.

Run it with `scripts/eval_run.py` (which also renders the document). Each test measures one thing,
records the figures in a results file, and asserts the acceptance thresholds of the plan, so the
evaluation fails loudly if the platform gets worse. The language model is scripted (it answers every
task with a valid object and counts the tokens of the prompts the platform really builds); nothing
here measures the quality of a real model's prose.
"""

import json
import os
import platform
import statistics
import sys
import time
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.classify import evaluation as classify_eval
from app.classify.embedder import SentenceTransformerEmbedder
from app.classify.index import MemoryMatcher
from app.classify.knowledge import default_knowledge
from app.core.config import Settings
from app.db.session import TenantContext, TenantSession, set_tenant
from app.fusion.evaluation import score as fusion_score
from app.knowledge.evaluation import evaluate_recall, load_gold
from app.knowledge.retrieval import HybridRetriever
from app.llm.budget import JobBudget
from app.llm.router import LLMRouter, ProviderLimits
from app.llm.tasks import Scope, answer_question
from tests.discovery_scoring import SYSTEM_IDS, aggregate, element_keys, ground_truth, location_key
from tests.fixtures_fusion import FusionEstate
from tests.fixtures_knowledge import KnowledgeOrg
from tests.llm_support import FakeClock, TaskAwareProvider
from tests.rea_support import rea_unavailable_reason
from tests.test_discovery_acceptance import EstateRun, run_estate
from tests.test_dpia_acceptance import RUBRIC, people_in
from tests.test_dsar_acceptance import CASES, email_of, locations, prepared
from tests.test_llm_onboarding import BUDGET, onboard, setup  # noqa: F401  (setup is a fixture)
from tests.test_records import REQUIRED_FIELDS

DATASETS = Path(__file__).resolve().parents[2] / "datasets"
OUT = Path(
    os.environ.get("EVAL_OUT", Path(__file__).resolve().parents[1] / ".eval" / "results.json")
)
RESULTS: dict[str, Any] = {}
KNOWLEDGE = default_knowledge()


def record(section: str, value: Any) -> None:
    RESULTS[section] = value


@pytest.fixture(scope="module", autouse=True)
def write_results() -> Iterator[None]:
    yield
    OUT.parent.mkdir(parents=True, exist_ok=True)
    RESULTS["environment"] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "rea_available": rea_unavailable_reason() is None,
        "providers": "scripted (no provider keys were used)",
    }
    OUT.write_text(json.dumps(RESULTS, indent=1, sort_keys=True, default=str), encoding="utf-8")


def pct(a: int | float, b: int | float) -> float:
    return round(100 * a / b, 1) if b else 100.0


# -- discovery: recall and precision by kind of evidence, REA against the fallback parsers -------


def discovery_figures(run: EstateRun) -> dict[str, Any]:
    kinds: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"truth": 0, "found": 0, "candidates": 0, "matched": 0, "evidence": set()}
    )
    for system_id in SYSTEM_IDS:
        truth = ground_truth(system_id)
        truth_keys: dict[str, set[tuple[str, ...]]] = defaultdict(set)
        for element in truth["data_elements"]:
            for loc in element["locations"]:
                truth_keys[loc["kind"]].add(location_key(loc))
        candidates = []
        for x in run.extractions[system_id]:
            if x.status != "ok":
                continue
            for c in x.elements:
                candidates.append(c)
                kinds[c.location_kind]["evidence"].add(x.evidence_kind.value)
        found = element_keys(candidates)
        for kind, keys in truth_keys.items():
            kinds[kind]["truth"] += len(keys)
            kinds[kind]["found"] += len(keys & found)
        for key in found:
            kinds[key[0]]["candidates"] += 1
            kinds[key[0]]["matched"] += int(key in truth_keys.get(key[0], set()))
    total = run.total
    return {
        "elements": f"{total.elements_found}/{total.elements_total}",
        "element_recall": pct(total.elements_found, total.elements_total),
        "location_recall": pct(total.locations_found, total.locations_total),
        "host_recall": pct(total.hosts_found, total.hosts_total),
        "candidate_precision": pct(total.matched_candidates, total.candidates),
        "seconds_per_system": {k: round(v, 2) for k, v in run.seconds.items()},
        "by_location_kind": {
            k: {
                "evidence": sorted(v["evidence"]),
                "truth": v["truth"],
                "found": v["found"],
                "recall": pct(v["found"], v["truth"]),
                "candidates": v["candidates"],
                "precision": pct(v["matched"], v["candidates"]),
            }
            for k, v in sorted(kinds.items())
        },
    }


@pytest.fixture(scope="module")
def fallback_run(tmp_path_factory: pytest.TempPathFactory) -> EstateRun:
    return run_estate(Settings(rea_enabled=False, rea_input_dir=str(tmp_path_factory.mktemp("fb"))))


@pytest.fixture(scope="module")
def rea_run(tmp_path_factory: pytest.TempPathFactory) -> EstateRun | None:
    if rea_unavailable_reason():
        return None
    return run_estate(
        Settings(
            rea_enabled=True,
            rea_input_dir=str(tmp_path_factory.mktemp("rea")),
            rea_observation_ms=1000,
        )
    )


def test_discovery_recall_and_precision(fallback_run: EstateRun, rea_run: EstateRun | None) -> None:
    fallback = discovery_figures(fallback_run)
    rea = discovery_figures(rea_run) if rea_run else None
    record("discovery", {"fallback": fallback, "rea": rea})
    for figures in (fallback, rea):
        if figures:
            assert figures["element_recall"] >= 90 and figures["host_recall"] >= 95


# -- classification: rules, embeddings, both; no model is involved at all -------------------------


@pytest.fixture(scope="module")
def matcher(real_embedder: SentenceTransformerEmbedder) -> MemoryMatcher:
    return MemoryMatcher(KNOWLEDGE, real_embedder)


def metric_row(items: list[Any], knowledge: Any = KNOWLEDGE) -> dict[str, Any]:
    m = classify_eval.evaluate(items, knowledge)[0]
    return {
        "labelled": m.labelled,
        "correct": m.correct,
        "wrong": m.wrong,
        "sent_to_review": m.abstained,
        "accuracy": round(100 * m.accuracy, 1),
        "special_total": m.special_total,
        "special_flagged": m.special_flagged,
        "technical_false_positives": m.technical_false_positives,
    }


def test_classification_accuracy_and_ablations(
    real_embedder: SentenceTransformerEmbedder, matcher: MemoryMatcher
) -> None:
    estate = classify_eval.prepare(
        classify_eval.estate_examples(), KNOWLEDGE, real_embedder, matcher
    )
    challenge = classify_eval.prepare(
        classify_eval.challenge_examples(), KNOWLEDGE, real_embedder, matcher
    )
    t = KNOWLEDGE.thresholds
    rules_only = replace(KNOWLEDGE, thresholds=replace(t, embedding_accept=2.0))
    embedding_only = replace(KNOWLEDGE, thresholds=replace(t, rule_accept=2.0))
    record(
        "classification",
        {
            "estate": metric_row(estate),
            "estate_rules_only": metric_row(estate, rules_only),
            "estate_embeddings_only": metric_row(estate, embedding_only),
            "challenge": metric_row(challenge),
            "challenge_rules_only": metric_row(challenge, rules_only),
            "challenge_embeddings_only": metric_row(challenge, embedding_only),
            "uses_a_language_model": False,
        },
    )
    assert RESULTS["classification"]["estate"]["accuracy"] >= 90


# -- recipients and the comparison ----------------------------------------------------------------


def test_recipient_detection(fusion_estate: FusionEstate) -> None:
    admin = fusion_estate.admin
    hosts_total = hosts_found = attrs_total = attrs_right = 0
    for estate_id, system_id in fusion_estate.systems.items():
        truth = ground_truth(estate_id)
        rows = admin.get(f"/api/v1/systems/{system_id}/recipients", params={"limit": 200}).json()
        domains = {r["domain"]: r for r in rows}
        for recipient in truth["recipients"]:
            for host in recipient["hosts"]:
                hosts_total += 1
                row = next(
                    (r for d, r in domains.items() if d == host or d.endswith("." + host)), None
                )
                hosts_found += int(row is not None)
                if row is not None and not recipient["internal"]:
                    attrs_total += 1
                    attrs_right += int(
                        (row["vendor"], row["role"], row["country"])
                        == (recipient["vendor"], recipient["role"], recipient["country"])
                    )
    record(
        "recipients",
        {
            "hosts": f"{hosts_found}/{hosts_total}",
            "recall": pct(hosts_found, hosts_total),
            "vendor_role_country": f"{attrs_right}/{attrs_total}",
            "attribute_accuracy": pct(attrs_right, attrs_total),
        },
    )
    assert hosts_found == hosts_total


def test_contradiction_detection(fusion_estate: FusionEstate) -> None:
    result = fusion_score(fusion_estate.pairs())
    record(
        "contradictions",
        {
            "seeded": result.seeded_ids,
            "found": result.found_ids,
            "recall": round(100 * result.recall, 1),
            "expected_pairs": f"{result.true_pairs}/{result.seeded_pairs}",
            "pair_recall": round(100 * result.pair_recall, 1),
            "reported_pairs": result.reported_pairs,
            "precision": round(100 * result.precision, 1),
            "extras": [list(x) for x in result.extra],
            "missed": list(result.missed),
        },
    )
    assert result.recall >= 0.9 and result.precision >= 0.85


# -- records -------------------------------------------------------------------------------------


def test_record_completeness_and_faithfulness(
    estate_records: dict[str, dict[str, Any]], fusion_estate: FusionEstate, owner_engine: Engine
) -> None:
    org = {"o": fusion_estate.org_id}
    with owner_engine.connect() as conn:
        known = {
            "discovery": {
                str(r[0])
                for r in conn.execute(
                    text("SELECT id FROM discovery_evidence WHERE org_id = :o"), org
                )
            },
            "questionnaire": {
                str(r[0])
                for r in conn.execute(text("SELECT id FROM evidence_items WHERE org_id = :o"), org)
            },
            "system": {
                str(r[0])
                for r in conn.execute(text("SELECT id FROM systems WHERE org_id = :o"), org)
            },
        }
    known["policy"] = known["questionnaire"]
    required = present = refs_total = refs_valid = 0
    per_system: dict[str, dict[str, Any]] = {}
    for estate_id, activity in estate_records.items():
        missing = set(activity["missing_fields"])
        sys_required = len(REQUIRED_FIELDS)
        sys_present = sum(1 for f in REQUIRED_FIELDS if f not in missing)
        required += sys_required
        present += sys_present
        sys_refs = sys_valid = 0
        for refs in (activity["citations"] or {}).values():
            for ref in refs:
                if ref["kind"] in known:
                    sys_refs += 1
                    sys_valid += int(ref["id"] in known[ref["kind"]])
        refs_total += sys_refs
        refs_valid += sys_valid
        per_system[estate_id] = {
            "complete": f"{sys_present}/{sys_required}",
            "missing": sorted(missing),
            "citations": sys_refs,
            "valid": sys_valid,
        }
    record(
        "records",
        {
            "completeness": pct(present, required),
            "fields": f"{present}/{required}",
            "faithfulness": pct(refs_valid, refs_total),
            "citations": f"{refs_valid}/{refs_total}",
            "per_system": per_system,
        },
    )
    assert refs_valid == refs_total and refs_total > 200


# -- impact assessment screening and request search ----------------------------------------------


def test_screening_against_the_rubric(
    fusion_estate: FusionEstate, estate_records: dict[str, dict[str, Any]]
) -> None:
    from tests.fixtures_api import csrf

    admin = fusion_estate.admin
    decisions = right = crit_expected = crit_right = crit_extra = 0
    rows = {}
    for estate_id, activity in estate_records.items():
        response = admin.post(
            f"/api/v1/activities/{activity['id']}/dpia-screening",
            json={"data_subjects_estimate": people_in(estate_id)},
            headers=csrf(admin),
        )
        screening = response.json()
        met = {c["id"] for c in screening["criteria"] if c["met"]}
        expected = set(RUBRIC[estate_id]["criteria_met"])
        decisions += 1
        right += int(screening["required"] is RUBRIC[estate_id]["assessment_required"])
        crit_expected += len(expected)
        crit_right += len(expected & met)
        crit_extra += len(met - expected)
        rows[estate_id] = {
            "required": screening["required"],
            "expected": RUBRIC[estate_id]["assessment_required"],
            "criteria_exact": met == expected,
        }
    record(
        "screening",
        {
            "decisions": f"{right}/{decisions}",
            "accuracy": pct(right, decisions),
            "criteria_recall": pct(crit_right, crit_expected),
            "criteria_extra": crit_extra,
            "per_system": rows,
        },
    )
    assert right == decisions


def test_request_search_recall(fusion_estate: FusionEstate) -> None:
    expected_total = found_total = extra_total = exact = 0
    per_case = {}
    for c in CASES:
        _, outcome = prepared(fusion_estate.admin, email_of(c["id"]))
        got = locations(fusion_estate, outcome["results"])
        want = {
            (loc["system"], loc["table"], loc["column"]): loc["rows"]
            for loc in c["expected_locations"]
        }
        expected_total += len(want)
        found_total += len(set(got) & set(want))
        extra_total += len(set(got) - set(want))
        exact += int(got == want)
        per_case[c["id"]] = {
            "expected": len(want),
            "found": len(set(got) & set(want)),
            "extra": len(set(got) - set(want)),
        }
    record(
        "requests",
        {
            "cases": len(CASES),
            "locations": f"{found_total}/{expected_total}",
            "recall": pct(found_total, expected_total),
            "extra": extra_total,
            "cases_exact": f"{exact}/{len(CASES)}",
            "per_case": per_case,
        },
    )
    assert found_total == expected_total and extra_total == 0


# -- retrieval and chat grounding ----------------------------------------------------------------


@pytest.fixture
def kdb(
    session_factory: sessionmaker[TenantSession], knowledge_org: KnowledgeOrg
) -> Iterator[Session]:
    with session_factory() as session:
        set_tenant(session, TenantContext(org_id=knowledge_org.org_id))
        yield session


def test_retrieval_and_chat_grounding(
    kdb: Session,
    real_embedder: SentenceTransformerEmbedder,
    knowledge_org: KnowledgeOrg,
    session_factory: sessionmaker[TenantSession],
) -> None:
    from app.knowledge.evaluation import matches
    from app.knowledge.retrieval import Filters

    gold = load_gold()
    modes = {}
    for mode in ("hybrid", "vector", "fulltext"):
        report = evaluate_recall(HybridRetriever(kdb, real_embedder, mode=mode), gold, knowledge_org.system_ids)  # type: ignore[arg-type]
        modes[mode] = {
            "recall_at_5": round(100 * report.recall, 1),
            "hits": f"{report.hits}/{report.total}",
            "mrr": round(report.mrr, 3),
            "p50_ms": round(report.p50_ms),
            "p95_ms": round(report.p95_ms),
            "missed": report.misses,
        }
    provider = TaskAwareProvider()
    clock = FakeClock()
    router = LLMRouter(
        {"groq": provider},
        lambda: session_factory,
        clock=clock,
        sleep=clock.sleep,
        limits={"groq": ProviderLimits(10_000_000, 10_000)},
    )
    retriever = HybridRetriever(kdb, real_embedder)
    cited_valid = cited_total = grounded = answered = tokens = 0
    for q in gold:
        filters = Filters(
            system_id=knowledge_org.system_ids[q.system] if q.system else None,
            doc_types=(q.doc_type,) if q.doc_type else (),
        )
        passages = retriever.search(q.question, top_k=5, filters=filters).passages
        job = JobBudget(3000)
        scope = Scope(knowledge_org.org_id, job=job)
        answer, _ = answer_question(router, scope, question=q.question, passages=passages)
        tokens += job.used
        by_id = {str(p.id): p for p in passages}
        for pid in answer.cited_passage_ids:
            cited_total += 1
            cited_valid += int(pid in by_id)
        answered += int(answer.supported)
        grounded += int(
            any(
                matches(by_id[pid], rel)
                for pid in answer.cited_passage_ids
                if pid in by_id
                for rel in q.relevant
            )
        )
    record(
        "retrieval",
        {
            "questions": len(gold),
            "modes": modes,
            "chat": {
                "answered": answered,
                "grounded": f"{grounded}/{len(gold)}",
                "grounded_pct": pct(grounded, len(gold)),
                "citation_validity": pct(cited_valid, cited_total),
                "citations": cited_total,
                "tokens_per_answer": round(tokens / len(gold)),
                "answer_text_quality": "not measured: the model is scripted",
            },
        },
    )
    assert modes["hybrid"]["recall_at_5"] >= 90 and cited_valid == cited_total


# -- tokens, calls and time ----------------------------------------------------------------------


def test_tokens_calls_and_time_first_run_against_repeat(
    setup: Any,  # noqa: F811
    fusion_estate: FusionEstate,
    estate_generation: dict[str, dict[str, Any]],
) -> None:
    router, provider, org_id, ids, _ = setup
    rows: dict[str, dict[str, Any]] = {}
    for sid in SYSTEM_IDS:
        calls0, started = len(provider.requests), time.monotonic()
        first = onboard(router, org_id, ids[sid], sid)
        rows[sid] = {
            "calls_first": len(provider.requests) - calls0,
            "tokens_first": first.used,
            "seconds_first": round(time.monotonic() - started, 3),
        }
    for sid in SYSTEM_IDS:
        calls0, started = len(provider.requests), time.monotonic()
        again = onboard(router, org_id, ids[sid], sid)
        rows[sid].update(
            {
                "calls_repeat": len(provider.requests) - calls0,
                "tokens_repeat": again.used,
                "seconds_repeat": round(time.monotonic() - started, 3),
            }
        )
    pipeline = {
        sid: {
            "fusion_tokens": fusion_estate.summaries[sid].get("tokens_used"),
            "record_tokens": estate_generation[sid].get("tokens_used"),
        }
        for sid in estate_generation
    }
    record(
        "tokens",
        {
            "budget_per_system": BUDGET,
            "max_first": max(r["tokens_first"] for r in rows.values()),
            "total_first": sum(r["tokens_first"] for r in rows.values()),
            "total_repeat": sum(r["tokens_repeat"] for r in rows.values()),
            "calls_first": sum(r["calls_first"] for r in rows.values()),
            "calls_repeat": sum(r["calls_repeat"] for r in rows.values()),
            "per_system": rows,
            "pipeline": pipeline,
            "median_seconds_first": round(
                statistics.median(r["seconds_first"] for r in rows.values()), 3
            ),
        },
    )
    assert all(
        r["tokens_first"] < BUDGET and r["tokens_repeat"] == 0 and r["calls_repeat"] == 0
        for r in rows.values()
    )


# -- what was not measured ------------------------------------------------------------------------


def test_record_what_could_not_be_measured() -> None:
    record(
        "not_measured",
        [
            "Groq against Gemini: no provider keys were available, so every model answer is scripted.",
            "The quality of generated prose (purposes, lawful basis suggestions, assessment text, chat answers) was not rated.",
            "Classification accuracy before and after a model step: classification uses no model, so the two are the same by construction.",
        ],
    )
    assert aggregate([]).elements_total == 0
