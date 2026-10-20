"""Write the privacy notice, questionnaire and ground truth of each system, the processor
agreements, the company wide index files and the reference outputs for the evaluation harness.

Everything is derived from estate_spec.py, so the documents agree with the generated evidence
except where a contradiction was seeded on purpose.
"""

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS_DIR, REFERENCE_DATE, write_json, write_text  # noqa: E402
from estate_spec import CONTRADICTIONS, SYSTEMS  # noqa: E402
from js_bundles import bundle_filename  # noqa: E402

EEA = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT",
    "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "IS", "LI", "NO",
}  # fmt: skip
ADEQUATE = {"AD", "AR", "CA", "FO", "GG", "IL", "IM", "JP", "JE", "NZ", "KR", "CH", "GB", "UY"}
BASIS_LABELS = {
    "scc": "standard_contractual_clauses",
    "adequacy": "adequacy_decision",
    "dpf": "dpf_certification",
    "none": None,
}
LAWFUL_BASIS_TEXT = {
    "contract": "the performance of a contract with you",
    "legitimate_interests": "our legitimate interests",
    "consent": "your consent",
    "legal_obligation": "a legal obligation that applies to us",
}
RETENTION_ACTUAL = {
    "web_shop": "Orders are kept 7 years and accounts until deletion.",
    "web_analytics": "25 months.",
    "helpdesk": "Indefinite. No deletion job exists and conversations from 2022 are still stored.",
    "crm": "Indefinite while the business relationship lasts.",
    "clinic_portal": "10 years.",
    "newsletter": "Until unsubscribe plus 30 days.",
    "staff_desktop": "6 years.",
    "hr_onboarding": "Employment plus 6 years.",
}
EVIDENCE_BY_TYPE = {
    "element_not_in_policy": ["policy", "har", "html", "sqlite"],
    "policy_contradiction": ["policy", "har", "sqlite"],
    "undeclared_recipient": ["policy", "questionnaire", "har", "js"],
    "third_country_no_safeguard": ["policy", "questionnaire", "har", "js"],
    "missing_agreement": ["questionnaire", "har"],
    "retention_conflict": ["policy", "questionnaire", "company_policy", "sqlite"],
    "missing_retention": ["questionnaire"],
    "missing_art9_condition": ["policy", "questionnaire", "sqlite", "html"],
    "stale_review": ["questionnaire"],
    "consent_defect": ["policy", "html"],
}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def is_third_country(country: str) -> bool:
    return country not in EEA


def has_special(spec: dict[str, Any]) -> bool:
    return any(e["special"] for e in spec["elements"].values())


# ---------------------------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------------------------
def element_locations(
    spec: dict[str, Any], sent_fields: set[tuple[str, str]]
) -> dict[str, list[dict[str, str]]]:
    locations: dict[str, list[dict[str, str]]] = {e: [] for e in spec["elements"]}
    for endpoint in spec["endpoints"]:
        for field in endpoint["fields"]:
            el = field["el"]
            if not el:
                continue
            if endpoint["page"] and endpoint["enctype"] != "query":
                locations[el].append(
                    {"kind": "form_field", "name": field["name"], "endpoint": endpoint["id"]}
                )
            if (endpoint["id"], field["name"]) in sent_fields:
                kind = {
                    "json": "request_json_key",
                    "form": "request_form_param",
                    "query": "request_query_param",
                }[endpoint["enctype"]]
                locations[el].append(
                    {"kind": kind, "name": field["name"], "endpoint": endpoint["id"]}
                )
    for table in spec["tables"]:
        for column in table["columns"]:
            if column.get("el"):
                locations[column["el"]].append(
                    {"kind": "db_column", "table": table["name"], "column": column["n"]}
                )
    for b in spec["beacons"]:
        for param, el in b["elements"].items():
            locations[el].append({"kind": "third_party_param", "host": b["host"], "name": param})
    for page in spec["pages"]:
        for cookie in page["cookies"]:
            if cookie["el"]:
                locations[cookie["el"]].append({"kind": "cookie", "name": cookie["name"]})
    return locations


def recipient_found_in(hosts: list[str], artifacts: dict[str, str]) -> list[str]:
    return sorted(kind for kind, text in artifacts.items() if any(h in text for h in hosts))


def ground_truth(
    spec: dict[str, Any], sent_fields: set[tuple[str, str]], artifacts: dict[str, str]
) -> dict[str, Any]:
    locations = element_locations(spec, sent_fields)
    return {
        "system_id": spec["id"],
        "system_name": spec["name"],
        "reference_date": REFERENCE_DATE,
        "stack": spec["stack"],
        "modeled_open_source_product": spec["modeled"],
        "data_elements": [
            {
                "id": el_id,
                "category": e["category"],
                "special_category": e["special"],
                "description": e["label"],
                "declared_in_policy": e["policy"],
                "declared_in_questionnaire": e["questionnaire"],
                "locations": locations[el_id],
            }
            for el_id, e in sorted(spec["elements"].items())
        ],
        "recipients": [
            {
                "id": r["id"],
                "hosts": sorted(r["hosts"]),
                "vendor": r["vendor"],
                "role": r["role"],
                "country": r["country"],
                "third_country": is_third_country(r["country"]),
                "purpose": r["purpose"],
                "internal": r["internal"],
                "shares_elements": sorted(r["shares"]),
                "declared_in_policy": r["declared_policy"],
                "declared_in_questionnaire": r["declared_questionnaire"],
                "agreement_required": r["agreement_required"],
                "agreement_on_file": r["agreement_on_file"],
                "transfer_basis": (
                    r["transfer_basis"] if is_third_country(r["country"]) else "not_required"
                ),
                "found_in": recipient_found_in(r["hosts"], artifacts),
            }
            for r in sorted(spec["recipients"], key=lambda r: r["id"])
        ],
        "technologies": sorted(spec["js"]["modules"]),
        "retention": {
            "policy": spec["policy"]["retention_statement"],
            "questionnaire": spec["questionnaire"]["retention"],
            "actual": RETENTION_ACTUAL[spec["id"]],
        },
        "last_review_date": spec["last_review_date"],
        "dpia": spec["dpia"],
        "contradictions": [c["id"] for c in CONTRADICTIONS if c["system"] == spec["id"]],
    }


# ---------------------------------------------------------------------------------------------
# Privacy notice and questionnaire
# ---------------------------------------------------------------------------------------------
def policy_markdown(spec: dict[str, Any]) -> str:
    p = spec["policy"]
    declared = [e["label"] for _, e in sorted(spec["elements"].items()) if e["policy"]]
    recipients = [r for r in spec["recipients"] if r["declared_policy"] and not r["internal"]]
    lines = [
        f"# Privacy notice: {spec['name']}",
        "",
        "_Reference estate document for the fictional company Northbridge Group. Demonstration use only. "
        "Draft for review by a qualified privacy professional. Not legal advice._",
        "",
        "## Who we are",
        "",
        f"{spec['name']} is operated by Northbridge Group. {spec['description']} "
        f"The system owner is {spec['owner']}.",
        "",
        "## Personal data we collect",
        "",
        *[f"- {label}" for label in declared],
        "",
        "## Why we use your data",
        "",
        *[f"- {purpose}" for purpose in p["purposes"]],
        "",
        f"Our legal basis is {LAWFUL_BASIS_TEXT[p['lawful_basis']]}.",
        "",
        "## Who we share it with",
        "",
        p["sharing_statement"],
        "",
    ]
    if recipients:
        lines += [
            f"- {r['vendor']} ({r['country']}): {r['purpose'].lower()}" for r in recipients
        ] + [""]
    lines += [
        "## How long we keep it",
        "",
        p["retention_statement"],
        "",
        "## International transfers",
        "",
        p["transfer_statement"],
        "",
    ]
    if p["extra_claims"]:
        lines += [
            "## How we handle your data",
            "",
            *[f"- {claim}" for claim in p["extra_claims"]],
            "",
        ]
    lines += [
        "## Security",
        "",
        "We protect your data with technical and organisational measures that are appropriate to the risk.",
        "",
        "## Your rights",
        "",
        "You can ask us for access to your data, correction, deletion, restriction, a copy in a portable "
        "format, and you can object to processing based on our legitimate interests. Write to "
        "privacy@northbridge.example. We answer within one month.",
    ]
    return "\n".join(lines)


def questionnaire(spec: dict[str, Any]) -> dict[str, Any]:
    q = spec["questionnaire"]
    categories = sorted({e["category"] for e in spec["elements"].values() if e["questionnaire"]})
    declared = [r for r in spec["recipients"] if r["declared_questionnaire"]]
    transfers = [
        {
            "recipient": r["vendor"],
            "country": r["country"],
            "safeguard": BASIS_LABELS[r["transfer_basis"]] or "",
        }
        for r in declared
        if is_third_country(r["country"])
    ]
    condition = q["special_category_condition"]
    if condition is None and not has_special(spec):
        condition = "not_applicable"
    return {
        "system_id": spec["id"],
        "system_name": spec["name"],
        "completed_by": spec["owner"],
        "answers": {
            "purposes": q["purposes"],
            "data_subjects": q["data_subjects"],
            "data_categories_declared": categories,
            "recipients_declared": [
                {"vendor": r["vendor"], "country": r["country"], "purpose": r["purpose"]}
                for r in declared
            ],
            "lawful_basis": q["lawful_basis"],
            "special_category_condition": condition,
            "retention": q["retention"],
            "transfers": transfers,
            "processors_with_agreement": sorted(
                {
                    r["vendor"]
                    for r in declared
                    if r["agreement_required"] and r["agreement_on_file"]
                }
            ),
            "security_measures": q["security_measures"],
            "last_review_date": q["last_review_date"],
            "notes": q["notes"],
        },
    }


# ---------------------------------------------------------------------------------------------
# Processor agreements (only where one is on file)
# ---------------------------------------------------------------------------------------------
def vendor_agreements() -> dict[str, str]:
    grouped: dict[str, dict[str, Any]] = {}
    for spec in SYSTEMS:
        labels = {k: v["label"] for k, v in spec["elements"].items()}
        for r in spec["recipients"]:
            if not (r["agreement_required"] and r["agreement_on_file"]):
                continue
            entry = grouped.setdefault(
                r["vendor"],
                {
                    "country": r["country"],
                    "basis": r["transfer_basis"],
                    "purposes": set(),
                    "data": set(),
                    "systems": set(),
                },
            )
            entry["purposes"].add(r["purpose"])
            entry["data"].update(labels[e] for e in r["shares"])
            entry["systems"].add(spec["name"])
    documents = {}
    for vendor, e in sorted(grouped.items()):
        clauses = [
            "## 1. Subject matter",
            "",
            f"The Processor provides: {'; '.join(sorted(e['purposes']))}.",
            "",
            "## 2. Personal data",
            "",
            *[f"- {item}" for item in sorted(e["data"])],
            "",
            "## 3. Instructions",
            "",
            "The Processor processes personal data only on documented instructions "
            "from the Controller and keeps it confidential.",
            "",
            "## 4. Security",
            "",
            "The Processor applies appropriate technical and organisational measures "
            "and notifies the Controller of a personal data breach without undue delay.",
            "",
            "## 5. Sub-processors",
            "",
            "The Processor uses sub-processors only with the Controller's prior "
            "written authorisation.",
            "",
        ]
        if e["basis"] == "scc":
            clauses += [
                "## 6. International transfers",
                "",
                "Transfers to a third country are covered by the "
                "standard contractual clauses attached as Annex 1.",
                "",
            ]
        elif e["basis"] == "adequacy":
            clauses += [
                "## 6. International transfers",
                "",
                "Processing takes place in a country covered by an " "adequacy decision.",
                "",
            ]
        elif is_third_country(e["country"]):
            clauses += [
                "## 6. International transfers",
                "",
                "(No transfer clause is included in this agreement.)",
                "",
            ]
        else:
            clauses += [
                "## 6. Location",
                "",
                "Processing takes place inside the European Economic Area.",
                "",
            ]
        clauses += [
            "## 7. Deletion",
            "",
            "On termination the Processor deletes or returns all personal data.",
        ]
        documents[slug(vendor) + ".md"] = "\n".join(
            [
                f"# Data processing agreement: Northbridge Group and {vendor}",
                "",
                "_Synthetic agreement for the demonstration estate. Not a legal document._",
                "",
                f"Controller: Northbridge Group. Processor: {vendor} ({e['country']}). "
                f"Systems covered: {', '.join(sorted(e['systems']))}.",
                "",
                *clauses,
            ]
        )
    return documents


# ---------------------------------------------------------------------------------------------
# Reference outputs and index files
# ---------------------------------------------------------------------------------------------
def contradiction_entries() -> list[dict[str, Any]]:
    entries = []
    for c in CONTRADICTIONS:
        kinds = sorted({k for t in c["types"] for k in EVIDENCE_BY_TYPE[t]})
        spec = next(s for s in SYSTEMS if s["id"] == c["system"])
        base = f"estate/{c['system']}"
        files = {
            "policy": f"{base}/policy.md",
            "questionnaire": f"{base}/questionnaire.json",
            "har": f"{base}/evidence/capture.har",
            "html": f"{base}/evidence/website_snapshot.html",
            "js": f"{base}/evidence/{bundle_filename(spec)}",
            "sqlite": f"{base}/evidence/snapshot.sqlite",
            "company_policy": "policies/company_privacy_policy.md",
        }
        entries.append({**c, "evidence_files": [files[k] for k in kinds]})
    return entries


def reference_outputs(artifacts_by_system: dict[str, dict[str, Any]]) -> dict[str, Any]:
    elements = []
    recipients = []
    for spec in SYSTEMS:
        truth = artifacts_by_system[spec["id"]]
        elements += [
            {
                "system": spec["id"],
                "element": e["id"],
                "category": e["category"],
                "special_category": e["special_category"],
            }
            for e in truth["data_elements"]
        ]
        for r in truth["recipients"]:
            recipients += [
                {
                    "system": spec["id"],
                    "host": h,
                    "recipient": r["id"],
                    "vendor": r["vendor"],
                    "country": r["country"],
                    "role": r["role"],
                    "internal": r["internal"],
                }
                for h in r["hosts"]
            ]
    dpia = [
        {
            "system": s["id"],
            "criteria_met": sorted(s["dpia"]["criteria"]),
            "assessment_required": s["dpia"]["required"],
        }
        for s in SYSTEMS
    ]
    return {
        "elements.json": {
            "description": "Expected classification of every data element.",
            "items": elements,
        },
        "recipients.json": {
            "description": "Expected recipient hosts with vendor, role and country.",
            "items": recipients,
        },
        "contradictions.json": {
            "description": "Seeded contradictions. A correct fusion step reports each entry with the listed types.",
            "items": contradiction_entries(),
        },
        "dpia_screening.json": {
            "description": "Rubric for impact assessment screening: two or more criteria means an assessment is required.",
            "threshold": 2,
            "items": dpia,
        },
        "summary.json": {
            "systems": len(SYSTEMS),
            "elements": len(elements),
            "special_category_elements": sum(1 for e in elements if e["special_category"]),
            "recipient_hosts": len(recipients),
            "contradictions": len(CONTRADICTIONS),
            "reference_date": REFERENCE_DATE,
        },
    }


def write_system_documents(spec: dict[str, Any], out_dir: Path, truth: dict[str, Any]) -> None:
    write_text(out_dir / "policy.md", policy_markdown(spec))
    write_json(out_dir / "questionnaire.json", questionnaire(spec))
    write_json(out_dir / "ground_truth.json", truth)


def write_agreements(datasets_dir: Path = DATASETS_DIR) -> None:
    target = datasets_dir / "policies" / "vendor_agreements"
    if target.exists():
        for old in target.glob("*.md"):
            old.unlink()
    for name, text in vendor_agreements().items():
        write_text(target / name, text)
