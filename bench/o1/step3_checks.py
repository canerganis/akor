"""Zero-call checks for step 3 (Haiku 5.5 on repair-handoff-20/v1): control match and experimental labels.

control_match answers, item by item, whether the archived Sonnet O1 control (bench/o1/live1, run at freeze 32333561)
still describes what HEAD would send and count under the derived route, apart from the model. The prompt items run
the real executor on the fixture transport with step3_replay_adapter.py, which answers every job with the control's
own archived accepted function, so even the adapter packets (which carry the accepted cores) are rendered from the
control's bytes and compared with the archived ledger digests. The other items compare pinned digests and function
sources. label_check dispatches claude-haiku-5-5 at sizes 4 and 1 through the real executor under the derived route
(fixture transport) and reads the labels. Nothing here calls a model; `claude --version` is the only subprocess.
"""
from __future__ import annotations

import ast
import hashlib
import itertools
import json
from pathlib import Path
import re
import subprocess
import sys
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(ROOT), str(HERE), str(HERE / 'evaluator')):
    if p not in sys.path:
        sys.path.insert(0, p)

import o1 as O  # noqa: E402
import o1_dry as D  # noqa: E402
import step3_haiku as S  # noqa: E402
from oz_batch import SYSTEM  # noqa: E402
from oz_reply import LANGUAGE, PROTOCOL  # noqa: E402

W = O.W
ARCHIVE = HERE / 'live1'
CONTROL_PREFIX = 'live1'
SCENARIOS = ('clean', 'interrupt', 'stale')
# 02-opus-changes.md, change 2: facts read from the control's ledgers.
EXPECTED = {'system': 'd941a86d', 'core4': 'ed27d59c', 'stale_core_A': '3fb652d8',
            'adapter': ('1c08ef8e', '1c628a20', '1ca7cc03', '4157a4b8')}
CONTROL_CLI = '2.1.306'
# The four executor files changed between the control freeze (079a2f9) and the base freeze (088815db). Their change
# is reviewed in plan-frozen.md; any other changed pinned file is an unreviewed difference.
REVIEWED_CHANGES = ('bench/step4/g3b.py', 'oz_do.py', 'oz_flow.py', 'oz_runtime.py')
# Accounting scope: files whose pinned digest must be the control's, and functions (sha256 of the normalized source
# segment, computed from `git show 079a2f9:<file>`) that define usage, launches and totals.
SCOPE_FILES = ('examples/claude_cli_adapter.py', 'bench/o1/o1.py', 'bench/o1/gate.py', 'oz_runner.py', 'oz_worker.py',
               'oz_accept.py', 'oz_memo.py', 'oz_quota.py')
CONTROL_FUNCTIONS = {
    'oz_flow.py:flow_usage': '99d8530630c8829b2b0b6d069fff35b825b1fcf82ed5046964f8a17c98e7a6c0',
    'oz_flow.py:stage_launches': '0dc34bb4c53b9aa588ee46dd193430ce60f590f1ad66e073c29c3eb0bae39a08',
    'oz_do.py:_accounting': 'fa47c1940603450abb919b539bc0da963e61cd9790d040662d073f59637fd504',
    'bench/o1/o1.py:totals_of': '6f25d5985317cf9e8da7dd5bb5c7a84d61c7338c3532145a02604151fdc9640d',
    'bench/o1/o1.py:calls_of': '78b5849efc9dc13a98dbd3604523026188e8e48eb1440c0f598b178ba89d5767',
    'bench/o1/o1.py:thinking_tokens': 'd77e54bff997d8e270d365a2b466c36729e167f008f05b58974fcce99689d704',
    'bench/o1/o1.py:ledger_audit': 'a3b1b97cd78246f99dc7789c43e58cac7a2e17ede8a2b464f2e4028648bb4b20',
    'examples/claude_cli_adapter.py:usage_from_envelope':
        '5e705dae23c2fc24d957d5b3067e46642defa758b9adbb2dab320073e083dd1f',
    'examples/claude_cli_adapter.py:reduce': '3890224b5780db4dc3a12e92fef359a778a88eb285fc2e3e538c6ab9e5dc1e85'}
HEADER = re.compile(r'O1 repair ticket\nticket: ([A-Z])\nrevision: ([0-9]+)\nop: repair_(core|adapter)@1\n')


# ---- the archive ----

def _ledger_names(scenario: str) -> list:
    return sorted(p.name[len('calls-'):-len('.jsonl')]
                  for p in ARCHIVE.glob(f'calls-{CONTROL_PREFIX}-{scenario}-repair_*-*.jsonl'))


def archived_sequences() -> dict:
    """Per scenario, the control's calls in start order: op, member ids, system and prompt digests, run name."""
    out = {}
    for scenario in SCENARIOS:
        rows = []
        for name in _ledger_names(scenario):
            for line in (ARCHIVE / f'calls-{name}.jsonl').read_text(encoding='utf-8').splitlines():
                r = json.loads(line)
                if r['event'] == 'call_start':
                    rows.append({'op': name.split('repair_')[1].split('-')[0], 'ids': [j['inbox_job_id'] for j in r['job_map']],
                                 'system': r['system_sha256'], 'prompt': r['prompt_sha256'],
                                 'submitted': r['submitted_sha256'], 'prompt_bytes': r['prompt_bytes'],
                                 'run': name, 'started_at': r['started_at']})
        out[scenario] = sorted(rows, key=lambda r: r['started_at'])
    return out


def replay_table(scenario: str) -> dict:
    """{'core_A@1': source, ...}: the control's accepted function for each job and ticket revision of one scenario,
    taken from the rows its runs stored for their own model answers (memo rows repeat earlier answers)."""
    runs = set(_ledger_names(scenario))
    table = {}
    for line in (ARCHIVE / 'candidates.jsonl').read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        if row['run'] not in runs or row['status'] != 'accepted' or str(row['receipt']).startswith('memo:'):
            continue
        record = json.loads(json.loads(row['inputs'])[0]['refs'][0])
        key = f"{row['job']}@{HEADER.match(record).group(2)}"
        value = json.loads(row['value'])
        if value != row['stored'] or key in table:
            raise ValueError(f'archived candidate rows disagree or repeat for {key}')
        table[key] = value
    return table


# ---- replay through the real executor ----

def _replay_adapter_file(ws: Path, kind: str) -> Path:
    path = ws / f'adapter-{kind}.json'
    path.write_text(json.dumps({'argv': [sys.executable, str(HERE / 'step3_replay_adapter.py')],
                                'protocols': [PROTOCOL], 'languages': [LANGUAGE]}), encoding='utf-8')
    return path


def replay_calls(base: Path, scenario: str) -> tuple:
    """(status, calls) of one scenario run at HEAD with the replay adapter: every call_start in start order."""
    with D.fixture_env(), patch.object(O, 'adapter_file', _replay_adapter_file):
        ws = D.fresh(Path(base), f'ctl-{scenario}')
        (ws / 'fixture' / 'replay.json').write_text(json.dumps(replay_table(scenario)), encoding='utf-8')
        result = O.run_scenario_flow(ws, 'fixture', CONTROL_PREFIX, scenario)
    rows = []
    for rel in O.stage_runs(ws, O.rid(CONTROL_PREFIX, scenario)):
        ledger = ws / rel / 'calls.jsonl'
        for line in (ledger.read_text(encoding='utf-8').splitlines() if ledger.exists() else ()):
            r = json.loads(line)
            if r['event'] == 'call_start':
                name = Path(rel).name
                rows.append({'op': name.split('repair_')[1].split('-')[0], 'ids': [j['inbox_job_id'] for j in r['job_map']],
                             'system': r['system_sha256'], 'prompt': r['prompt_sha256'],
                             'submitted': r['submitted_sha256'], 'prompt_bytes': r['prompt_bytes'], 'run': name,
                             'started_at': r['started_at']})
    return result['status'], sorted(rows, key=lambda r: r['started_at'])


# ---- digests and sources ----

def _function_digest(path: str, name: str) -> str:
    text = (ROOT / path).read_text(encoding='utf-8').replace('\r\n', '\n')
    node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == name)
    return hashlib.sha256(ast.get_source_segment(text, node).encode('utf-8')).hexdigest()


def _row(id_: str, item: str, expected, actual, ok: bool, **extra) -> dict:
    return dict({'id': id_, 'item': item, 'expected': expected, 'actual': actual,
                 'verdict': 'MATCH' if ok else 'MISMATCH'}, **extra)


def _prompt_item(id_: str, item: str, pairs: list) -> dict:
    """pairs: [(label, expected call row or None, actual call row or None)]; every pair must have equal digests."""
    detail = []
    for label, want, got in pairs:
        detail.append({'scenario': label, 'expected': want['prompt'] if want else None,
                       'actual': got['prompt'] if got else None, 'system': got['system'] if got else None,
                       'submitted_equal': bool(want and got and want['submitted'] == got['submitted']),
                       'bytes_equal': bool(want and got and want['prompt_bytes'] == got['prompt_bytes']),
                       'run': got['run'] if got else None})
    ok = bool(detail) and all(d['expected'] and d['expected'] == d['actual'] and d['submitted_equal']
                              and d['bytes_equal'] for d in detail)
    return {'id': id_, 'item': item, 'detail': detail, 'verdict': 'MATCH' if ok else
            ('UNVERIFIED' if not detail else 'MISMATCH'),
            'expected': [d['expected'] for d in detail], 'actual': [d['actual'] for d in detail]}


def control_match(base: Path, scenarios=SCENARIOS, control_path: Path = S.CONTROL_FILE) -> dict:
    """The control-match items of 02-opus-changes.md change 2, each MATCH, MISMATCH or UNVERIFIED."""
    control = json.loads(Path(control_path).read_text(encoding='utf-8'))
    archive = archived_sequences()
    runs = {}
    for scenario in scenarios:
        status, rows = replay_calls(base, scenario)
        runs[scenario] = {'status': status, 'calls': rows}

    def calls(scenario, op, size):
        want = [r for r in archive[scenario] if r['op'] == op and len(r['ids']) == size]
        got = [r for r in runs.get(scenario, {}).get('calls', []) if r['op'] == op and len(r['ids']) == size]
        return [(f'{scenario}/{op}{size}#{i}', w, g) for i, (w, g) in enumerate(itertools.zip_longest(want, got))]

    items = []
    core4 = [x for s in scenarios for x in calls(s, 'core', 4)]
    items.append(_prompt_item('core_size4_prompt', 'core size-4 packet prompt ed27d59c (clean, interrupt, stale)', core4))
    stale1 = calls('stale', 'core', 1) if 'stale' in scenarios else []
    items.append(_prompt_item('stale_core_A_singleton', 'stale core A singleton prompt 3fb652d8', stale1))
    adapter = [x for s in scenarios for size in (4, 1) for x in calls(s, 'adapter', size)]
    items.append(_prompt_item('adapter_prompts', 'adapter prompts 1c08ef8e 1c628a20 1ca7cc03 4157a4b8, rendered from '
                                                 'the archived Sonnet accepted cores', adapter))
    # a prompt item also demands the expected short digests the preregistration names
    for row in items:
        short = {'core_size4_prompt': (EXPECTED['core4'],), 'stale_core_A_singleton': (EXPECTED['stale_core_A'],),
                 'adapter_prompts': EXPECTED['adapter']}[row['id']]
        if row['verdict'] == 'MATCH' and not all(d['expected'][:8] in short for d in row['detail']):
            row['verdict'] = 'MISMATCH'
    items.append(_run_ids(scenarios, archive, runs))

    head_code = {c: O.ndigest(ROOT / c) for c in list(O.CODE)}
    cc = control['code']
    items.append(_row('adapter_script', 'adapter script digest (examples/claude_cli_adapter.py)',
                      cc['examples/claude_cli_adapter.py'], head_code['examples/claude_cli_adapter.py'],
                      cc['examples/claude_cli_adapter.py'] == head_code['examples/claude_cli_adapter.py']))
    wf = 'bench/o1/repair-handoff-20-v1/workflow.json'
    same_wf = control['frozen'][wf] == O.ndigest(ROOT / wf)
    base_route = S.base_spec()['route']
    derived = S.derive(S.base_spec(), S.overlay())
    route_equal = {k: v for k, v in derived['route'].items() if k not in ('model', 'alias_map')} == {
        k: v for k, v in base_route.items() if k not in ('model', 'alias_map')}
    items.append(_row('effort', 'effort (default) and the remaining route fields, model aside',
                      {'workflow_json': control['frozen'][wf], 'effort': 'default'},
                      {'workflow_json': O.ndigest(ROOT / wf), 'effort': derived['route']['effort']},
                      same_wf and route_equal and derived['route']['effort'] == 'default'))
    system_sha = hashlib.sha256(SYSTEM.encode('utf-8')).hexdigest()
    archived_systems = {r['system'] for rows in archive.values() for r in rows}
    replay_systems = {r['system'] for s in runs.values() for r in s['calls']}
    items.append(_row('wire_H_system', 'wire system text H digest d941a86d (archived ledgers, replay ledgers, oz_batch.SYSTEM)',
                      sorted(archived_systems), sorted(replay_systems | {system_sha}),
                      archived_systems == {system_sha} and replay_systems <= {system_sha}
                      and system_sha.startswith(EXPECTED['system'])))
    parser = (f"{derived['route']['parser']}@sha256:{cc['oz_reply.py'][:16]};wire-H-sha256:"
              f"{next(iter(archived_systems))[:16]}")
    with S.applied():
        fields, model = O.route('live')
    items.append(_row('parser_and_wire', 'parser (oz_reply.py digest, parser name) and wire fields of the route identity',
                      {'oz_reply.py': cc['oz_reply.py'], 'oz_batch.py': cc['oz_batch.py'], 'parser': parser},
                      {'oz_reply.py': head_code['oz_reply.py'], 'oz_batch.py': head_code['oz_batch.py'],
                       'parser': fields['parser']},
                      cc['oz_reply.py'] == head_code['oz_reply.py'] and cc['oz_batch.py'] == head_code['oz_batch.py']
                      and parser == fields['parser']))
    control_fields = {'effort': 'default', 'cli_version': CONTROL_CLI,
                      'adapter': f"argv:{json.dumps(['python', derived['route']['adapter_script']], separators=(',', ':'))};"
                                 f"sha256:{cc['examples/claude_cli_adapter.py']}",
                      'parser': parser}
    items.append(_row('route_identity', 'route identity fields (effort, cli_version, adapter, parser) equal the control\'s',
                      control_fields, fields, control_fields == fields and model == 'claude-haiku-5-5',
                      model=model))
    found = O.cli_version()
    items.append(_row('cli_version', '`claude --version` is 2.1.306', CONTROL_CLI, found,
                      found == CONTROL_CLI == derived['route']['cli_version']))
    functions = {key: _function_digest(*key.split(':')) for key in CONTROL_FUNCTIONS}
    changed_scope = sorted(f for f in SCOPE_FILES if cc[f] != head_code[f])
    items.append(_row('accounting_scope', 'accounting scope: modelUsage whole call, the totals_of definition, launches, '
                                          'ledger and the files that carry them',
                      {'functions': CONTROL_FUNCTIONS, 'changed_scope_files': []},
                      {'functions': functions, 'changed_scope_files': changed_scope},
                      functions == CONTROL_FUNCTIONS and not changed_scope))
    changed = sorted(f for f in cc if cc[f] != head_code.get(f))
    unreviewed_ops = sorted(name for name, op in W.registry().items()
                            if hasattr(op, 'ref_order') and not (op.single and not op.values))
    items.append(_row('executor_paths', 'executor files changed since the control freeze are exactly the four reviewed, '
                                        'and no O1 model operation uses the opt-in ordered or value inputs',
                      {'changed': list(REVIEWED_CHANGES), 'ordered_or_value_ops': []},
                      {'changed': changed, 'ordered_or_value_ops': unreviewed_ops},
                      tuple(changed) == REVIEWED_CHANGES and not unreviewed_ops))
    return {'items': items, 'all_match': all(r['verdict'] == 'MATCH' for r in items), 'scenarios': list(scenarios),
            'control_digest': control['digest'], 'base_digest': S.base_freeze()['digest'],
            'replay_status': {s: r['status'] for s, r in runs.items()}, 'head': _head()}


def _run_ids(scenarios, archive, runs) -> dict:
    detail = []
    for s in scenarios:
        want = [r['run'] for r in archive[s]]
        got = [r['run'] for r in runs[s]['calls']]
        detail.append({'scenario': s, 'expected': want, 'actual': got})
    ok = bool(detail) and all(d['expected'] == d['actual'] and d['expected'] for d in detail)
    return {'id': 'run_ids', 'item': 'stage run ids (hash of operation identity, nodes, texts, generations) equal the '
                                     'archived ledger names', 'detail': detail, 'verdict': 'MATCH' if ok else
            ('UNVERIFIED' if not detail else 'MISMATCH'), 'expected': [d['expected'] for d in detail],
            'actual': [d['actual'] for d in detail]}


def _head() -> str | None:
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, cwd=str(ROOT),
                              timeout=30).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


# ---- labels ----

def label_check(base: Path) -> dict:
    """Dispatches with model claude-haiku-5-5 at sizes 4 and 1 under the derived live route, through the real executor on
    the fixture transport (the fixture envelope reports the Haiku id, so the response check passes): labels must be
    experimental. The same flows with experimental_sizes naming neither size must read qualified_cell (the control that
    shows the check can fail)."""
    base = Path(base)
    with S.applied():
        fields, model = O.route('live')
        with D.fixture_env(), patch.object(O, 'route', lambda kind: (fields, model)):
            _, outs = D.case_run(base, 'label-haiku', {'model': model}, ['clean', 'stale'])
            _, control = D.case_run(base, 'label-control', {'model': model}, ['clean', 'stale'],
                                    experimental_sizes=(99,))

    def pairs(rows):
        return [[size, label] for row in rows.values() for size, label in zip(row['packets'], row['labels'])]
    gate = all(row['gate']['checks']['every_dispatch_experimental'] for row in outs.values())
    experimental, negative = pairs(outs), pairs(control)
    ok = (model == 'claude-haiku-5-5' and {s for s, _ in experimental} == {1, 4}
          and all(label == 'experimental' for _, label in experimental)
          and {s for s, _ in negative} == {1, 4} and all(label == 'qualified_cell' for _, label in negative) and gate)
    return {'pass': ok, 'model': model, 'experimental': experimental, 'negative_control': negative,
            'gate_every_dispatch_experimental': gate, 'packets': {s: row['packets'] for s, row in outs.items()},
            'pass_g3c_under_haiku_fixture': {s: row[O.GT.LABEL] for s, row in outs.items()},
            'cells': 'oz_do.CELLS marks claude-haiku-5-5 sizes 1 and 4 as pass (qualified_cell) on the materials class'}
