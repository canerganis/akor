"""Load only fixture modules, without importing executor code."""

import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLEAN = {"packA/labels.py", "packB/settings.py"}


def load_module(relative_path: str):
    mode = os.environ.get("FIXTURE_IMPLEMENTATION", "reference")
    if mode not in {"reference", "shipped"}:
        raise ValueError("FIXTURE_IMPLEMENTATION must be reference or shipped")
    source = ROOT / relative_path
    if mode == "reference" and relative_path not in CLEAN:
        source = ROOT / "ref" / relative_path
    name = "fixture_" + relative_path.replace("/", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
