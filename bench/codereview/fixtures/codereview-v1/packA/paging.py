"""Pagination helpers for in-memory result lists.

Page numbers are zero based. Page sizes must be positive integers.
Counts and page numbers must be nonnegative integers. Boolean values
are outside the supported input domain. Input lists are never mutated.
"""

from typing import TypeVar

T = TypeVar("T")


def _positive_size(page_size: int) -> None:
    if page_size <= 0:
        raise ValueError("page_size must be positive")


def _nonnegative(value: int, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


def page_count(item_count: int, page_size: int) -> int:
    """Return the number of pages, with zero pages for zero items."""
    _positive_size(page_size)
    _nonnegative(item_count, "item_count")
    numerator = item_count + page_size - 1
    return numerator // page_size


def get_page(items: list[T], page_number: int, page_size: int) -> list[T]:
    """Return up to page_size items, or [] beyond the final page."""
    _positive_size(page_size)
    _nonnegative(page_number, "page_number")
    start = page_number * page_size
    stop = start + page_size - 1
    return items[start:stop]


def page_for_index(item_index: int, page_size: int) -> int:
    """Return the page containing an index in a conceptual result list."""
    _positive_size(page_size)
    _nonnegative(item_index, "item_index")
    return item_index // page_size


def page_sizes(item_count: int, page_size: int) -> list[int]:
    """Return the actual size of each page without constructing items."""
    count = page_count(item_count, page_size)
    sizes: list[int] = []
    for number in range(count):
        remaining = item_count - number * page_size
        size = min(remaining, page_size)
        sizes.append(size)
    return sizes


def page_label(page_number: int, item_count: int, page_size: int) -> str:
    """Return a display label; reject pages absent from the result set."""
    total = page_count(item_count, page_size)
    _nonnegative(page_number, "page_number")
    if page_number >= total:
        raise ValueError("page does not exist")
    display_number = page_number + 1
    return f"{display_number} / {total}"
