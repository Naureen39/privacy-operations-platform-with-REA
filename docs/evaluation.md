# Evaluation

Measured on 2026-10-27 on the reference estate (`datasets/estate`, a fictional retailer with a clinic arm: eight systems, 72 data elements, 19 recipient hosts, 19 seeded contradictions, ten request cases). Python 3.12.13, Windows-11-10.0.26200-SP0. REA available: yes. Model providers: **scripted (no provider keys were used)**.

Regenerate with `cd backend && uv run python ../scripts/eval_run.py`. The measuring code is `backend/tests/test_evaluation.py`; every table below is written from its results file, and the same test asserts the acceptance thresholds, so a regression fails the run.

## What these figures are, and are not

- The estate was generated from the same specification as its ground truth and was used to look at mistakes (the first fusion run had 80 percent precision; two general changes were made after reading the false positives). The figures show that the machinery recovers what the evidence contains. They are optimistic for systems the rules have not seen.
- **No real language model was used.** The model is a scripted double that answers every task with a valid object and counts the tokens of the prompts the platform builds. Token and call counts are therefore the real size of what the platform sends; they say nothing about the quality of a model's prose, and Groq against Gemini was not compared.

## 1. Data element discovery

| Extractors | Elements found | Element recall | Location recall | Recipient host recall | Candidate precision |
|---|---|---|---|---|---|
| Fallback parsers | 72/72 | 100.0% | 100.0% | 100.0% | 69.8% |
| REA (with the website parser) | 72/72 | 100.0% | 100.0% | 100.0% | 69.8% |

**Fallback parsers, by kind of location** (the evidence that reveals it is in the second column):

| Location kind | Evidence | Truth | Found | Recall | Candidates | Precision |
|---|---|---|---|---|---|---|
| cookie | har | 2 | 2 | 100.0% | 6 | 33.3% |
| db_column | sqlite_snapshot | 89 | 89 | 100.0% | 112 | 79.5% |
| form_field | website | 51 | 51 | 100.0% | 52 | 98.1% |
| request_form_param | har | 45 | 45 | 100.0% | 46 | 97.8% |
| request_json_key | har | 10 | 10 | 100.0% | 12 | 83.3% |
| request_query_param | har | 5 | 5 | 100.0% | 9 | 55.6% |
| response_json_key | har | 0 | 0 | n/a | 22 | 0.0% |
| third_party_param | har | 13 | 13 | 100.0% | 49 | 26.5% |

**REA, by kind of location** (the evidence that reveals it is in the second column):

| Location kind | Evidence | Truth | Found | Recall | Candidates | Precision |
|---|---|---|---|---|---|---|
| cookie | har | 2 | 2 | 100.0% | 6 | 33.3% |
| db_column | sqlite_snapshot | 89 | 89 | 100.0% | 112 | 79.5% |
| form_field | website | 51 | 51 | 100.0% | 52 | 98.1% |
| request_form_param | har | 45 | 45 | 100.0% | 46 | 97.8% |
| request_json_key | har | 10 | 10 | 100.0% | 12 | 83.3% |
| request_query_param | har | 5 | 5 | 100.0% | 9 | 55.6% |
| response_json_key | har | 0 | 0 | n/a | 22 | 0.0% |
| third_party_param | har | 13 | 13 | 100.0% | 49 | 26.5% |

Precision is the share of discovered names that are a ground-truth location. It is deliberately below 100 percent: discovery lists everything it sees, including non-personal fields such as `idsite` or `created_at`, and classification decides what is personal data.

## 2. Category classification

| Configuration | Estate correct | Accuracy | Wrong | Sent to review | Challenge correct | Accuracy | Wrong |
|---|---|---|---|---|---|---|---|
| Rules and embeddings (the shipped configuration) | 213/216 | 98.6% | 0 | 3 | 72/78 | 92.3% | 3 |
| Rules only | 204/216 | 94.4% | 0 | 12 | 55/78 | 70.5% | 1 |
| Embeddings only | 141/216 | 65.3% | 1 | 74 | 64/78 | 82.1% | 0 |

Special category (Article 9) elements flagged: 17 of 17. Technical names mistaken for personal data: 0.

**Before and after the model step:** classification uses no language model (a test checks that the code imports no model provider and no HTTP client), so the accuracy before and after a model step is the same by construction. The model is used later, for free text only. The challenge set holds names the rules were not tuned on and is the fairer estimate for an unseen system; the estate figures flatter the rule layer because the synonym lists and the estate field names were written by the same author.

## 3. Recipient detection

| Measure | Result |
|---|---|
| Hosts found in the stored recipients | 19/19 (100.0%) |
| Vendor, role and country correct for external hosts | 18/18 (100.0%) |

## 4. Contradiction detection

| Measure | Result |
|---|---|
| Seeded contradictions found | 19 of 19 (100.0%) |
| Expected (system, type) findings reported | 24/24 (100.0%) |
| Precision of the reported pairs | 88.9% (27 reported) |
| Reported but not seeded | crm/element_not_in_policy, newsletter/policy_contradiction, staff_desktop/policy_contradiction |

The extras are real inconsistencies the dataset does not list, or a known classifier miss; each is reviewed in `docs/architecture.md`.

## 5. Records: completeness and faithfulness

| Measure | Result |
|---|---|
| Required fields present | 88/88 (100.0%) |
| Citations that point to evidence that exists | 201/201 (100.0%) |

| System | Required fields | Missing | Citations | Valid |
|---|---|---|---|---|
| clinic_portal | 11/11 | special_category_condition | 26 | 26 |
| crm | 11/11 | none | 24 | 24 |
| helpdesk | 11/11 | none | 23 | 23 |
| hr_onboarding | 11/11 | special_category_condition | 29 | 29 |
| newsletter | 11/11 | none | 23 | 23 |
| staff_desktop | 11/11 | none | 22 | 22 |
| web_analytics | 11/11 | none | 21 | 21 |
| web_shop | 11/11 | none | 33 | 33 |

A missing field is a real gap, not a failure: the Article 9 condition of the clinic and HR systems is not in the evidence, so the record says so and a finding is raised. A claim without a valid evidence id does not occur; the record builder cites only what the extraction produced.

## 6. Impact assessment screening

| Measure | Result |
|---|---|
| Assessment-needed decision matches the rubric | 8/8 (100.0%) |
| Rubric criteria recovered | 100.0% |
| Criteria met that the rubric does not list | 0 |

## 7. Access request search

| Measure | Result |
|---|---|
| Request cases | 10 |
| Expected locations found | 52/52 (100.0%) |
| Locations returned that were not expected | 0 |
| Cases with exactly the expected result | 10/10 |

Two cases are designed to find nothing (a person who is in no system, and a pseudonymous identifier); they return nothing.

## 8. Retrieval and chat on the 40 question gold set

| Retrieval | Recall at 5 | Hits | MRR | p50 / p95 (ms) |
|---|---|---|---|---|
| fulltext | 75.0% | 30/40 | 0.6 | 22 / 47 |
| hybrid | 97.5% | 39/40 | 0.908 | 114 / 200 |
| vector | 97.5% | 39/40 | 0.869 | 75 / 101 |

| Chat (retrieval grounded, scripted model) | Result |
|---|---|
| Questions answered from retrieved passages | 40 of 40 |
| Answers that cite a passage matching the gold answer | 36/40 (90.0%) |
| Citations that are among the passages retrieved | 100.0% of 80 |
| Tokens per answer (prompt and answer) | 942 |
| Quality of the answer text | not measured: the model is scripted |

## 9. Tokens, calls and time, first run against a repeat run

| System | Calls (first) | Tokens (first) | Seconds (first) | Calls (repeat) | Tokens (repeat) | Seconds (repeat) |
|---|---|---|---|---|---|---|
| clinic_portal | 3 | 1745 | 0.125 | 0 | 0 | 0.032 |
| crm | 3 | 1698 | 0.172 | 0 | 0 | 0.031 |
| helpdesk | 3 | 1671 | 0.156 | 0 | 0 | 0.031 |
| hr_onboarding | 3 | 1914 | 0.047 | 0 | 0 | 0.016 |
| newsletter | 3 | 1650 | 0.094 | 0 | 0 | 0.031 |
| staff_desktop | 3 | 1723 | 0.047 | 0 | 0 | 0.031 |
| web_analytics | 3 | 1700 | 0.125 | 0 | 0 | 0.031 |
| web_shop | 3 | 1889 | 0.156 | 0 | 0 | 0.047 |

The largest first onboarding uses 1914 tokens against a budget of 4000. A repeat with unchanged evidence makes 0 calls and uses 0 tokens, because every answer is cached by the hash of its normalized request. The call counts are three per system (one purpose and basis call, two conflicts the rules cannot settle). The seconds are the router overhead around a scripted answer, not model latency.

## 10. Ablations

| Comparison | Variant | Shipped |
|---|---|---|
| REA extractors against fallback parsers (elements found) | 72/72 / 100.0% hosts | 72/72 / 100.0% hosts |
| Rules only against rules and embeddings (estate accuracy) | 94.4% | 98.6% |
| Embeddings only against rules and embeddings (estate accuracy) | 65.3% | 98.6% |
| Hybrid retrieval against vector only and full text only (recall at 5) | vector 97.5%, full text 75.0% | 97.5% |

**Rules plus a model against rules only:** not applicable to classification (no model is involved). **Groq against Gemini:** not run, because no provider keys were available.

## 11. Load sanity: a 50 MB capture

A synthetic network capture of 50.0 MB (10651 requests) is analysed in a fresh process; the memory of the process and its children is sampled every 50 ms. The limit is 1536 MB.

| Extractor | Peak memory | Time | Outcome |
|---|---|---|---|
| fallback | 345 MB | 1.2 s | fallback ok |
| rea | 346 MB | 2.5 s | rea error, fallback ok |



## 12. Backend test coverage

Measured with `coverage run -m pytest` (825 tests); the target is 80 percent on these packages and CI fails below it. Figures are from the last full run, not regenerated by this script.

| Package | Coverage |
|---|---|
| discovery | 95% |
| classify | 97% |
| fusion | 98% |
| records | 98% |
| dpia | 97% |
| dsar | 95% |
| llm | 98% |
| core | 98% |
| whole backend | 97% |

## Not measured

- Groq against Gemini: no provider keys were available, so every model answer is scripted.
- The quality of generated prose (purposes, lawful basis suggestions, assessment text, chat answers) was not rated.
- Classification accuracy before and after a model step: classification uses no model, so the two are the same by construction.
