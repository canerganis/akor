"""Preregistered fault boundaries (foundation record clause 5 tests; step 4 plan C7). Standard library only.

point(name) is a no-op unless the boundary is armed. A boundary is armed for a process by the environment variable
OZ_FAULTS (comma-separated names): reaching it then ends the process at once with os._exit(KILL_EXIT), so no cleanup,
finally block or context manager runs, exactly like a hard kill. Tests and harnesses can also register an in-process
hook for a name (for example a preregistered source mutation); a hook runs and execution continues.
"""
from __future__ import annotations

import os
from typing import Callable

KILL_EXIT = 86
hooks: dict[str, list[Callable[[str], None]]] = {}


def armed() -> set:
    return {n.strip() for n in os.environ.get('OZ_FAULTS', '').split(',') if n.strip()}


def point(name: str) -> None:
    for hook in list(hooks.get(name, ())):
        hook(name)
    if name in armed():
        os._exit(KILL_EXIT)


def on(name: str, hook: Callable[[str], None]) -> Callable[[], None]:
    """Register an in-process hook; returns a function that removes it."""
    hooks.setdefault(name, []).append(hook)
    return lambda: hooks.get(name, []).remove(hook) if hook in hooks.get(name, []) else None
