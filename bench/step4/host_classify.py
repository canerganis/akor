"""inspection-handoff-20/v3 runtime: the classify nodes are host operations (host.classify@1).

Decision: docs/design/boundary-adoption-2026-10-23/decision-host-classify.md (rounds 05 and 06). After the adoption
qualification failed at call 9 on an inclusive upper-limit equality, step 4 stops sending classification to a model:
the host computes the label exactly from node 11's checked interval and the structured goal limits, in Decimal.

This module adds nothing to the frozen v1 and v2 harness files. It loads separate copies of workflow.py, g3b.py,
evaluator.py and step4.py for the v3 pack (bench/step4/packs.py), registers the one new host operation in the v3 copy
of workflow.py only, replaces that copy's graph rule, and binds the v3 copy of step4.py to the three copies. The v1 and
v2 modules, their packs and their freezes are untouched.

    host.classify@1  inputs: interval (node 11's /bounds/X: [low, high] two-decimal mm strings, or "unknown") and
                     limits (the structured goal limits, exactly workflow.json's {lower, upper, unit: mm,
                     inclusive: true}); output: "inside" exactly when lower <= low and high <= upper (Decimal),
                     "outside" otherwise, "unknown" when the interval is unknown. Anything malformed (including
                     limits that disagree with the contract, whether or not the interval is unknown) is refused with
                     a HostError and blocks the node; nothing is repaired or guessed.

Standard library only.
"""
from __future__ import annotations

from decimal import Decimal
from importlib import util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import packs  # noqa: E402
from oz_flow import HostError, HostOp  # noqa: E402

V3 = 'inspection-handoff-20-v3'
V2 = packs.V2
LIMIT_KEYS = frozenset({'lower', 'upper', 'unit', 'inclusive'})
INTERVAL_STATUSES = ('inside', 'outside', 'unknown')


def _evaluator():
    """The v3 copy of evaluator.py. Its WORKFLOW table has no entry for a new pack at import (it is a frozen file), so
    the copy is executed under the v2 key and then bound to the v3 pack directory and workflow id; the v2 copy that
    adopt.py uses is never touched. Every function of the copy reads FROZEN and WORKFLOW at call time."""
    key = 'evaluator__' + V3.replace('-', '_')
    if key in sys.modules:
        return sys.modules[key]
    found = util.spec_from_file_location(key, HERE / 'evaluator.py')
    module = util.module_from_spec(found)
    module.PACK = V2
    sys.modules[key] = module
    try:
        found.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(key, None)
        raise
    module.PACK = V3
    module.FROZEN = HERE / V3
    module.WORKFLOW = 'inspection-handoff-20/v3'
    return module


W = packs.load('workflow', V3)
G = packs.load('g3b', V3)
E = _evaluator()
S = packs.load('step4', V3)
S.W, S.G, S.E = W, G, E


# ---- the operation ----

def parse_limits(limits) -> tuple:
    """(lower, upper) as Decimal from the structured goal limits, or HostError. The contract is exactly workflow.json's
    {lower, upper, unit: mm, inclusive: true} with two-decimal strings and lower below upper."""
    if not isinstance(limits, dict) or set(limits) != LIMIT_KEYS:
        raise HostError('limits must be exactly {lower, upper, unit, inclusive}')
    if limits['unit'] != 'mm' or limits['inclusive'] is not True:
        raise HostError('limits must be in mm and inclusive')
    if not all(isinstance(limits[k], str) and W.LIMIT_RE.fullmatch(limits[k]) for k in ('lower', 'upper')):
        raise HostError('limits must be two-decimal numbers as strings')
    lower, upper = Decimal(limits['lower']), Decimal(limits['upper'])
    if lower >= upper:
        raise HostError('lower limit must be below the upper limit')
    return lower, upper


def parse_interval(interval):
    """'unknown', or (low, high) as Decimal from two two-decimal mm strings with low <= high, else HostError."""
    if interval == 'unknown':
        return 'unknown'
    if not isinstance(interval, list) or len(interval) != 2 or any(not isinstance(x, str) for x in interval):
        raise HostError('interval must be [low, high] or unknown')
    low, high = W._mm(interval[0]), W._mm(interval[1])
    if low > high:
        raise HostError('interval is inverted')
    return low, high


def classify_interval(interval, limits) -> str:
    """The label of a checked interval against the goal limits: inclusive at both limits, exact in Decimal."""
    lower, upper = parse_limits(limits)
    parsed = parse_interval(interval)
    if parsed == 'unknown':
        return 'unknown'
    low, high = parsed
    return 'inside' if lower <= low and high <= upper else 'outside'


def op_classify(inputs, ctx):
    return classify_interval(inputs['interval'], inputs['limits'])


CLASSIFY = HostOp('host.classify', 1, frozenset({'interval', 'limits'}), op_classify)
W.HOST_OPS = tuple(W.HOST_OPS) + (CLASSIFY,)
W.op_classify = op_classify


# ---- the graph rule ----

def graph_problems(graph_value=None, spec=None) -> list:
    """Where the v3 graph and spec depart from the decision (empty when they hold): no model classify operation or
    node, and every classify_X (X = A..D) is host.classify binding interval = node 11's /bounds/X and limits = the
    structured limits of workflow.json as a literal, with no extra ordering edge, and handoff_rows consuming the four
    classifications in record order."""
    spec, graph_value = spec or W.load('workflow.json'), graph_value or W.graph()
    problems = []
    if 'model.classify' in spec['model_ops']:
        problems.append('v3 has no model.classify operation')
    if 'host.classify@1' not in spec['host_ops']:
        problems.append('host.classify@1 is not a listed host operation')
    nodes = graph_value['nodes']
    if len(nodes) != 20:
        problems.append(f'the graph keeps 20 nodes, not {len(nodes)}')
    names = ('A', 'B', 'C', 'D')
    by_id = {n['id']: n for n in nodes}
    for n in nodes:
        if n['op'] == 'model.classify':
            problems.append(f"{n['id']}: model.classify is not part of v3")
    for name in names:
        node = by_id.get(f'classify_{name}')
        if node is None:
            problems.append(f'classify_{name} is missing')
            continue
        want = {'interval': {'node': 'checked_intervals', 'path': f'/bounds/{name}'},
                'limits': {'lit': spec['limits']}}
        if node['op'] != 'host.classify' or node['in'] != want or node['after'] != []:
            problems.append(f'classify_{name}: must be host.classify binding the interval of its own record from '
                            f'checked_intervals and the structured limits')
    rows = by_id.get('handoff_rows')
    want_status = {'list': [{'node': f'classify_{n}'} for n in names]}
    if rows is None or rows['in'].get('status') != want_status:
        problems.append('handoff_rows must consume classify_A..D in record order')
    return problems


W.graph_problems = graph_problems
