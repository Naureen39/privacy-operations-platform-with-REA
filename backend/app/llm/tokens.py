import math


def estimate_tokens(text: str) -> int:
    """A deliberately high estimate (JSON and identifiers tokenize badly): about 3.5 characters
    per token. Real usage comes back from the provider and is what gets logged and budgeted."""
    return math.ceil(len(text.encode("utf-8")) / 3.5) if text else 0
