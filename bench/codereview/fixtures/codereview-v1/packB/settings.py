"""Parse simple line-oriented application settings.

Keys are case-sensitive ASCII identifiers starting with a letter or
underscore. Values are strings. Blank lines and whole-line comments
starting with # are ignored. Inline comments and escapes are not used.
"""


def _valid_key(key: str) -> bool:
    if not key:
        return False
    first = key[0]
    if not (first.isascii() and (first.isalpha() or first == "_")):
        return False
    for character in key[1:]:
        if not (character.isascii() and (character.isalnum() or character == "_")):
            return False
    return True


def parse_settings(text: str) -> dict[str, str]:
    """Parse key=value lines; duplicate keys use the last value."""
    settings: dict[str, str] = {}
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not _valid_key(key):
            raise ValueError(f"invalid setting on line {line_number}")
        settings[key] = value.strip()
    return settings


def render_settings(settings: dict[str, str]) -> str:
    """Render sorted keys with one final newline, or '' for no keys.

    Values must have no outer whitespace or splitlines line boundaries.
    These restrictions make rendering and parsing exact inverses.
    """
    lines: list[str] = []
    for key, value in sorted(settings.items()):
        if not _valid_key(key):
            raise ValueError("invalid setting key")
        if value != value.strip():
            raise ValueError("value has outer whitespace")
        if value and value.splitlines() != [value]:
            raise ValueError("value contains a line boundary")
        lines.append(f"{key}={value}")
    return "\n".join(lines) + ("\n" if lines else "")


def overlay(base: dict[str, str], updates: dict[str, str]) -> dict[str, str]:
    """Return a new mapping with updates taking precedence."""
    combined = dict(base)
    combined.update(updates)
    return combined


def select_prefix(settings: dict[str, str], prefix: str) -> dict[str, str]:
    """Select matching keys without removing the prefix."""
    return {key: value for key, value in settings.items() if key.startswith(prefix)}
