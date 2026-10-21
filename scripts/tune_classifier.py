"""Tune the classifier's thresholds on the reference estate and store them in the configuration.

    cd backend && uv run python ../scripts/tune_classifier.py [--write]

Thresholds are chosen on the tuning systems only. The held-out systems and the challenge set are
scored afterwards with the chosen values and are never used for the choice. With --write, the
values and their metrics are stored in datasets/regulation/taxonomy/classifier_config.json.
"""

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.classify.embedder import SentenceTransformerEmbedder  # noqa: E402
from app.classify.evaluation import (  # noqa: E402
    HELD_OUT,
    TUNING,
    Metrics,
    challenge_examples,
    estate_examples,
    evaluate,
    prepare,
    tune,
)  # fmt: skip
from app.classify.index import MemoryMatcher  # noqa: E402
from app.classify.knowledge import DEFAULT_DIR, load_knowledge  # noqa: E402


def summary(m: Metrics) -> dict[str, float | int]:
    return {
        "labelled": m.labelled, "correct": m.correct, "wrong": m.wrong, "unclassified": m.abstained,
        "accuracy": round(m.accuracy, 4), "coverage": round(m.coverage, 4),
        "special_recall": round(m.special_recall, 4), "special_extra_escalations": m.special_extra,
        "technical_false_positives": m.technical_false_positives,
    }  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--write", action="store_true", help="store the chosen thresholds in the configuration"
    )
    args = parser.parse_args()

    knowledge = load_knowledge()
    embedder = SentenceTransformerEmbedder(local_files_only=False)
    matcher = MemoryMatcher(knowledge, embedder)
    examples = estate_examples()
    prepared = prepare(examples, knowledge, embedder, matcher)
    tuning = [p for p in prepared if p.example.system_id in TUNING]
    held_out = [p for p in prepared if p.example.system_id in HELD_OUT]

    chosen, tuned_metrics = tune(tuning, knowledge)
    tuned_knowledge = replace(knowledge, thresholds=chosen)
    held_metrics, _ = evaluate(held_out, tuned_knowledge)
    all_metrics, _ = evaluate(prepared, tuned_knowledge)
    challenge_metrics, _ = evaluate(
        prepare(challenge_examples(), knowledge, embedder, matcher), tuned_knowledge
    )

    report = {
        "tuning": summary(tuned_metrics),
        "held_out": summary(held_metrics),
        "estate_all": summary(all_metrics),
        "challenge": summary(challenge_metrics),
    }
    print(
        json.dumps(
            {
                "thresholds": {
                    k: getattr(chosen, k)
                    for k in (
                        "rule_accept",
                        "rule_margin",
                        "embedding_accept",
                        "embedding_margin",
                        "special_near",
                    )
                },
                **report,
            },
            indent=2,
        )
    )
    for label, metrics in (("held out", held_metrics), ("challenge", challenge_metrics)):
        for error in metrics.errors:
            print(f"  [{label}] {error}")

    if args.write:
        path = DEFAULT_DIR / "taxonomy" / "classifier_config.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config.update(
            version="1.0-tuned",
            rule_accept=chosen.rule_accept, rule_margin=chosen.rule_margin,
            embedding_accept=chosen.embedding_accept, embedding_margin=chosen.embedding_margin,
            special_near=chosen.special_near,
        )  # fmt: skip
        config["meta"] = {
            "embedding_model": embedder.name,
            "tuned_on": list(TUNING),
            "held_out": list(HELD_OUT),
            "objective": "correct - 3 * wrong - 0.5 * technical false positives - 0.15 * extra special escalations; every special category element must be flagged",
            "metrics": report,
        }
        path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
