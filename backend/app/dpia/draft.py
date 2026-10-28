"""Draft the sections of an assessment: two assistant calls with retrieved regulation text, with the
risk catalogue and templates as the fallback when no provider can answer. The assistant's risks
must cite passages it was given; the gaps found by the comparison become risks with evidence."""

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from sqlalchemy.orm import Session

from app.db.models import Finding, ProcessingActivity
from app.dpia.service import RiskInput
from app.knowledge.retrieval import Filters, HybridRetriever, Passage
from app.llm.errors import LLMError
from app.llm.router import LLMRouter
from app.llm.schemas import DpiaRisk, DpiaSections
from app.llm.tasks import Scope, draft_dpia_sections

HERE = Path(__file__).resolve().parent
MAX_RISKS = 7
_env = Environment(
    loader=FileSystemLoader(HERE / "templates"),
    undefined=StrictUndefined,
    autoescape=False,  # noqa: S701  # nosec B701
    trim_blocks=True,
    lstrip_blocks=True,
)
CATALOGUE: dict[str, Any] = json.loads((HERE / "risk_catalogue.json").read_text(encoding="utf-8"))[
    "criteria"
]
DESCRIPTION_ARTICLES = (35, 5)  # the content of an assessment; the principles


@dataclass
class Draft:
    description: str
    necessity: str
    risks: list[RiskInput]
    sources: dict[str, str]  # section -> "assistant" or "template" / "catalogue"
    tokens: int = 0
    calls: int = 0
    notes: list[str] = field(default_factory=list)


class Drafter:
    def __init__(
        self,
        db: Session,
        retriever: HybridRetriever,
        router: LLMRouter | None,
        labels: dict[str, str],
    ) -> None:
        self.db = db
        self.retriever = retriever
        self.router = router
        self.labels = labels

    def draft(
        self,
        activity: ProcessingActivity,
        met_criteria: list[tuple[str, str]],  # (id, label)
        special: list[str],
        findings: list[Finding],
        scope: Scope,
    ) -> Draft:
        facts = self._facts(activity, special)
        met_ids = [c for c, _ in met_criteria]
        out = Draft("", "", [], {})

        description_passages = self._passages(
            [
                ("content of an impact assessment necessity and proportionality", 35),
                ("principles relating to processing", 5),
            ]
        )
        risk_queries = [
            (CATALOGUE[c]["query"], CATALOGUE[c]["articles"][0]) for c in met_ids if c in CATALOGUE
        ][:4]
        risk_passages = self._passages(risk_queries) or description_passages[:2]

        sections = self._ask(scope, "description", facts, met_ids, description_passages, out)
        if sections is not None and sections.description and sections.necessity_and_proportionality:
            out.description, out.necessity = (
                sections.description,
                sections.necessity_and_proportionality,
            )
            out.sources["description"] = out.sources["necessity"] = "assistant"
        else:
            out.description, out.necessity = self._template_texts(facts, met_criteria, activity)
            out.sources["description"] = out.sources["necessity"] = "template"

        by_id = {str(p.id): p for p in risk_passages}
        sections = self._ask(scope, "risks", facts, met_ids, risk_passages, out)
        if sections is not None and sections.risks:
            out.risks = [self._model_risk(r, by_id) for r in sections.risks]
            out.sources["risks"] = "assistant"
        else:
            out.risks = self._catalogue_risks(met_ids)
            out.sources["risks"] = "catalogue"
        out.risks = (out.risks + self._gap_risks(findings, {r.title for r in out.risks}))[
            :MAX_RISKS
        ]
        return out

    # -- assistant ---------------------------------------------------------------------------

    def _ask(
        self,
        scope: Scope,
        part: str,
        facts: dict[str, Any],
        met_ids: list[str],
        passages: list[Passage],
        out: Draft,
    ) -> DpiaSections | None:
        if self.router is None or not self.router.providers or not passages:
            return None
        try:
            sections, result = draft_dpia_sections(
                self.router,
                scope,
                part=part,
                activity=facts,
                criteria_met=met_ids,
                passages=passages,
            )
        except LLMError as exc:
            out.notes.append(f"{part}: assistant unavailable ({type(exc).__name__})")
            return None
        out.calls += 0 if result.cache_hit else 1
        out.tokens += result.tokens
        return sections

    def _model_risk(self, risk: DpiaRisk, passages: dict[str, Passage]) -> RiskInput:
        citation = "; ".join(passages[i].citation for i in risk.cited_passage_ids if i in passages)
        return RiskInput(
            title=risk.risk, description=None, likelihood=risk.likelihood, severity=risk.severity,
            mitigation=risk.mitigation, residual_likelihood=max(1, risk.likelihood - 1),
            residual_severity=risk.severity, citation=citation,
        )  # fmt: skip

    # -- fallbacks and gap risks -------------------------------------------------------------

    def _template_texts(
        self, facts: dict[str, Any], met: list[tuple[str, str]], activity: ProcessingActivity
    ) -> tuple[str, str]:
        description = _env.get_template("description.j2").render(
            name=facts["name"], categories=facts["data_categories"], subjects=facts["data_subjects"],
            purposes=facts["purposes"], recipients=[r["vendor"] for r in facts["recipients"]],
            transfers=[f"{t['country']} ({t['mechanism']})" for t in facts["transfers"]],
            special=facts["special_categories"], retention=facts["retention"], criteria=[label for _, label in met],
        ).strip()  # fmt: skip
        necessity = _env.get_template("necessity.j2").render(
            basis=(activity.lawful_basis or "").replace("_", " "),
            special_condition=(activity.special_category_condition or "").replace("_", " "),
            special=facts["special_categories"], retention=facts["retention"],
        ).strip()  # fmt: skip
        return description, necessity

    def _catalogue_risks(self, met_ids: list[str]) -> list[RiskInput]:
        risks = []
        for cid in met_ids:
            entry = CATALOGUE.get(cid)
            if entry is None:
                continue
            citation = self._article_citations(entry)
            risks.append(self._from_catalogue(entry, citation))
        return risks

    def _gap_risks(self, findings: list[Finding], have: set[str]) -> list[RiskInput]:
        kinds = {"third_country_no_safeguard": "transfer_gap", "missing_agreement": "agreement_gap"}
        risks = []
        for key in dict.fromkeys(kinds[f.type] for f in findings if f.type in kinds):
            entry = CATALOGUE[key]
            if entry["title"] in have:
                continue
            related = [f for f in findings if kinds.get(f.type) == key][:3]
            evidence = "; ".join(f"finding:{f.id}" for f in related)
            risks.append(
                self._from_catalogue(
                    entry, "; ".join(x for x in (self._article_citations(entry), evidence) if x)
                )
            )
        return risks

    def _from_catalogue(self, entry: dict[str, Any], citation: str) -> RiskInput:
        return RiskInput(
            title=entry["title"], description=None, likelihood=entry["likelihood"], severity=entry["severity"],
            mitigation=entry["mitigation"], residual_likelihood=max(1, entry["likelihood"] - 1),
            residual_severity=entry["severity"], citation=citation,
        )  # fmt: skip

    def _article_citations(self, entry: dict[str, Any]) -> str:
        found = self._passages([(entry["query"], n) for n in entry["articles"][:2]])
        return "; ".join(p.citation for p in found)

    # -- retrieval and facts -----------------------------------------------------------------

    def _passages(self, queries: list[tuple[str, int]]) -> list[Passage]:
        seen: dict[uuid.UUID, Passage] = {}
        for query, article in queries:
            result = self.retriever.search(
                query,
                top_k=1,
                filters=Filters(articles=(article,), sources=("regulation",)),
                rerank=False,
            )
            for passage in result.passages:
                seen.setdefault(passage.id, passage)
        return list(seen.values())

    def _facts(self, activity: ProcessingActivity, special: list[str]) -> dict[str, Any]:
        measures = [
            m.lstrip("- ").strip()
            for m in (activity.security_measures or "").splitlines()
            if m.strip()
        ]
        return {
            "name": activity.name,
            "purposes": list(activity.purposes)[:6],
            "data_subjects": list(activity.data_subjects)[:6],
            "data_categories": [self.labels.get(c, c) for c in activity.data_categories][:14],
            "special_categories": [self.labels.get(c, c) for c in special],
            "recipients": [{"vendor": r.get("vendor", ""), "role": r.get("role", ""), "country": r.get("country") or "unknown"} for r in activity.recipients][:8],
            "transfers": [{"country": t.get("country", ""), "mechanism": t.get("mechanism", "")} for t in activity.transfers][:6],
            "retention": (activity.retention or "")[:200],
            "security_measures": measures[:4],
            "lawful_basis": activity.lawful_basis or "",
            "article_9_condition_recorded": bool(activity.special_category_condition),
        }  # fmt: skip
