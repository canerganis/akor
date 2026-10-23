"""ASCII identifiers for export columns.

Labels are arbitrary strings. Slugs retain ASCII letters and digits,
lowercase letters, and replace runs of other characters with a hyphen.
Unicode characters are separators, without transliteration.
"""


def slug(label: str) -> str:
    """Return a normalized identifier, or 'item' if nothing remains."""
    parts: list[str] = []
    pending_separator = False
    for character in label:
        is_letter = "a" <= character <= "z" or "A" <= character <= "Z"
        is_digit = "0" <= character <= "9"
        if is_letter or is_digit:
            if pending_separator and parts:
                parts.append("-")
            parts.append(character.lower())
            pending_separator = False
        else:
            pending_separator = True
    normalized = "".join(parts)
    return normalized or "item"


def unique_labels(labels: list[str]) -> list[str]:
    """Slug labels in order, adding the first unused suffix from 2."""
    used: set[str] = set()
    result: list[str] = []
    for label in labels:
        base = slug(label)
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}-{suffix}"
            suffix += 1
        used.add(candidate)
        result.append(candidate)
    return result


def make_header(labels: list[str], delimiter: str = ",") -> str:
    """Join unique identifiers using one allowed delimiter."""
    allowed = (",", ";", "\t", "|")
    if delimiter not in allowed:
        raise ValueError("unsupported delimiter")
    normalized_labels = unique_labels(labels)
    return delimiter.join(normalized_labels)


def label_map(labels: list[str]) -> dict[str, str]:
    """Map each generated unique identifier to its original label."""
    identifiers = unique_labels(labels)
    result: dict[str, str] = {}
    for identifier, original in zip(identifiers, labels):
        result[identifier] = original
    return result


def is_slug(value: str) -> bool:
    """Whether value is a nonempty canonical identifier."""
    if not value:
        return False
    return slug(value) == value
