"""The 5 by 5 risk matrix: likelihood times severity, in four bands."""

from collections.abc import Iterable

LEVELS = ("low", "medium", "high", "very_high")


def score(likelihood: int, severity: int) -> int:
    return likelihood * severity


def level(likelihood: int, severity: int) -> str:
    value = score(likelihood, severity)
    if value <= 4:
        return "low"
    if value <= 9:
        return "medium"
    if value <= 15:
        return "high"
    return "very_high"


def worst(levels: Iterable[str]) -> str | None:
    ranked = sorted(set(levels), key=LEVELS.index)
    return ranked[-1] if ranked else None


def grid(pairs: Iterable[tuple[int, int]]) -> list[list[int]]:
    """Counts per cell; rows are severity 5 down to 1, columns likelihood 1 up to 5."""
    cells = [[0] * 5 for _ in range(5)]
    for likelihood, severity in pairs:
        cells[5 - severity][likelihood - 1] += 1
    return cells
