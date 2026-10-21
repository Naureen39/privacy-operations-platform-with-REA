"""Loading of the knowledge files the classifier uses: the personal data taxonomy, the Article 9
categories, the vendor registry and the tuned thresholds. They live in datasets/regulation/."""

import hashlib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "datasets" / "regulation"


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    definition: str
    synonyms: tuple[str, ...]
    pattern_classes: tuple[str, ...]
    sensitivity: str
    special_category: bool


@dataclass(frozen=True)
class SpecialCategory:
    id: str
    label: str
    synonyms: tuple[str, ...]


@dataclass(frozen=True)
class VendorEntry:
    pattern: str
    vendor: str
    role: str
    country: str
    category: str
    fictional: bool = False


@dataclass(frozen=True)
class Thresholds:
    """Decision thresholds. `tuned_on` and `metrics` document how they were chosen."""

    version: str
    rule_accept: float
    rule_margin: float
    embedding_accept: float
    embedding_margin: float
    special_near: float
    review_floor: float
    non_personal_tokens: tuple[str, ...]
    prefix_tokens: tuple[str, ...]
    meta: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class Knowledge:
    categories: dict[str, Category]
    special: dict[str, SpecialCategory]
    vendors: tuple[VendorEntry, ...]
    first_party: tuple[str, ...]
    thresholds: Thresholds
    version: str  # hash of the taxonomy files, stored with the indexed entries


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_knowledge(directory: Path | None = None) -> Knowledge:
    base = directory or DEFAULT_DIR
    taxonomy_path = base / "taxonomy" / "personal_data_taxonomy.json"
    special_path = base / "taxonomy" / "special_categories.json"
    config_path = base / "taxonomy" / "classifier_config.json"
    vendor_path = base / "vendor_registry.yaml"

    categories = {
        c["id"]: Category(
            id=c["id"],
            label=c["label"],
            definition=c["definition"],
            synonyms=tuple(c["synonyms"]),
            pattern_classes=tuple(c.get("pattern_classes", [])),
            sensitivity=c["sensitivity"],
            special_category=bool(c["special_category"]),
        )
        for c in _read_json(taxonomy_path)["categories"]
    }
    special = {
        c["id"]: SpecialCategory(c["id"], c["label"], tuple(c["synonyms"]))
        for c in _read_json(special_path)["categories"]
    }
    registry = yaml.safe_load(vendor_path.read_text(encoding="utf-8"))
    vendors = tuple(
        VendorEntry(
            v["pattern"].lower(),
            v["vendor"],
            v["role"],
            v["country"],
            v["category"],
            bool(v.get("fictional")),
        )
        for v in registry["vendors"]
    )
    config = _read_json(config_path)
    thresholds = Thresholds(
        version=config["version"],
        rule_accept=config["rule_accept"],
        rule_margin=config["rule_margin"],
        embedding_accept=config["embedding_accept"],
        embedding_margin=config["embedding_margin"],
        special_near=config["special_near"],
        review_floor=config["review_floor"],
        non_personal_tokens=tuple(config["non_personal_tokens"]),
        prefix_tokens=tuple(config["prefix_tokens"]),
        meta=config.get("meta", {}),
    )
    digest = hashlib.sha256()
    for path in (taxonomy_path, special_path):
        digest.update(path.read_bytes())
    return Knowledge(
        categories,
        special,
        vendors,
        tuple(h.lower() for h in registry["first_party"]),
        thresholds,
        digest.hexdigest()[:16],
    )


@lru_cache
def default_knowledge() -> Knowledge:
    return load_knowledge()
