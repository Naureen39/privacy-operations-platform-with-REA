from dataclasses import dataclass, field
from typing import Any

from app.classify.normalize import AUTOCOMPLETE_WORDS, expand, split_identifier

TYPE_WORDS = {
    "email": "email address",
    "tel": "telephone number",
    "password": "password",
    "date": "date",
    "checkbox": "yes or no choice",
    "textarea": "free text",
    "hidden": "hidden value",
    "number": "number",
}


@dataclass(frozen=True)
class ElementFeatures:
    """What the classifier knows about one discovered element. Never contains sample values."""

    name: str
    location_kind: str
    data_type: str | None = None
    pattern_class: str | None = None
    label: str | None = None
    autocomplete: str | None = None
    input_type: str | None = None
    table: str | None = None
    table_columns: tuple[str, ...] = ()
    source_kind: str | None = None
    extra: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_context(
        cls,
        name: str,
        context: dict[str, Any],
        *,
        data_type: str | None,
        pattern_class: str | None,
        source_kind: str | None,
    ) -> "ElementFeatures":
        return cls(
            name=name,
            location_kind=str(context.get("location_kind", "")),
            data_type=data_type,
            pattern_class=pattern_class,
            label=context.get("label"),
            autocomplete=context.get("autocomplete"),
            input_type=context.get("input_type"),
            table=context.get("table"),
            table_columns=tuple(context.get("table_columns", ())),
            source_kind=source_kind,
        )

    @property
    def tokens(self) -> list[str]:
        return split_identifier(self.name)

    @property
    def words(self) -> list[str]:
        return expand(self.tokens)

    def description(self) -> str:
        """The text that is embedded. Names, labels and types only: no values."""
        parts = [" ".join(self.words) or self.name]
        if self.label:
            parts.append(f"labelled {self.label}")
        if self.autocomplete:
            hint = AUTOCOMPLETE_WORDS.get(self.autocomplete.split()[-1].lower())
            if hint:
                parts.append(f"asks for {hint}")
        if self.input_type and self.input_type in TYPE_WORDS:
            parts.append(f"input type {TYPE_WORDS[self.input_type]}")
        elif self.data_type and self.source_kind != "sqlite_snapshot":
            parts.append(f"type {self.data_type}")
        if self.pattern_class:
            parts.append(f"values look like {self.pattern_class.replace('_', ' ')}")
        if self.table:
            parts.append(f"in table {' '.join(expand(split_identifier(self.table)))}")
        return "; ".join(parts)
