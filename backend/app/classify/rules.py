"""The rule layer: deterministic evidence for a category.

Sources, strongest first: the HTML `autocomplete` hint, the value pattern (e-mail, IP address,
payment card with Luhn check, IBAN with mod 97 check, password hash and so on), the input type,
the name compared with the taxonomy's synonyms, and the label compared with the same synonyms.
Each source scores the categories it supports; the best score per category wins and a second
independent source adds a little.
"""

from dataclasses import dataclass, field

from app.classify.features import ElementFeatures
from app.classify.knowledge import Knowledge
from app.classify.normalize import contains_sequence, expand, split_identifier, strip_prefixes

# autocomplete token -> category
AUTOCOMPLETE_CATEGORY = {
    "name": "name", "given-name": "name", "additional-name": "name", "family-name": "name", "cc-name": "name",
    "email": "contact_email", "tel": "contact_phone", "tel-national": "contact_phone",
    "bday": "date_of_birth", "bday-day": "date_of_birth", "sex": "gender",
    "street-address": "postal_address", "address-line1": "postal_address", "address-line2": "postal_address",
    "address-level1": "postal_address", "address-level2": "postal_address", "postal-code": "postal_address",
    "country": "postal_address", "country-name": "postal_address",
    "organization": "employment_data", "organization-title": "employment_data",
    "username": "online_identifier", "new-password": "authentication_credentials",
    "current-password": "authentication_credentials", "cc-number": "payment_card", "cc-exp": "payment_card",
    "cc-csc": "payment_card",
}  # fmt: skip

# value pattern -> (category, score)
PATTERN_CATEGORY = {
    "email": ("contact_email", 0.97),
    "ip_address": ("ip_address", 0.94),
    "payment_card": ("payment_card", 0.95),
    "iban": ("bank_account", 0.95),
    "password_hash": ("authentication_credentials", 0.95),
    "phone": ("contact_phone", 0.82),
    "coordinate": ("geolocation", 0.82),
}  # fmt: skip

INPUT_TYPE_CATEGORY = {
    "email": ("contact_email", 0.95),
    "tel": ("contact_phone", 0.92),
    "password": ("authentication_credentials", 0.95),
}

# Values of these kinds identify or describe a person even when the name is technical (an `_id`
# parameter that carries a hex token, a `uid` that carries e-mail addresses).
PERSONAL_PATTERNS = {
    "email",
    "ip_address",
    "payment_card",
    "iban",
    "phone",
    "password_hash",
    "hex_token",
    "uuid",
    "coordinate",
}
BIRTH_TOKENS = {"dob", "birth", "birthdate", "birthday", "bday", "born"}
CONSENT_TOKENS = {"consent", "optin", "subscribed", "gdpr"}
# Words that match many fields on their own, so alone they never make a rule decision.
GENERIC_TOKENS = {
    "name",
    "address",
    "id",
    "date",
    "type",
    "number",
    "data",
    "info",
    "value",
    "code",
    "text",
    "order",
    "total",
    "no",
}


@dataclass
class RuleHit:
    score: float
    reasons: list[str] = field(default_factory=list)

    def add(self, score: float, reason: str) -> None:
        if score > self.score:
            self.score = score
        self.reasons.append(reason)


def _synonym_index(knowledge: Knowledge) -> list[tuple[str, list[str], list[str]]]:
    """(category, synonym tokens, synonym tokens without qualifiers) for every taxonomy synonym."""
    prefixes = knowledge.thresholds.prefix_tokens
    entries = []
    for category in knowledge.categories.values():
        for synonym in category.synonyms:
            tokens = split_identifier(synonym)
            if tokens:
                entries.append((category.id, tokens, strip_prefixes(tokens, prefixes)))
    return entries


class RuleEngine:
    def __init__(self, knowledge: Knowledge) -> None:
        self.knowledge = knowledge
        self.prefixes = knowledge.thresholds.prefix_tokens
        self.index = _synonym_index(knowledge)

    # -- individual sources ---------------------------------------------------------------------
    def _match_phrase(
        self, tokens: list[str], source: str, hits: dict[str, RuleHit], weight: float
    ) -> None:
        """Compare a tokenised name or label with every synonym."""
        if not tokens:
            return
        core = strip_prefixes(tokens, self.prefixes)
        for category, syn_tokens, syn_core in self.index:
            score = 0.0
            how = ""
            if tokens == syn_tokens:
                score, how = 0.95, "exact synonym"
            elif core == syn_core and not (len(core) == 1 and core[0] in GENERIC_TOKENS):
                score, how = 0.92, "synonym without qualifiers"
            elif len(syn_tokens) >= 2 and contains_sequence(tokens, syn_tokens):
                score, how = 0.88, "contains multi word synonym"
            elif len(syn_core) >= 2 and contains_sequence(core, syn_core):
                score, how = 0.86, "contains multi word synonym"
            elif len(syn_tokens) == 1 and syn_tokens[0] in tokens and len(tokens) > 1:
                score, how = (
                    0.7 if syn_tokens[0] in GENERIC_TOKENS else 0.8
                ), "contains synonym word"
            if score:
                hit = hits.setdefault(category, RuleHit(0.0))
                hit.add(score * weight, f"{source}: {how} ({'_'.join(syn_tokens)})")

    def evaluate(self, features: ElementFeatures) -> dict[str, RuleHit]:
        hits: dict[str, RuleHit] = {}
        tokens = features.tokens
        words = expand(tokens)

        if features.autocomplete:
            category = AUTOCOMPLETE_CATEGORY.get(features.autocomplete.split()[-1].lower())
            if category:
                hits.setdefault(category, RuleHit(0.0)).add(
                    0.95, f"autocomplete hint {features.autocomplete}"
                )

        if features.pattern_class in PATTERN_CATEGORY:
            category, score = PATTERN_CATEGORY[features.pattern_class]
            hits.setdefault(category, RuleHit(0.0)).add(
                score, f"values look like {features.pattern_class}"
            )
        if features.pattern_class in {"date", "datetime"} and BIRTH_TOKENS & set(tokens):
            hits.setdefault("date_of_birth", RuleHit(0.0)).add(
                0.92, "date value with a birth word in the name"
            )
        if features.pattern_class == "uuid" or features.pattern_class == "hex_token":
            hits.setdefault("online_identifier", RuleHit(0.0)).add(
                0.6, f"values look like {features.pattern_class}"
            )
        if features.pattern_class == "free_text":
            hits.setdefault("communications_content", RuleHit(0.0)).add(
                0.6, "values look like free text"
            )
        if features.pattern_class == "url":
            hits.setdefault("browsing_behavior", RuleHit(0.0)).add(0.6, "values look like URLs")

        if features.input_type in INPUT_TYPE_CATEGORY:
            category, score = INPUT_TYPE_CATEGORY[features.input_type]
            hits.setdefault(category, RuleHit(0.0)).add(score, f"input type {features.input_type}")
        if features.input_type == "date" and BIRTH_TOKENS & set(tokens):
            hits.setdefault("date_of_birth", RuleHit(0.0)).add(
                0.92, "date input with a birth word in the name"
            )
        if features.input_type == "checkbox" and CONSENT_TOKENS & set(tokens):
            hits.setdefault("consent_record", RuleHit(0.0)).add(
                0.9, "checkbox with a consent word in the name"
            )

        self._match_phrase(tokens, "name", hits, 1.0)
        if words != tokens:  # abbreviations spelled out (ph -> phone, dob -> date of birth)
            self._match_phrase(words, "name (abbreviations expanded)", hits, 0.97)
        if features.location_kind == "cookie":
            hits.setdefault("online_identifier", RuleHit(0.0)).add(0.82, "cookie")
        if features.label:
            self._match_phrase(split_identifier(features.label), "label", hits, 0.93)

        # Independent sources that agree make a decision more certain.
        for hit in hits.values():
            kinds = {r.split(":")[0].split(" ")[0] for r in hit.reasons}
            if len(kinds) >= 2:
                hit.score = min(0.99, hit.score + 0.03)
        return hits

    def non_personal(self, features: ElementFeatures) -> bool:
        """Technical names (timestamps, statuses, tracker site ids) are not personal data on their own."""
        if features.pattern_class in PERSONAL_PATTERNS:
            return False
        words = set(features.tokens) | set(expand(features.tokens))
        return bool(words & set(self.knowledge.thresholds.non_personal_tokens)) and not (
            words & {"email", "phone", "ip", "address", "name", "birth", "card", "iban", "password"}
        )
