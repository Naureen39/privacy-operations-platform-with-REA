"""Versioned prompt files and the registry of the five tasks (plus a connection test).

Each prompt is `prompt_files/<task>.v<N>.md`; the constant prefix (common rules, then the task text) is
sent first so provider side prompt caching applies. The version and the SHA-256 of the text are part
of the cache key, so editing a prompt never serves an answer produced by the old one.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.llm import schemas

PROMPT_DIR = Path(__file__).resolve().parent / "prompt_files"
Check = Callable[[dict[str, Any], Any], None]


@dataclass(frozen=True)
class PromptSpec:
    task: str
    version: int
    system: str
    output_model: type[BaseModel]
    check: Check | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.system.encode("utf-8")).hexdigest()

    @property
    def schema(self) -> dict[str, Any]:
        return schemas.inline_refs(self.output_model.model_json_schema())

    @property
    def schema_name(self) -> str:
        return self.task


def _ids(payload: dict[str, Any]) -> set[str]:
    return {str(p.get("id")) for p in payload.get("passages", []) if isinstance(p, dict)}


def _check_citations(payload: dict[str, Any], cited: list[str]) -> None:
    unknown = set(cited) - _ids(payload)
    if unknown:
        raise ValueError(f"cited passage ids not in the input: {sorted(unknown)}")


def _check_conflict(payload: dict[str, Any], data: schemas.ConflictVerdict) -> None:
    _check_citations(payload, data.cited_passage_ids)
    if data.verdict != "undetermined" and not data.cited_passage_ids:
        raise ValueError("a verdict needs at least one cited passage")
    if len(payload.get("passages", [])) > 3:
        raise ValueError("at most 3 passages may be sent")


def _check_answer(payload: dict[str, Any], data: schemas.Answer) -> None:
    _check_citations(payload, data.cited_passage_ids)
    if data.supported != bool(data.cited_passage_ids):
        raise ValueError("an answer is supported exactly when it cites passages")


def _check_dpia(payload: dict[str, Any], data: schemas.DpiaSections) -> None:
    for risk in data.risks:
        _check_citations(payload, risk.cited_passage_ids)
        if not risk.cited_passage_ids:
            raise ValueError("every risk must cite a passage")
    if payload.get("part") == "description":
        if data.risks or not data.description:
            raise ValueError("part description returns the texts and no risks")
    elif payload.get("part") == "risks" and (
        data.description or data.necessity_and_proportionality or not data.risks
    ):
        raise ValueError("part risks returns risks and no texts")


_TASKS: dict[str, tuple[int, type[BaseModel], Check | None]] = {
    "suggest_purpose_and_basis": (1, schemas.PurposeAndBasis, None),
    "adjudicate_conflict": (1, schemas.ConflictVerdict, _check_conflict),
    "draft_dpia_sections": (1, schemas.DpiaSections, _check_dpia),
    "draft_request_cover_note": (1, schemas.CoverNote, None),
    "answer_question": (1, schemas.Answer, _check_answer),
    "ping": (1, schemas.Pong, None),
}
TASKS = tuple(t for t in _TASKS if t != "ping")


def _read(name: str, version: int) -> str:
    return (PROMPT_DIR / f"{name}.v{version}.md").read_text(encoding="utf-8").strip()


_CACHE: dict[str, PromptSpec] = {}


def get_prompt(task: str) -> PromptSpec:
    if task not in _TASKS:
        raise KeyError(f"unknown LLM task: {task}")
    if task not in _CACHE:
        version, model, check = _TASKS[task]
        system = _read("_common", 1) + "\n" + _read(task, version)
        _CACHE[task] = PromptSpec(task, version, system, model, check)
    return _CACHE[task]
