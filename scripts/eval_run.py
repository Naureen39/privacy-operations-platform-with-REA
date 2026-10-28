"""Run the evaluation on the reference estate end to end and write docs/evaluation.md.

    cd backend
    uv run python ../scripts/eval_run.py                  # measure, then write the document
    uv run python ../scripts/eval_run.py --render-only    # rewrite the document from the last results
    uv run python ../scripts/eval_run.py --skip-load      # leave out the 50 MB capture check

The measuring is `backend/tests/test_evaluation.py` (it needs Docker for a throwaway PostgreSQL
container and the embedding model; REA is used when the pinned release can run). It writes
`backend/.eval/results.json`; the 50 MB capture check (`scripts/load_check.py`) writes
`backend/.eval/load.json`. This script turns both into the document.
"""

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
EVAL_DIR = BACKEND / ".eval"
DOC = ROOT / "docs" / "evaluation.md"


COVERAGE = {
    "discovery": "95%",
    "classify": "97%",
    "fusion": "98%",
    "records": "98%",
    "dpia": "97%",
    "dsar": "95%",
    "llm": "98%",
    "core": "98%",
    "whole backend": "97%",
}


def run(*cmd: str) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(list(cmd), cwd=BACKEND, check=False).returncode  # noqa: S603


def table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def pct(value: Any) -> str:
    return f"{value}%" if value is not None else "not run"


def discovery_section(d: dict[str, Any]) -> str:
    fb, rea = d["fallback"], d.get("rea")
    head = [
        "Extractors",
        "Elements found",
        "Element recall",
        "Location recall",
        "Recipient host recall",
        "Candidate precision",
    ]
    rows = [
        [
            "Fallback parsers",
            fb["elements"],
            pct(fb["element_recall"]),
            pct(fb["location_recall"]),
            pct(fb["host_recall"]),
            pct(fb["candidate_precision"]),
        ]
    ]
    rows.append(
        [
            "REA (with the website parser)",
            rea["elements"],
            pct(rea["element_recall"]),
            pct(rea["location_recall"]),
            pct(rea["host_recall"]),
            pct(rea["candidate_precision"]),
        ]
        if rea
        else ["REA", "not run", "", "", "", ""]
    )
    out = [table(head, rows), ""]
    for label, data in (("Fallback parsers", fb), ("REA", rea)):
        if not data:
            continue
        kinds = data["by_location_kind"]
        out.append(
            f"**{label}, by kind of location** (the evidence that reveals it is in the second column):\n"
        )
        out.append(
            table(
                [
                    "Location kind",
                    "Evidence",
                    "Truth",
                    "Found",
                    "Recall",
                    "Candidates",
                    "Precision",
                ],
                [
                    [
                        k,
                        ", ".join(v["evidence"]) or "none",
                        v["truth"],
                        v["found"],
                        pct(v["recall"]) if v["truth"] else "n/a",
                        v["candidates"],
                        pct(v["precision"]),
                    ]
                    for k, v in kinds.items()
                ],
            )
        )
        out.append("")
    out.append(
        "Precision is the share of discovered names that are a ground-truth location. It is deliberately below 100 percent: discovery lists everything it sees, including non-personal fields such as `idsite` or `created_at`, and classification decides what is personal data."
    )
    return "\n".join(out)


def classification_section(c: dict[str, Any]) -> str:
    rows = []
    for label, key in (
        ("Rules and embeddings (the shipped configuration)", ""),
        ("Rules only", "_rules_only"),
        ("Embeddings only", "_embeddings_only"),
    ):
        e, ch = c[f"estate{key}"], c[f"challenge{key}"]
        rows.append(
            [
                label,
                f"{e['correct']}/{e['labelled']}",
                pct(e["accuracy"]),
                e["wrong"],
                e["sent_to_review"],
                f"{ch['correct']}/{ch['labelled']}",
                pct(ch["accuracy"]),
                ch["wrong"],
            ]
        )
    e = c["estate"]
    return "\n".join(
        [
            table(
                [
                    "Configuration",
                    "Estate correct",
                    "Accuracy",
                    "Wrong",
                    "Sent to review",
                    "Challenge correct",
                    "Accuracy",
                    "Wrong",
                ],
                rows,
            ),
            "",
            f"Special category (Article 9) elements flagged: {e['special_flagged']} of {e['special_total']}. Technical names mistaken for personal data: {e['technical_false_positives']}.",
            "",
            "**Before and after the model step:** classification uses no language model (a test checks that the code imports no model provider and no HTTP client), so the accuracy before and after a model step is the same by construction. The model is used later, for free text only. The challenge set holds names the rules were not tuned on and is the fairer estimate for an unseen system; the estate figures flatter the rule layer because the synonym lists and the estate field names were written by the same author.",
        ]
    )


def render(results: dict[str, Any], load: dict[str, Any] | None) -> str:
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    env = results.get("environment", {})
    parts = [
        "# Evaluation",
        "",
        f"Measured on {now} on the reference estate (`datasets/estate`, a fictional retailer with a clinic arm: eight systems, 72 data elements, 19 recipient hosts, 19 seeded contradictions, ten request cases). Python {env.get('python', '?')}, {env.get('platform', '?')}. REA available: {'yes' if env.get('rea_available') else 'no'}. Model providers: **{env.get('providers', 'scripted')}**.",
        "",
        "Regenerate with `cd backend && uv run python ../scripts/eval_run.py`. The measuring code is `backend/tests/test_evaluation.py`; every table below is written from its results file, and the same test asserts the acceptance thresholds, so a regression fails the run.",
        "",
        "## What these figures are, and are not",
        "",
        "- The estate was generated from the same specification as its ground truth and was used to look at mistakes (the first fusion run had 80 percent precision; two general changes were made after reading the false positives). The figures show that the machinery recovers what the evidence contains. They are optimistic for systems the rules have not seen.",
        "- **No real language model was used.** The model is a scripted double that answers every task with a valid object and counts the tokens of the prompts the platform builds. Token and call counts are therefore the real size of what the platform sends; they say nothing about the quality of a model's prose, and Groq against Gemini was not compared.",
        "",
        "## 1. Data element discovery",
        "",
        discovery_section(results["discovery"]),
        "",
        "## 2. Category classification",
        "",
        classification_section(results["classification"]),
        "",
    ]
    r = results["recipients"]
    parts += [
        "## 3. Recipient detection",
        "",
        table(
            ["Measure", "Result"],
            [
                ["Hosts found in the stored recipients", f"{r['hosts']} ({pct(r['recall'])})"],
                [
                    "Vendor, role and country correct for external hosts",
                    f"{r['vendor_role_country']} ({pct(r['attribute_accuracy'])})",
                ],
            ],
        ),
        "",
    ]
    c = results["contradictions"]
    parts += [
        "## 4. Contradiction detection",
        "",
        table(
            ["Measure", "Result"],
            [
                [
                    "Seeded contradictions found",
                    f"{c['found']} of {c['seeded']} ({pct(c['recall'])})",
                ],
                [
                    "Expected (system, type) findings reported",
                    f"{c['expected_pairs']} ({pct(c['pair_recall'])})",
                ],
                [
                    "Precision of the reported pairs",
                    f"{pct(c['precision'])} ({c['reported_pairs']} reported)",
                ],
                [
                    "Reported but not seeded",
                    ", ".join(f"{a}/{b}" for a, b in c["extras"]) or "none",
                ],
            ],
        ),
        "",
        "The extras are real inconsistencies the dataset does not list, or a known classifier miss; each is reviewed in `docs/architecture.md`.",
        "",
    ]
    rec = results["records"]
    parts += [
        "## 5. Records: completeness and faithfulness",
        "",
        table(
            ["Measure", "Result"],
            [
                ["Required fields present", f"{rec['fields']} ({pct(rec['completeness'])})"],
                [
                    "Citations that point to evidence that exists",
                    f"{rec['citations']} ({pct(rec['faithfulness'])})",
                ],
            ],
        ),
        "",
        table(
            ["System", "Required fields", "Missing", "Citations", "Valid"],
            [
                [k, v["complete"], ", ".join(v["missing"]) or "none", v["citations"], v["valid"]]
                for k, v in rec["per_system"].items()
            ],
        ),
        "",
        "A missing field is a real gap, not a failure: the Article 9 condition of the clinic and HR systems is not in the evidence, so the record says so and a finding is raised. A claim without a valid evidence id does not occur; the record builder cites only what the extraction produced.",
        "",
    ]
    s = results["screening"]
    parts += [
        "## 6. Impact assessment screening",
        "",
        table(
            ["Measure", "Result"],
            [
                [
                    "Assessment-needed decision matches the rubric",
                    f"{s['decisions']} ({pct(s['accuracy'])})",
                ],
                ["Rubric criteria recovered", pct(s["criteria_recall"])],
                ["Criteria met that the rubric does not list", s["criteria_extra"]],
            ],
        ),
        "",
    ]
    q = results["requests"]
    parts += [
        "## 7. Access request search",
        "",
        table(
            ["Measure", "Result"],
            [
                ["Request cases", q["cases"]],
                ["Expected locations found", f"{q['locations']} ({pct(q['recall'])})"],
                ["Locations returned that were not expected", q["extra"]],
                ["Cases with exactly the expected result", q["cases_exact"]],
            ],
        ),
        "",
        "Two cases are designed to find nothing (a person who is in no system, and a pseudonymous identifier); they return nothing.",
        "",
    ]
    t = results["retrieval"]
    modes = t["modes"]
    ch = t["chat"]
    parts += [
        "## 8. Retrieval and chat on the 40 question gold set",
        "",
        table(
            ["Retrieval", "Recall at 5", "Hits", "MRR", "p50 / p95 (ms)"],
            [
                [m, pct(v["recall_at_5"]), v["hits"], v["mrr"], f"{v['p50_ms']} / {v['p95_ms']}"]
                for m, v in modes.items()
            ],
        ),
        "",
        table(
            ["Chat (retrieval grounded, scripted model)", "Result"],
            [
                [
                    "Questions answered from retrieved passages",
                    f"{ch['answered']} of {t['questions']}",
                ],
                [
                    "Answers that cite a passage matching the gold answer",
                    f"{ch['grounded']} ({pct(ch['grounded_pct'])})",
                ],
                [
                    "Citations that are among the passages retrieved",
                    pct(ch["citation_validity"]) + f" of {ch['citations']}",
                ],
                ["Tokens per answer (prompt and answer)", ch["tokens_per_answer"]],
                ["Quality of the answer text", ch["answer_text_quality"]],
            ],
        ),
        "",
    ]
    tk = results["tokens"]
    rows = [
        [
            k,
            v["calls_first"],
            v["tokens_first"],
            f"{v['seconds_first']}",
            v["calls_repeat"],
            v["tokens_repeat"],
            f"{v['seconds_repeat']}",
        ]
        for k, v in tk["per_system"].items()
    ]
    parts += [
        "## 9. Tokens, calls and time, first run against a repeat run",
        "",
        table(
            [
                "System",
                "Calls (first)",
                "Tokens (first)",
                "Seconds (first)",
                "Calls (repeat)",
                "Tokens (repeat)",
                "Seconds (repeat)",
            ],
            rows,
        ),
        "",
        f"The largest first onboarding uses {tk['max_first']} tokens against a budget of {tk['budget_per_system']}. A repeat with unchanged evidence makes {tk['calls_repeat']} calls and uses {tk['total_repeat']} tokens, because every answer is cached by the hash of its normalized request. The call counts are three per system (one purpose and basis call, two conflicts the rules cannot settle). The seconds are the router overhead around a scripted answer, not model latency.",
        "",
    ]
    parts += ["## 10. Ablations", ""]
    d = results["discovery"]
    cls = results["classification"]
    abl = [
        [
            "REA extractors against fallback parsers (elements found)",
            (
                f"{d['rea']['elements']} / {d['rea']['host_recall']}% hosts"
                if d.get("rea")
                else "REA not run"
            ),
            f"{d['fallback']['elements']} / {d['fallback']['host_recall']}% hosts",
        ],
        [
            "Rules only against rules and embeddings (estate accuracy)",
            pct(cls["estate_rules_only"]["accuracy"]),
            pct(cls["estate"]["accuracy"]),
        ],
        [
            "Embeddings only against rules and embeddings (estate accuracy)",
            pct(cls["estate_embeddings_only"]["accuracy"]),
            pct(cls["estate"]["accuracy"]),
        ],
        [
            "Hybrid retrieval against vector only and full text only (recall at 5)",
            f"vector {pct(modes['vector']['recall_at_5'])}, full text {pct(modes['fulltext']['recall_at_5'])}",
            pct(modes["hybrid"]["recall_at_5"]),
        ],
    ]
    parts += [
        table(["Comparison", "Variant", "Shipped"], abl),
        "",
        "**Rules plus a model against rules only:** not applicable to classification (no model is involved). **Groq against Gemini:** not run, because no provider keys were available.",
        "",
    ]
    if load:
        rows = []
        for run_ in load["runs"]:
            detail = run_.get("runs") or []
            ok = ", ".join(f"{x['extractor']} {x['status']}" for x in detail) or run_.get(
                "error", "failed"
            )
            rows.append(
                [
                    run_["mode"],
                    f"{run_['peak_mb']} MB",
                    f"{run_.get('seconds', run_['wall_seconds'])} s",
                    ok,
                ]
            )
        parts += [
            "## 11. Load sanity: a 50 MB capture",
            "",
            f"A synthetic network capture of {load['capture_mb']} MB ({load['requests']} requests) is analysed in a fresh process; the memory of the process and its children is sampled every 50 ms. The limit is {load['limit_mb']} MB.",
            "",
            table(["Extractor", "Peak memory", "Time", "Outcome"], rows),
            "",
            (
                ("REA was not run here: " + str(load["rea_skipped"]) + ".")
                if load.get("rea_skipped")
                else ""
            ),
            "",
        ]
    parts += [
        "## 12. Backend test coverage",
        "",
        "Measured with `coverage run -m pytest` (825 tests); the target is 80 percent on these packages "
        "and CI fails below it. Figures are from the last full run, not regenerated by this script.",
        "",
        table(
            ["Package", "Coverage"],
            [[k, v] for k, v in COVERAGE.items()],
        ),
        "",
    ]
    nm = results.get("not_measured", [])
    parts += ["## Not measured", "", *[f"- {x}" for x in nm], ""]
    return "\n".join(parts).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--render-only", action="store_true")
    parser.add_argument("--skip-load", action="store_true")
    args = parser.parse_args()
    code = 0
    if not args.render_only:
        code = run(
            "uv", "run", "pytest", "tests/test_evaluation.py", "-q", "-p", "no:cacheprovider"
        )
        if not args.skip_load:
            code = code or run(sys.executable, "../scripts/load_check.py")
    results_file = EVAL_DIR / "results.json"
    if not results_file.exists():
        print("No results yet; run without --render-only first.")
        return 1
    results = json.loads(results_file.read_text(encoding="utf-8"))
    load_file = EVAL_DIR / "load.json"
    load = json.loads(load_file.read_text(encoding="utf-8")) if load_file.exists() else None
    DOC.write_text(render(results, load), encoding="utf-8")
    print(f"Wrote {DOC.relative_to(ROOT)}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
