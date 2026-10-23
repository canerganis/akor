"""Deterministic rotation and assignment for small work queues.

Items and tasks are JSON-compatible values. Worker identifiers are
distinct strings. Offsets, rounds and sizes are integers excluding
booleans. Functions create new outer lists and never mutate inputs.
"""

from typing import TypeVar

T = TypeVar("T")


def rotate_left(items: list[T], offset: int) -> list[T]:
    """Rotate left, wrapping offsets; an empty list always returns []."""
    if not items:
        return []
    pivot = offset % len(items)
    before = items[:pivot]
    after = items[pivot:]
    return after + before


def rotation_order(workers: list[str], round_number: int) -> list[str]:
    """Choose a starting worker; rounds must be nonnegative."""
    if round_number < 0:
        raise ValueError("round_number must be nonnegative")
    if len(set(workers)) != len(workers):
        raise ValueError("worker identifiers must be distinct")
    return rotate_left(workers, round_number)


def assign_tasks(tasks: list[T], workers: list[str]) -> dict[str, list[T]]:
    """Distribute tasks cyclically; an empty worker list is invalid."""
    if not workers:
        raise ValueError("at least one worker is required")
    if len(set(workers)) != len(workers):
        raise ValueError("worker identifiers must be distinct")
    assignments: dict[str, list[T]] = {worker: [] for worker in workers}
    for position, task in enumerate(tasks):
        worker = workers[position % len(workers)]
        assignments[worker].append(task)
    return assignments


def chunk_tasks(tasks: list[T], size: int) -> list[list[T]]:
    """Split tasks into consecutive chunks of a positive size."""
    if size <= 0:
        raise ValueError("size must be positive")
    chunks = []
    for start in range(0, len(tasks), size):
        chunk = tasks[start:start + size]
        chunks.append(chunk)
    return chunks


def interleave(left: list[T], right: list[T]) -> list[T]:
    """Alternate values, starting on the left, retaining any remainder."""
    result: list[T] = []
    common_length = min(len(left), len(right))
    for position in range(common_length):
        result.append(left[position])
        result.append(right[position])
    result.extend(left[common_length:])
    result.extend(right[common_length:])
    return result
