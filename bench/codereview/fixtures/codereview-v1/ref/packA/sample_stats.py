"""Small summaries for bounded sensor samples.

Inputs are lists of finite numbers in [-1000000, 1000000].
Nonfinite and out-of-range values raise ValueError. Other types are
outside the input contract. Empty data is valid and represents no data.
"""

import math


def _checked(values: list[float]) -> list[float]:
    result: list[float] = []
    for value in values:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("samples must be finite")
        if abs(number) > 1000000:
            raise ValueError("sample outside supported range")
        result.append(number)
    return result


def mean(values: list[float]) -> float | None:
    """Return the arithmetic mean, or None when there are no samples."""
    checked = _checked(values)
    if not checked:
        return None
    total = math.fsum(checked)
    return total / len(checked)


def spread(values: list[float]) -> float | None:
    """Return maximum minus minimum, or None for an empty list."""
    checked = _checked(values)
    if not checked:
        return None
    smallest = min(checked)
    largest = max(checked)
    return largest - smallest


def latest(values: list[float], limit: int) -> list[float]:
    """Return the last limit samples; limit is a nonnegative integer."""
    if limit < 0:
        raise ValueError("limit must be nonnegative")
    checked = _checked(values)
    if limit == 0:
        return []
    return checked[-limit:]


def describe(values: list[float]) -> dict:
    """Return count, mean and spread using the same empty-data policy."""
    checked = _checked(values)
    summary = {
        "count": len(checked),
        "mean": mean(checked),
        "spread": spread(checked),
    }
    return summary


def centered(values: list[float]) -> list[float]:
    """Subtract the mean; an empty input produces an empty output."""
    checked = _checked(values)
    if not checked:
        return []
    average = mean(checked)
    return [value - average for value in checked]
