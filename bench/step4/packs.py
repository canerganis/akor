"""Separate module copies of the step 4 harness for another frozen pack (the boundary adoption's v2).

workflow.py, g3b.py and evaluator.py read their pack directory from a module global PACK (default: the v1 pack). load()
executes a fresh copy of one of them under its own module name with PACK set before its code runs, so the v1 modules
that other harnesses and tests import stay exactly as they are. harness() is a copy of step4.py with its workflow,
predicate and evaluator bound to the copies of the same pack. Standard library only.
"""
from __future__ import annotations

from importlib import util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
V2 = 'inspection-handoff-20-v2'
for p in (str(HERE.parents[1]), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _key(name: str, pack: str) -> str:
    return f'{name}__{pack.replace("-", "_")}'


def load(name: str, pack: str = V2):
    """A copy of bench/step4/<name>.py that reads pack (cached per process)."""
    key = _key(name, pack)
    if key in sys.modules:
        return sys.modules[key]
    found = util.spec_from_file_location(key, HERE / f'{name}.py')
    module = util.module_from_spec(found)
    module.PACK = pack
    sys.modules[key] = module
    try:
        found.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(key, None)
        raise
    return module


def harness(pack: str = V2):
    """A copy of step4.py whose W, G and E are the pack's copies (its own module state: RERUN, ENTRY)."""
    module = load('step4', pack)
    module.W, module.G, module.E = load('workflow', pack), load('g3b', pack), load('evaluator', pack)
    return module
