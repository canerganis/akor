"""Direct CLI workflow versus the AKOR executor on the O1 repair package (Claude and Astra decision, 2026-10-26).

Both arms deliver the same repaired package for tickets A to D and are judged by the same independent evaluator
(evaluator.evaluate_package: tiers A, I and H, patch, provenance). A sequence is a cold repair (all tickets at
revision 1) followed by a revision (ticket A at revision 2); each arm keeps its own artifacts between the two.

  direct  one claude -p request for the whole package (same model, flags and source information as the AKOR route),
          local A-tier checks, at most MAX_FIXES corrective requests naming only the failing functions; on the
          revision it re-requests only the changed ticket and keeps B, C and D.
  akor    the existing O1 executor unchanged (oz_flow.run_flow, OZ/1g packets, per-job checks, memo); the revision
          is a new flow in the same memo namespace whose source A starts at revision 2.

    python bench/o1/compare.py run --workspace DIR --order direct,akor [--kind fixture|live]
Live runs need O1_LIVE_CONFIRM=1. Results: DIR/compare.json (one row per delivery). The five-minute limit is a
scoring deadline (verified_on_time), not a kill: the executor keeps its own deadlines unchanged, the shared caps bound
spend.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(ROOT), str(HERE), str(HERE / 'evaluator')):
    if p not in sys.path:
        sys.path.insert(0, p)

import evaluator as E  # noqa: E402
import o1 as O  # noqa: E402
import sandbox  # noqa: E402
import sandbox_worker as SW  # noqa: E402
import workflow as W  # noqa: E402
from oz_flow import Flow, flow_dir, flow_usage, run_flow  # noqa: E402

MAX_FIXES = 2
MAX_LAUNCHES = 16
MAX_TOKENS = 150_000
DEADLINE = 300.0
CORE_TAIL = '\nAccepted core function (already in scope; call it, do not redefine it):\n'
SYSTEM = 'You repair Python functions. Reply with one JSON object only, no prose and no Markdown fences.'


# ---- shared ----

def revisions(stage: str) -> dict:
    return {n: (2 if stage == 'revision' and n == 'A' else 1) for n in W.TICKETS}


def tickets(revs: dict) -> dict:
    return {n: W.ticket(n, revs[n]) for n in W.TICKETS}


def a_tier(t: dict, op: str, source, core: str | None) -> str | None:
    """None when the candidate passes the policy and the A tier, else a short reason."""
    if not W.source_ok(source):
        return 'not a source string within the size limit'
    name, params = W.function_of(t, op)
    problems = SW.check_function(source, name, params, W.policy())
    if problems:
        return 'policy: ' + '; '.join(map(str, problems))[:300]
    payload, expected = W.tier_a_payload(t, op, source, core)
    result = W.judge(payload, expected)
    return None if result['pass'] else result['reason']


def evaluate(dest: Path, revs: dict, sources: dict) -> dict:
    accepted = {f'{op}_{n}': sources[n][op] for n in W.TICKETS for op in ('core', 'adapter') if n in sources}
    r = E.evaluate_package(dest, revs, accepted)
    return {'verified': r['verified'], 'errors': r['errors']}


# ---- direct arm ----

def usage_of(envelope) -> dict | None:
    return O._cca().usage_from_envelope(envelope)


def call_claude(prompt: str, kind: str, fixture_answer) -> dict:
    """{'text', 'usage', 'thinking', 'seconds', 'envelope', 'failure'} for one claude -p call (the AKOR route's
    flags, no tools). A timeout, an unreadable envelope or another model is a recorded launch with no usable reply,
    the same as a refused dispatch on the AKOR side."""
    started = time.time()
    model = O.spec()['route']['model']
    envelope, failure, raw = None, None, ''
    if kind == 'fixture':
        text = json.dumps(fixture_answer())
        envelope = {'result': text, 'modelUsage': {model: {
            'inputTokens': len(prompt) // 4, 'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0,
            'outputTokens': len(text) // 4, 'thinkingTokens': 0}}}
    else:
        try:
            proc = subprocess.run([shutil.which('claude'), '-p', '--model', model,
                                   '--system-prompt', SYSTEM, '--tools', '', '--setting-sources', '',
                                   '--strict-mcp-config', '--no-session-persistence', '--output-format', 'json'],
                                  input=prompt, capture_output=True, text=True, encoding='utf-8', timeout=DEADLINE)
            raw = proc.stdout
            envelope = json.loads(raw)
        except subprocess.TimeoutExpired:
            failure = 'timeout'
        except ValueError:
            failure = 'unreadable envelope'
    if envelope is not None and not isinstance(envelope, dict):
        envelope, failure = None, 'unreadable envelope'
    if envelope is not None:
        seen = sorted(envelope.get('modelUsage') or {})
        if seen != [model]:
            failure = 'unexpected model(s): ' + ', '.join(seen)
    return {'text': '' if failure or envelope is None else envelope.get('result', ''),
            'usage': usage_of(envelope) if envelope else None,
            'thinking': O.thinking_tokens(envelope) if envelope else None,
            'seconds': round(time.time() - started, 2), 'envelope': envelope if envelope is not None else raw,
            'failure': failure}


def job_text(t: dict, op: str, core: str | None = None) -> str:
    """The frozen record of one job. An adapter asked without its core in the same request gets the retained core
    source, as the AKOR adapter record carries the accepted core."""
    if op == 'core':
        return t['core_record']
    prefix = t['adapter_record_prefix']
    head = prefix[:prefix.index(CORE_TAIL)] if CORE_TAIL in prefix else prefix
    if core is not None:
        return head + CORE_TAIL + '\n' + core
    return head + (f"\nYour repaired {t['core']['name']} is in scope at run time; call it by name and do not "
                   'include it in this answer.\n')


def request_prompt(ts: dict, names, fixes: dict | None = None, sources: dict | None = None) -> str:
    spec_ = O.spec()
    parts = [spec_['goal'], '', 'Rules for every function: ' + spec_['model_ops']['model.repair_core']['instruction']
             .split('Rules for the code: ', 1)[1], '',
             'Reply with one JSON object: {"<ticket>": {"core": "<python source>", "adapter": "<python source>"}} '
             f"for tickets {', '.join(names)}" + (', only for the functions listed below.' if fixes else '.'), '']
    for n in names:
        for op in ('core', 'adapter'):
            if fixes is None or op in fixes.get(n, {}):
                alone = fixes is not None and op == 'adapter' and 'core' not in fixes.get(n, {})
                parts += [f'=== ticket {n}, {op} ===',
                          job_text(ts[n], op, (sources or {}).get(n, {}).get('core') if alone else None)]
                if fixes:
                    prev, reason = fixes[n][op]
                    parts += ['Your previous answer failed the hidden checks (' + reason + '):', prev, '']
    return '\n'.join(parts)


def parse_reply(text: str) -> dict:
    text = text.strip()
    m = re.fullmatch(r'```(?:json)?\s*(.*?)\s*```', text, re.S)
    try:
        data = json.loads(m.group(1) if m else text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def fixture_sources(ts: dict, names) -> dict:
    import fixture_adapter as FA
    out = {}
    for n in names:
        t = ts[n]
        rel = f"A_rev{t['revision']}.py" if n == 'A' else f'{n}.py'
        text = (HERE / 'fixture' / rel).read_text(encoding='utf-8')
        out[n] = {op: FA.function_source(text, t[op]['name']) for op in ('core', 'adapter')}
    return out


def build_package(dest: Path, ts: dict, sources: dict) -> None:
    """The O1 delivery layout from the direct arm's sources, rendered by the workflow's own host functions."""
    snap = {'tickets': {n: {'source_revision': ts[n]['revision'], 'sha256': W.sha(W.source_bytes(n, ts[n]['revision'])),
                            'ticket': ts[n]} for n in W.TICKETS}}
    package = W.op_assemble({'snapshot': snap, 'cores': [sources[n]['core'] for n in W.TICKETS],
                             'adapters': [sources[n]['adapter'] for n in W.TICKETS]}, None)
    integration = {'tier': 'I', 'modules': {}}
    for n in W.TICKETS:
        m = package['modules'][n]
        payload, expected = W.i_payload(ts[n], m['text'])
        ok = W.judge(payload, expected)['pass']
        integration['modules'][n] = {'sha256': m['sha256'], 'ticket_revision': ts[n]['revision'],
                                     'rows': len(expected), 'passed': len(expected) if ok else 0, 'seeds': [0, 1]}
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    files = {m['file']: m['text'] for m in package['modules'].values()}
    files['repair.patch'] = W.render_patch(snap, package)
    doc = W.provenance_doc(snap, package, integration)
    files['verification.md'] = W.report_text(doc)
    files['provenance.json'] = json.dumps(doc, indent=1, sort_keys=True) + '\n'
    for name, text in files.items():
        (dest / name).write_bytes(text.encode('utf-8'))
    (dest / 'manifest.json').write_text(json.dumps({k: W.sha(v) for k, v in sorted(files.items())}, indent=1),
                                        encoding='utf-8')


def direct_delivery(ws: Path, stage: str, kind: str, state: dict, ledger) -> dict:
    revs = revisions(stage)
    ts = tickets(revs)
    good = state.get('good', set())
    # Changed tickets, plus any ticket the previous delivery left unresolved (AKOR re-runs uncached nodes too).
    names = [n for n in W.TICKETS if revs[n] != state['revs'][n] or n not in good]
    sources = {n: dict(v) for n, v in state.get('sources', {}).items() if n not in names}
    calls, started = [], time.time()
    fixes, stopped = None, None
    for attempt in range(1 + MAX_FIXES):
        stopped = ledger.refusal()
        if stopped:
            break
        want = names if fixes is None else sorted(fixes)
        call = call_claude(request_prompt(ts, want, fixes, sources), kind, lambda: fixture_sources(ts, want))
        ledger.add(call['usage'])
        (ws / 'direct-calls').mkdir(parents=True, exist_ok=True)
        (ws / 'direct-calls' / f'{stage}-{attempt}.json').write_text(json.dumps(call['envelope']), encoding='utf-8')
        calls.append({k: call[k] for k in ('usage', 'thinking', 'seconds', 'failure')})
        reply = parse_reply(call['text'])
        for n in want:
            for op in ('core', 'adapter'):
                if (fixes is None or op in fixes[n]) and isinstance(reply.get(n), dict) and op in reply[n]:
                    sources.setdefault(n, {})[op] = reply[n][op]
        fixes = {}
        for n in names:
            core = sources.get(n, {}).get('core')
            for op in ('core', 'adapter'):
                src = sources.get(n, {}).get(op)
                reason = 'missing from the reply' if src is None else a_tier(ts[n], op, src, core)
                if reason:
                    fixes.setdefault(n, {})[op] = (src if isinstance(src, str) else '', reason)
        if not fixes:
            break
    dest = ws / 'direct-delivery' / stage
    delivered = fixes == {}
    if delivered:
        build_package(dest, ts, sources)
    elapsed = round(time.time() - started, 2)
    state.update(revs=revs, sources=sources, good=set(W.TICKETS) if delivered else
                 {n for n in W.TICKETS if n not in (fixes or {}) and n in sources})
    if delivered:
        verdict = evaluate(dest, revs, sources)
    else:
        verdict = {'verified': False,
                   'errors': [stopped or f'unresolved after {MAX_FIXES} fixes: {sorted(fixes or {})}']}
    return row('direct', stage, calls, elapsed, verdict)


# ---- AKOR arm ----

def akor_calls(ws: Path, request_id: str) -> list:
    """One row per dispatch, usage normalized from the retained CLI envelope like the direct arm (cache counters
    kept; unknown usage stays None)."""
    out = []
    for d in O.trace_of(ws, request_id):
        done = ws / d['run_dir'] / 'captures' / f"{d['receipt']}.done"
        envelope = O.envelope_of(json.loads(done.read_text(encoding='utf-8'))) if done.exists() else None
        seen = sorted((envelope or {}).get('modelUsage') or {})
        failure = ('no retained envelope' if not envelope else
                   None if seen == [O.spec()['route']['model']] else 'unexpected model(s): ' + ', '.join(seen))
        out.append({'usage': usage_of(envelope) if envelope else None,
                    'thinking': O.thinking_tokens(envelope) if envelope else None, 'seconds': None,
                    'failure': failure,
                    'members': [m['id'] for m in d['members']]})
    return out


def akor_delivery(ws: Path, stage: str, kind: str, prefix: str, ledger) -> dict:
    revs = revisions(stage)
    request_id = f'{prefix}-{stage}'
    if stage == 'revision':
        f = Flow(flow_dir(ws, request_id) / 'flow.sqlite')
        try:
            f.import_source('A', W.source_bytes('A', 2))
        finally:
            f.close()
    # The flow's own admission enforces what is left of the global caps: it counts every flow in this workspace.
    flows = sorted(x.name for x in (ws / 'flows').glob('*') if (x / 'flow.sqlite').exists())
    here = [flow_usage(ws, x) for x in flows if x != request_id]
    budget = dict(O.allocation(),
                  max_launches=sum(u['launches'] for u in here) + ledger.left_launches(),
                  max_tokens=sum(u['tokens_known'] + u['calls_without_usage'] * O.allocation()['reserve_per_launch']
                                 for u in here) + ledger.left_tokens())
    budget.pop('max_launches_per_flow', None)
    quota = O.quota_store(ws, kind)
    started = time.time()
    try:
        result = run_flow(O.flow_request(prefix, stage, request_id=request_id),
                          O.settings(ws, kind, f'{kind}-{prefix}-akor', quota=quota, budget=budget))
    finally:
        quota.close()
    elapsed = round(time.time() - started, 2)
    usage = flow_usage(ws, request_id)
    calls = akor_calls(ws, request_id)
    for c in calls:
        ledger.add(c['usage'])
    f = Flow(flow_dir(ws, request_id) / 'flow.sqlite')
    try:
        latest = f.latest()
    finally:
        f.close()
    sources = {}
    for n in W.TICKETS:
        for op in ('core', 'adapter'):
            a = latest.get(f'{op}_{n}')
            if a is not None:
                sources.setdefault(n, {})[op] = json.loads(a['value'])
    target = result['targets'][O.TARGET]
    if target['status'] == 'delivered':
        verdict = evaluate(ws / target['destination'], revs, sources)
    else:
        verdict = {'verified': False, 'errors': [f"not delivered: {result.get('blocker')}"]}
    out = row('akor', stage, calls, elapsed, verdict)
    out['launches_flow_usage'] = usage['launches']
    out['tokens_flow_usage'] = usage['tokens_known']
    return out


# ---- report ----

class Ledger:
    """Launches and tokens across every workspace of the comparison (one JSON file), checked before each launch."""

    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
            'launches': 0, 'tokens': 0, 'calls_without_usage': 0}

    def add(self, usage):
        self.data['launches'] += 1
        if usage:
            self.data['tokens'] += usage['input_tokens'] + usage['output_tokens']
        else:
            self.data['calls_without_usage'] += 1
            self.data['tokens'] += O.allocation().get('reserve_per_launch', 5000)
        self.path.write_text(json.dumps(self.data), encoding='utf-8')

    def left_launches(self) -> int:
        return max(0, MAX_LAUNCHES - self.data['launches'])

    def left_tokens(self) -> int:
        return max(0, MAX_TOKENS - self.data['tokens'])

    def refusal(self):
        # The same rule as the AKOR flow admission: a launch needs one full reserve of tokens left.
        if not self.left_launches() or self.left_tokens() < O.allocation()['reserve_per_launch']:
            return f'engineering cap reached: {self.data}'
        return None


def row(arm: str, stage: str, calls: list, elapsed: float, verdict: dict) -> dict:
    known = [c['usage'] for c in calls if c['usage']]
    thinking_unknown = sum(1 for c in calls if c['thinking'] is None)
    tin = sum(u['input_tokens'] for u in known)
    tout = sum(u['output_tokens'] for u in known)
    return {'arm': arm, 'stage': stage, 'launches': len(calls), 'input_tokens': tin, 'output_tokens': tout,
            'tokens': tin + tout, 'cached_input_tokens': sum(u.get('cached_input_tokens') or 0 for u in known),
            'thinking_tokens': sum(c['thinking'] or 0 for c in calls), 'thinking_unknown': thinking_unknown,
            'calls_without_usage': len(calls) - len(known), 'failed_calls': sum(1 for c in calls if c['failure']),
            'elapsed_seconds': elapsed, 'on_time': elapsed <= DEADLINE, 'verified': verdict['verified'],
            'verified_on_time': verdict['verified'] and elapsed <= DEADLINE,
            'errors': verdict['errors'], 'calls': calls}


def run(ws: Path, order: list, kind: str, prefix: str, ledger_path: Path) -> dict:
    ws = ws.resolve()
    ws.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(ledger_path)
    out_path = ws / 'compare.json'
    report = json.loads(out_path.read_text(encoding='utf-8')) if out_path.exists() else {'kind': kind, 'rows': []}
    for arm in order:
        arm_ws = ws / arm
        arm_ws.mkdir(exist_ok=True)
        if arm == 'akor':
            O.prepare(arm_ws, kind)
        state = {'revs': revisions('cold')}
        for stage in ('cold', 'revision'):
            if ledger.refusal():
                report['stopped'] = ledger.refusal()
                break
            r = (direct_delivery(arm_ws, stage, kind, state, ledger) if arm == 'direct'
                 else akor_delivery(arm_ws, stage, kind, prefix, ledger))
            r['order'] = ','.join(order)
            report['rows'].append(r)
            out_path.write_text(json.dumps(report, indent=1) + '\n', encoding='utf-8')
            print(arm, stage, 'verified' if r['verified'] else 'FAILED', '' if r['on_time'] else 'LATE', r['launches'], 'launches', r['tokens'],
                  'tokens', r['elapsed_seconds'], 's', flush=True)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = p.add_subparsers(dest='command', required=True)
    r = sub.add_parser('run')
    r.add_argument('--workspace', required=True, type=Path)
    r.add_argument('--order', default='direct,akor')
    r.add_argument('--kind', choices=('fixture', 'live'), default='fixture')
    r.add_argument('--prefix', default='cmp')
    r.add_argument('--ledger', type=Path, help='shared cap ledger (default: next to the workspace)')
    args = p.parse_args(argv)
    if args.kind == 'live' and not os.environ.get(O.LIVE_ENV):
        print(f'live runs paid calls: set {O.LIVE_ENV}=1 to proceed', file=sys.stderr)
        return 2
    order = args.order.split(',')
    if sorted(order) != ['akor', 'direct']:
        p.error('--order must name direct and akor once each')
    ledger = args.ledger or args.workspace.resolve().parent / 'compare-ledger.json'
    report = run(args.workspace, order, args.kind, args.prefix, ledger)
    complete = len(report['rows']) == 4 and not report.get('stopped')
    return 0 if complete and all(x['verified_on_time'] for x in report['rows']) else 3


if __name__ == '__main__':
    sys.exit(main())
