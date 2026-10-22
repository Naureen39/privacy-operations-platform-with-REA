"""Output schemas of the five LLM tasks. Every field is required (strict JSON schema mode needs
that) and every string is length limited, so an answer cannot grow past the token cap."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ShortText = Annotated[str, StringConstraints(max_length=120)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


LawfulBasis = Literal[
    "consent",
    "contract",
    "legal_obligation",
    "vital_interests",
    "public_task",
    "legitimate_interests",
]


class PurposeAndBasis(Strict):
    purposes: list[ShortText] = Field(min_length=1, max_length=5)
    lawful_basis: LawfulBasis
    basis_rationale: str = Field(max_length=300)
    needs_review: bool


class ConflictVerdict(Strict):
    verdict: Literal["supported_by_policy", "contradicts_policy", "undetermined"]
    explanation: str = Field(max_length=400)
    cited_passage_ids: list[str] = Field(max_length=3)


class DpiaRisk(Strict):
    risk: str = Field(max_length=200)
    likelihood: int = Field(ge=1, le=5)
    severity: int = Field(ge=1, le=5)
    mitigation: str = Field(max_length=250)
    cited_passage_ids: list[str] = Field(max_length=3)


class DpiaSections(Strict):
    """Part 1 fills the two texts and leaves `risks` empty; part 2 does the opposite."""

    description: str = Field(max_length=900)
    necessity_and_proportionality: str = Field(max_length=900)
    risks: list[DpiaRisk] = Field(max_length=5)


class CoverNote(Strict):
    note: str = Field(max_length=600)


class Answer(Strict):
    answer: str = Field(max_length=900)
    supported: bool
    cited_passage_ids: list[str] = Field(max_length=5)


class Pong(Strict):
    ok: bool


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve $ref/$defs so providers with a restricted JSON schema dialect accept the schema."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {k: walk(v) for k, v in node.items() if k not in ("$defs", "title")}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    result: dict[str, Any] = walk({k: v for k, v in schema.items() if k != "$defs"})
    return result
