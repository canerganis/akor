"""Gate G0 of the caller-cost plan (docs/design/caller-cost-2026-10-23): offline checks of bench/live/pilot_k2.py,
the bench `oz do` wrapper (k2_wrap.py) and the recording adapter (k2_adapter.py). No model is called: the caller and
the worker are local fake programs."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bench' / 'live'))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pilot_k2 as K
import k2_wrap as W
from oz_workspace import initialize

DATA = K.DATA

# Shared by the fake worker and the fake caller: computes the materials answers from a reference text.
ANSWER = r'''
import json, re
from decimal import Decimal
def fields(text):
    line = re.search(r'length=[^\n]*', text).group(0)
    return dict(p.split('=', 1) for p in line.split('; '))
def answer(op, text):
    kv = fields(text)
    if 'array of strings containing' in op:
        return [kv[f] for f in ('length', 'uncertainty', 'n', 'method', 'basis', 'physical_validation')]
    if 'field names whose values are unknown' in op:
        return [f for f in ('uncertainty', 'method', 'basis') if kv[f] == 'unknown']
    if kv['uncertainty'] == 'unknown':
        return 'unknown'
    l, u = Decimal(kv['length'][:-3]), Decimal(kv['uncertainty'][:-3])
    if '[length-uncertainty' in op:
        return [f'{l - u:.2f} mm', f'{l + u:.2f} mm']
    return 'inside' if l - u >= Decimal('12.48') and l + u <= Decimal('12.52') else 'outside'
'''

# Fake worker (oz.adapter/3 program): answers every job correctly from the packet, except IDs listed in mode.json.
FAKE_WORKER = ANSWER + r'''
import sys
from pathlib import Path
request = json.load(sys.stdin)
here = Path(__file__).parent
mode = json.loads((here / 'mode.json').read_text()) if (here / 'mode.json').exists() else {}
with open(here / 'captured.jsonl', 'a', encoding='utf-8') as f:
    f.write(json.dumps({'ids': request['ids']}) + '\n')
body = json.loads(request['prompt'])
lines = ['OZ/1g']
for block in body['jobs']:
    op = body['ops'][block[0]]
    for row in block[1:]:
        if row[0] in mode.get('fail', []):
            lines.append(json.dumps([row[0], 'error', 'missing_data', 'no length']))
        else:
            lines.append(json.dumps({row[0]: answer(op, body['refs'][row[1]])}))
json.dump({'reply': '\n'.join(lines), 'usage': {'input_tokens': 1000, 'output_tokens': 300}}, sys.stdout)
'''

# Fake caller (stands in for `claude -p ... --output-format stream-json`): K arms build an oz.do/1 request and run the
# `oz` shim's command; J does the work itself. Emits a stream-json transcript with usage.
FAKE_CALLER = ANSWER + r'''
import os, re, shlex, subprocess, sys
from pathlib import Path
if '--version' in sys.argv:
    print('0.0.0 (fake caller)'); sys.exit(0)
prompt = sys.stdin.buffer.read().decode('utf-8')
lines = prompt.split('\n')
msgs = [(m.group(1), json.loads(m.group(2))) for m in (re.match(r'^(ma_\d+) request (".*")$', l) for l in lines) if m]
goal = next(l[6:] for l in lines if l.startswith('Goal: '))
files = 'refs/N.txt' in prompt
inline = {}
for i, l in enumerate(lines):
    if l.startswith('Refs ['):
        inline = {str(r[0]): r[2] for r in json.loads(lines[i + 1])}
def ref_of(text):
    return re.search(r'[Rr]eference (\d+)', text).group(1)
def ref_text(k):
    return Path(f'refs/{k}.txt').read_text(encoding='utf-8') if files else inline[k]
def norm(text):
    return re.sub(r"^Reference \d+: ", '', re.sub(r"reference \d+'s", "the reference's", text))
tools, out_text = [], ''
artifact = 'reply only with the JSON `{"outside"' in prompt
if 'You have the `oz` command' in prompt:
    ops, jobs, refs = {}, [], {}
    for mid, text in msgs:
        name = 'op%d' % list(dict.fromkeys(norm(t) for _, t in msgs)).index(norm(text))
        ops[name] = norm(text)
        k = ref_of(text)
        refs['r' + k] = {'path': f'refs/{k}.txt'} if files else inline[k]
        jobs.append([mid, name, 'r' + k])
    request = json.dumps({'model': 'claude-sonnet-5-5', 'goal': goal, 'ops': ops, 'refs': refs, 'jobs': jobs})
    shim = next(Path(d) / 'oz' for d in os.environ['PATH'].split(os.pathsep) if (Path(d) / 'oz').is_file())
    exec_line = [l for l in shim.read_text().splitlines() if l.startswith('exec ')][0]
    base = [a for a in shlex.split(exec_line)[1:] if a != '$@']
    if 'oz do request.json' in prompt:
        Path('request.json').write_text(request, encoding='utf-8')
        args, stdin, command = ['do', 'request.json', '--adapter', 'adapter.json'], b'', 'cat > request.json <<EOF\n' + request + '\nEOF\noz do request.json --adapter adapter.json'
    else:
        flag = ['--receipt'] if '--receipt' in prompt else []
        args, stdin = ['do', '--adapter', 'adapter.json', *flag], request.encode('utf-8')
        command = 'oz do --adapter adapter.json %s<<\'EOF\'\n%s\nEOF' % (' '.join(flag) + ' ' if flag else '', request)
    proc = subprocess.run(base + args, input=stdin, capture_output=True)
    tools.append((command, proc.stdout.decode('utf-8')))
    if Path('results.json').exists():
        result = json.loads(Path('results.json').read_text(encoding='utf-8'))
    else:
        result = json.loads(proc.stdout.decode('utf-8'))
    jobs_out = result['jobs']
else:
    tools.append(('cat refs/*.txt' if files else 'true', ''))
    jobs_out = {mid: {'status': 'accepted', 'value': answer(norm(text), ref_text(ref_of(text)))} for mid, text in msgs}
    if artifact:
        Path('results.json').write_text(json.dumps({'jobs': jobs_out}), encoding='utf-8')
if artifact:
    lists = {'outside': [m for m, _ in msgs if jobs_out[m].get('value') == 'outside'],
             'unknown': [m for m, _ in msgs if jobs_out[m].get('value') == 'unknown'],
             'not_accepted': [m for m, _ in msgs if jobs_out[m]['status'] != 'accepted']}
    out_text = json.dumps(lists)
else:
    rows = []
    for m, _ in msgs:
        j = jobs_out[m]
        v = j.get('value')
        rows.append([m, 0 if j['status'] == 'accepted' else 2, v if isinstance(v, str) else json.dumps(v) if j['status'] == 'accepted' else 'failed'])
    out_text = json.dumps({'results': rows})
events = [{'type': 'system', 'subtype': 'init'}]
for i, (command, result) in enumerate(tools):
    events.append({'type': 'assistant', 'message': {'id': 'msg%d' % i, 'content': [
        {'type': 'tool_use', 'id': 'tu%d' % i, 'name': 'Bash', 'input': {'command': command}}],
        'usage': {'input_tokens': 10, 'output_tokens': 40 + len(command) // 3}}})
    events.append({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'tu%d' % i, 'content': result}]}})
events.append({'type': 'assistant', 'message': {'id': 'final', 'content': [{'type': 'text', 'text': out_text}],
               'usage': {'input_tokens': 10, 'output_tokens': 30 + len(out_text) // 3}}})
events.append({'type': 'result', 'result': out_text, 'is_error': False, 'num_turns': len(tools) + 1,
               'modelUsage': {'claude-sonnet-5-5': {'inputTokens': 900, 'cacheReadInputTokens': 4000,
                                                     'cacheCreationInputTokens': 100, 'outputTokens': 600}}})
sys.stdout.write(''.join(json.dumps(e) + '\n' for e in events))
'''
CAPS = {'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}


def perfect_reply(spec):
    return json.dumps({'results': [[m, 0, v if isinstance(v, str) else json.dumps(v)]
                                   for m, v in spec['expected'].items()]})


def perfect_file(spec):
    return json.dumps({'jobs': {m: {'status': 'accepted', 'value': v} for m, v in spec['expected'].items()}}).encode()


class Temp(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)


# ---------- seed binding (the pilot_k cross-seed bug) ----------
class SeedBindingTests(unittest.TestCase):
    def test_archived_records_rejudge_to_stored_values(self):
        """Every stored arm K record re-judges to its stored (rescored) value, and every stored J record too."""
        checked = 0
        for name, arm in (('pilot_k_sonnet16.jsonl', 'K'), ('pilot_k_sonnet64.jsonl', 'K'),
                          ('pilot2_sonnet.jsonl', 'J'), ('pilot2_sonnet64.jsonl', 'J')):
            for r in K.load(DATA / name):
                if r['arm'] != arm:
                    continue
                n = r.get('n') or r['jobs']
                spec = K.build_spec('A', 'reply', 'J', n, r['seed'])
                if arm == 'K':
                    self.assertTrue(r['rescored'])
                self.assertEqual(K.judge_reply(r['text'], spec), ('', r['jobs_passed']), (name, r['seed']))
                checked += 1
        self.assertEqual(checked, 12)

    def test_the_old_bug_would_be_caught(self):
        """Judging seed 3105's stored reply with seed 3107's records (what pilot_k did) loses jobs."""
        r = next(r for r in K.load(DATA / 'pilot_k_sonnet64.jsonl') if r['seed'] == 3105)
        self.assertEqual(K.judge_reply(r['text'], K.build_spec('A', 'reply', 'K0', 64, 3105))[1], 64)
        self.assertLess(K.judge_reply(r['text'], K.build_spec('A', 'reply', 'K0', 64, 3107))[1], 64)

    def test_specs_built_first_then_judged_in_any_global_state(self):
        """Build every counted spec before judging (the order that caused the bug), scramble the module records,
        then judge: each run still gets full marks against its own seed."""
        specs = [K.build_spec(*c) for c in K.schedule()]
        K.M.use_records(K.M.make_records(1))
        for spec in specs:
            if spec['contract'] == 'reply':
                self.assertEqual(K.judge_reply(perfect_reply(spec), spec), ('', spec['n']), spec['tag'])
            else:
                lists = K.continuation_expected(spec)
                self.assertEqual(K.judge_artifact(perfect_file(spec), json.dumps(lists), spec)['verified'], spec['n'])

    def test_cross_seed_judgment_fails(self):
        for (block, n), seeds in K.SEEDS.items():
            a, b = (K.build_spec(block, 'reply', 'J', n, s) for s in seeds[:2])
            self.assertLess(K.judge_reply(perfect_reply(a), b)[1], n, (block, n))
            self.assertNotEqual(a['input_sha256'], b['input_sha256'])

    def test_pure_oracle_matches_live6(self):
        for seed in (3005, 3107, 7001, 7203):
            recs = K.M.make_records(seed)
            K.M.use_records(recs)
            for job in K.job_codes(64):
                self.assertEqual(K.oracle(recs[int(job[1:])], job[0]), K.X.oracle(job[0], int(job[1:])))

    def test_rejudge_command_uses_each_records_seed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'k2.jsonl'
            rows = []
            for cell in [('B', 'art', 'K1r', 16, 7001), ('B', 'art', 'J', 16, 7002), ('A', 'reply', 'J', 64, 3105)]:
                spec = K.build_spec(*cell)
                run = path.with_suffix('') / spec['tag']
                run.mkdir(parents=True)
                if spec['contract'] == 'art':
                    (run / 'results.json').write_bytes(perfect_file(spec))
                    text = json.dumps(K.continuation_expected(spec))
                else:
                    text = perfect_reply(spec)
                rows.append({'tag': spec['tag'], 'block': cell[0], 'contract': cell[1], 'arm': cell[2], 'n': cell[3],
                             'seed': cell[4], 'input_sha256': spec['input_sha256'], 'text': text, 'verified': cell[3]})
            path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(K.rejudge(path), 0)
                rows[1]['verified'] = 15
                path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
                self.assertEqual(K.rejudge(path), 1)


# ---------- artifact and continuation oracle (round 04) ----------
class ContinuationOracleTests(unittest.TestCase):
    def setUp(self):
        self.spec = K.build_spec('B', 'art', 'J', 16, 7001)
        self.lists = K.continuation_expected(self.spec)
        self.reply = json.dumps(self.lists)

    def judge(self, data, reply=None):
        return K.judge_artifact(data, self.reply if reply is None else reply, self.spec)

    def test_frozen_text_is_verbatim_round_04(self):
        sign = (K.REPO / 'docs/design/caller-cost-2026-10-23/04-opus-r2-sign.md').read_text(encoding='utf-8')
        flat = ' '.join(sign.split())
        self.assertIn(' '.join(K.CONTINUATION.split()), flat)

    def test_correct(self):
        self.assertEqual(self.lists, {'outside': ['ma_04', 'ma_08', 'ma_16'], 'unknown': ['ma_10', 'ma_12'],
                                      'not_accepted': []})
        res = self.judge(perfect_file(self.spec))
        self.assertEqual((res['verified'], res['reply_ok'], res['file_error']), (16, True, ''))

    def test_reply_variants_score_zero(self):
        bad = [json.dumps({'outside': self.lists['outside'][::-1], 'unknown': self.lists['unknown'], 'not_accepted': []}),
               json.dumps(dict(self.lists, extra=[])),
               json.dumps({'outside': self.lists['outside'], 'unknown': self.lists['unknown']}),
               'Here it is: ' + self.reply,
               '```json\n' + self.reply + '\n```',
               json.dumps(dict(self.lists, not_accepted=['ma_01'])),
               json.dumps(dict(self.lists, unknown=self.lists['unknown'] + ['ma_10'])),
               json.dumps(dict(self.lists, outside=[4, 8, 16])),
               '{"outside":[],"outside":[],"unknown":[],"not_accepted":[]}',
               '{"outside":NaN,"unknown":[],"not_accepted":[]}', '', None]
        for reply in bad:
            res = self.judge(perfect_file(self.spec), reply if reply is not None else 'null')
            self.assertEqual((res['verified'], res['reply_ok']), (0, False), reply)
            self.assertEqual(res['file_jobs_passed'], 16)

    def test_corrupted_artifacts_score_zero(self):
        good = perfect_file(self.spec)
        obj = json.loads(good)
        missing = json.loads(good); del missing['jobs']['ma_07']
        extra = json.loads(good); extra['jobs']['ma_99'] = {'status': 'accepted', 'value': 'x'}
        status = json.loads(good); status['jobs']['ma_01']['status'] = 'ok'
        entry = json.loads(good); entry['jobs']['ma_01'] = ['accepted', 'x']
        corrupt = [None, b'', good[:len(good) // 2], b'\xef\xbb\xbf' + good, good.replace(b'"jobs"', b'"jobs": {}, "jobs"', 1),
                   b'\xff' + good, json.dumps([obj]).encode(), json.dumps({'results': obj['jobs']}).encode(),
                   json.dumps({'jobs': list(obj['jobs'].items())}).encode(), json.dumps(missing).encode(),
                   json.dumps(extra).encode(), json.dumps(status).encode(), json.dumps(entry).encode(),
                   good.replace(b'"value": "outside"', b'"value": NaN', 1)]
        for data in corrupt:
            res = self.judge(data)
            self.assertEqual(res['verified'], 0, data[:80] if data else data)
            self.assertTrue(res['file_error'], data[:80] if data else data)

    def test_per_job_oracle(self):
        obj = json.loads(perfect_file(self.spec))
        obj['jobs']['ma_02']['value'] = ['12.40 mm', '12.47 mm']             # wrong value
        del obj['jobs']['ma_03']['value']                                    # accepted without value
        obj['jobs']['ma_05']['value'] = json.dumps(obj['jobs']['ma_05']['value'])   # JSON text in a string: accepted
        obj['jobs']['ma_06']['status'] = 'failed'                            # not accepted
        obj['jobs']['ma_09']['value'] = True                                 # wrong type
        res = self.judge(json.dumps(obj).encode())
        self.assertEqual((res['file_jobs_passed'], res['verified']), (12, 12))

    def test_file_reported_failure_needs_matching_reply(self):
        """A job the file marks failed puts its ID in not_accepted, which differs from the expected empty list: 0."""
        obj = json.loads(perfect_file(self.spec))
        obj['jobs']['ma_01'] = {'status': 'failed', 'code': 'missing_data', 'message': 'x'}
        honest = json.dumps(dict(self.lists, not_accepted=['ma_01']))
        self.assertEqual(self.judge(json.dumps(obj).encode(), honest)['verified'], 0)
        self.assertEqual(self.judge(json.dumps(obj).encode())['verified'], 15)

    def test_reply_contract_oracle(self):
        spec = K.build_spec('B', 'reply', 'K1f', 64, 7101)
        self.assertEqual(K.judge_reply(perfect_reply(spec), spec), ('', 64))
        rows = json.loads(perfect_reply(spec))['results']
        rows[3][2] = 'inside' if rows[3][2] != 'inside' else 'outside'
        self.assertEqual(K.judge_reply(json.dumps({'results': rows}), spec), ('', 63))
        self.assertEqual(K.judge_reply('```json\n' + perfect_reply(spec) + '\n```', spec)[1], 0)
        self.assertEqual(K.judge_reply(json.dumps({'results': rows[:-1]}), spec)[1], 0)


# ---------- workload, texts and schedule ----------
class WorkloadTests(unittest.TestCase):
    def test_schedule_matches_signed_plan(self):
        cells = K.schedule()
        self.assertEqual(len(cells), 48)
        count = lambda **kw: sum(all(dict(zip(('block', 'contract', 'arm', 'n', 'seed'), c))[k] == v for k, v in kw.items())
                                 for c in cells)
        self.assertEqual(count(arm='K0'), 3)
        self.assertEqual(count(block='A') - count(arm='K0'), 9)
        self.assertEqual(count(block='B', contract='reply'), 12)
        self.assertEqual(count(block='B', contract='art'), 18)
        self.assertEqual(count(block='C'), 6)
        self.assertEqual(len({c[:4] + (c[4],) for c in cells}), 48)
        self.assertEqual({c[4] for c in cells if c[0] == 'A' and c[3] == 16}, {3005, 3006, 3007})
        self.assertEqual({c[4] for c in cells if c[0] == 'A' and c[3] == 64}, {3105, 3106, 3107})

    def test_fresh_seeds_unused_in_stored_data(self):
        fresh = {s for (b, n), seeds in K.SEEDS.items() if b != 'A' for s in seeds}
        self.assertEqual(len(fresh), 9)
        used = set()
        for path in DATA.glob('*.jsonl'):
            if path.name.startswith('pilot_k2'):
                continue
            for line in path.read_text(encoding='utf-8').splitlines():
                with contextlib.suppress(ValueError):
                    r = json.loads(line)
                    if isinstance(r, dict) and isinstance(r.get('seed'), int):
                        used.add(r['seed'])
        self.assertFalse(fresh & used)
        self.assertNotIn(K.SMOKE_SEED, fresh)

    def test_block_c_references(self):
        spec = K.build_spec('C', 'art', 'J', 64, 7201)
        self.assertEqual(len(spec['files']), 16)
        positions = set()
        recs = K.M.make_records(7201)
        for k in range(1, 17):
            data = spec['files'][f'refs/{k}.txt']
            self.assertEqual(len(data), K.REF_BYTES)
            text = data.decode('ascii')
            line = K.record_line(recs[k])
            self.assertEqual(text.split('\n').count(line), 1)
            positions.add(text.index(line))
            filler = text.replace(line, '')
            self.assertFalse(set(filler) & set('=;0123456789'))
            words = set(filler.lower().replace('.', ' ').split())
            self.assertFalse(words & {'length', 'uncertainty', 'n', 'method', 'basis', 'physical_validation', 'unknown',
                                      'micrometer', 'caliper', 'expanded', 'resolution', 'not_claimed', 'inside',
                                      'outside', 'mm'})
        self.assertGreater(len(positions), 8)
        self.assertEqual(spec['files'], K.build_spec('C', 'art', 'K1r', 64, 7201)['files'])
        self.assertEqual(K.build_spec('C', 'art', 'K1r', 64, 7201)['max_tokens'], K.C_MAX_TOKENS)

    def test_same_source_access_and_task_for_j_and_k(self):
        for block, contract, n, seed in (('B', 'reply', 16, 7001), ('B', 'art', 64, 7101), ('C', 'art', 64, 7201)):
            j = K.build_spec(block, contract, 'J', n, seed)
            for arm in ('K1f', 'K1r'):
                k = K.build_spec(block, contract, arm, n, seed)
                self.assertTrue(k['prompt'].endswith('\n\n' + j['prompt']))
                self.assertEqual((k['files'], k['expected'], k['ids']), (j['files'], j['expected'], j['ids']))
        b = K.build_spec('B', 'reply', 'J', 16, 7001)
        self.assertEqual(b['files']['refs/1.txt'].decode(), K.record_line(K.M.make_records(7001)[1]))
        self.assertNotIn('length=', b['prompt'])

    def test_k1_full_and_receipt_differ_only_in_mode_sentence_and_flag(self):
        f, r = K.k1_text('K1f', 'art'), K.k1_text('K1r', 'art')
        self.assertEqual(f.replace(K.K1_MODE['K1f'], '').replace('adapter.json`', 'adapter.json --receipt`'),
                         r.replace(K.K1_MODE['K1r'], ''))

    def test_block_a_prompts_match_the_pilot(self):
        import pilot2
        import pilot_k
        j = K.build_spec('A', 'reply', 'J', 16, 3005)
        self.assertEqual(j['prompt'], pilot2.calls(3005, 'J')[0][1])
        k0 = K.build_spec('A', 'reply', 'K0', 64, 3105)
        self.assertEqual(k0['prompt'], pilot_k.K_TEXT + K.build_spec('A', 'reply', 'J', 64, 3105)['prompt'])
        self.assertEqual(k0['oz'], 'legacy')

    def test_manifest_is_deterministic(self):
        self.assertEqual(K.manifest()[0], K.manifest()[0])


# ---------- receipt bound ----------
def fake_result(n, accepted=0, id_len=64, model='m', path_extra=None):
    ids = [(f'{i:04d}' + 'x' * id_len)[:id_len] for i in range(n)]
    jobs = {mid: {'status': 'accepted', 'value': 'v'} if i < accepted else {'status': 'unresolved', 'reason': 'deadline'}
            for i, mid in enumerate(ids)}
    counts = {'accepted': accepted, 'unresolved': n - accepted} if accepted < n else {'accepted': n}
    return ids, {'schema': 'oz.do.result/1', 'status': 'incomplete', 'counts': counts, 'jobs': jobs,
                 'evidence': {'scope': 'model_declared'}, 'calls': [],
                 'accounting': {'calls': 1, 'failed_calls': 0, 'usage_coverage': 'complete',
                                'tokens': {'input_tokens': 10 ** 15, 'output_tokens': 10 ** 15}},
                 'blocker': {'reason': 'experimental_size_not_authorized', 'size': 256, 'model': model},
                 'run': {'request_id': 'r' * 64, 'request_sha256': 'f' * 64}}


class ReceiptTests(unittest.TestCase):
    def check(self, result, path, ids):
        text = W.receipt(result, path, 123456789, 'a' * 64)
        self.assertLessEqual(len(text.encode('utf-8')), W.RECEIPT_BYTES)
        r = json.loads(text)
        pending = [m for m in ids if result['jobs'][m]['status'] != 'accepted']
        na = r['not_accepted']
        self.assertEqual(na['total'], len(pending))
        self.assertEqual(na['listed'], pending[:len(na['listed'])])
        self.assertEqual(na['omitted'], len(pending) - len(na['listed']))
        self.assertLessEqual(len(na['listed']), 32)
        self.assertEqual(r['schema'], 'oz.do.receipt/1')
        self.assertNotIn('value', text)
        return r

    def test_job_counts(self):
        for n in (1, 64, 256):
            ids, result = fake_result(n, id_len=5)
            r = self.check(result, 'results.json', ids)
            self.assertEqual(len(r['not_accepted']['listed']), min(n, 32))
            ids, result = fake_result(n, accepted=n, id_len=5)
            self.assertEqual(self.check(result, 'results.json', ids)['not_accepted'], {'total': 0, 'listed': [], 'omitted': 0})

    def test_long_ids_paths_and_blocker(self):
        nasty = 'C:/' + 'ü/\u2028"\\\x01' * 3000 + '/results.json'
        for n in (1, 33, 64, 256):
            ids, result = fake_result(n, id_len=64, model='M\x00"' * 4000)
            result['blocker'].update({'a' * 500: 'b' * 9000, 'c': [1] * 999, 'd': {'x': 'y' * 999}, 'e': 1.5})
            result['counts'].update({'x' * 900: 1, 'y' * 900: 2, 'z' * 900: 3})
            result['status'] = 's' * 5000
            result['evidence']['scope'] = 'e' * 5000
            result['accounting']['usage_coverage'] = 'u' * 5000
            result['run']['request_id'] = 'q' * 5000
            r = self.check(result, nasty, ids)
            self.assertGreaterEqual(len(r['not_accepted']['listed']), min(n, 8))
            self.assertTrue(r['artifact']['path'].startswith('...') and r['artifact']['path'].endswith('/results.json'))
            self.assertIn('artifact.path', r['truncated'])
            self.assertIn('blocker', r['truncated'])

    def test_short_fields_kept_exactly(self):
        ids, result = fake_result(3, accepted=1, id_len=5)
        r = self.check(result, 'out/results.json', ids)
        self.assertEqual((r['artifact']['path'], r['artifact']['bytes'], r['request']['request_id']),
                         ('out/results.json', 123456789, 'r' * 64))
        self.assertEqual(r['truncated'], [])
        self.assertEqual(r['blocker'], {'reason': 'experimental_size_not_authorized', 'model': 'm', 'size': 256})

    def test_fit(self):
        self.assertEqual(W.fit('abc', 10), ('abc', False))
        head, cut = W.fit('abcdefghij', 8)
        self.assertEqual((head, cut), ('abc...', True))
        self.assertEqual(W.fit('abcdefghij', 8, tail=True), ('...hij', True))
        text, _ = W.fit('ü' * 100, 20)
        self.assertLessEqual(W.size(text), 20)


# ---------- wrapper: publication, digest, binding, resume, exit codes ----------
def wrapper_request(n=4, **extra):
    value = {'request_id': 'k2t', 'model': 'claude-sonnet-5-5', 'goal': 'Report length facts only.',
             'ops': {'v': "Reference: Return inside if the entire length +/- uncertainty interval lies within the goal's "
                          'acceptance interval; outside otherwise. If uncertainty is unknown, return unknown.'},
             'refs': {'c1': 'length=12.50 mm; uncertainty=0.02 mm; n=3; method=unknown; basis=unknown; physical_validation=x',
                      'c2': 'length=12.47 mm; uncertainty=0.03 mm; n=5; method=caliper; basis=expanded; physical_validation=x'},
             'jobs': [[f'j{i}', 'v', 'c1' if i % 2 else 'c2'] for i in range(1, n + 1)]}
    value.update(extra)
    return json.dumps(value).encode('utf-8')


class WrapperTests(Temp):
    def setUp(self):
        super().setUp()
        self.ws = self.tmp / 'ws'
        initialize(self.ws)
        (self.ws / 'fake.py').write_text(FAKE_WORKER, encoding='utf-8')
        (self.ws / 'adapter.json').write_text(json.dumps({'argv': [sys.executable, 'fake.py'], **CAPS}), encoding='utf-8')
        self.out = self.tmp / 'results.json'
        self.archive = self.tmp / 'archive'

    def calls(self):
        path = self.ws / 'captured.jsonl'
        return len(path.read_text(encoding='utf-8').splitlines()) if path.exists() else 0

    def wrap(self, raw, *flags, legacy=False):
        out, err = io.StringIO(), io.StringIO()
        pre = ['--archive', str(self.archive)] + (['--legacy'] if legacy else [])
        args = ['do', '--workspace', str(self.ws), '--adapter', str(self.ws / 'adapter.json')]
        if not legacy:
            args += ['--out', str(self.out), *flags]
        code = W.main(pre + args, stdin=io.BytesIO(raw), stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def test_full_mode_prints_what_it_publishes(self):
        raw = wrapper_request()
        code, out, err = self.wrap(raw)
        self.assertEqual((code, err), (0, ''))
        data = self.out.read_bytes()
        self.assertEqual(out.encode('utf-8'), data)
        digest = hashlib.sha256(data).hexdigest()
        self.assertEqual((self.tmp / 'results.json.sha256').read_text(), f'{digest}  results.json\n')
        result = json.loads(data)
        self.assertEqual(result['schema'], 'oz.do.result/1')
        self.assertEqual([j['value'] for j in result['jobs'].values()], ['inside', 'outside'] * 2)
        self.assertEqual((self.archive / '0000' / 'request.bin').read_bytes(), raw)
        self.assertEqual(json.loads((self.archive / '0000' / 'published.json').read_text())['sha256'], digest)
        self.assertEqual(json.loads((self.archive / '0000' / 'meta.json').read_text())['mode'], 'full')
        self.assertFalse([p for p in self.tmp.iterdir() if p.name.endswith('.tmp')])

    def test_receipt_digest_binding_and_resume(self):
        code, out, err = self.wrap(wrapper_request(), '--receipt')
        self.assertEqual((code, err), (0, ''))
        self.assertLessEqual(len(out.encode('utf-8')), W.RECEIPT_BYTES + 1)
        rec = json.loads(out)
        data = self.out.read_bytes()
        full = json.loads(data)
        self.assertEqual(rec['artifact'], {'path': str(self.out), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        self.assertEqual(rec['request'], {'request_id': 'k2t', 'sha256': full['run']['request_sha256']})
        self.assertEqual((rec['status'], rec['jobs'], rec['counts']), ('complete', 4, {'accepted': 4}))
        self.assertEqual(self.calls(), 1)
        # resubmission: same request, no new worker call, a fresh publication that matches its own receipt
        code, out2, _ = self.wrap(wrapper_request(), '--receipt')
        self.assertEqual((code, self.calls()), (0, 1))
        data2 = self.out.read_bytes()
        self.assertEqual(json.loads(out2)['artifact']['sha256'], hashlib.sha256(data2).hexdigest())
        self.assertEqual(json.loads(data2)['jobs'], full['jobs'])
        # binding: the same request_id naming different work is refused; nothing is published
        code, out3, err3 = self.wrap(wrapper_request(n=5), '--receipt')
        self.assertEqual((code, out3, self.out.read_bytes(), self.calls()), (2, '', data2, 1))
        self.assertTrue(err3.startswith('oz: request_id k2t already names different work'))

    def test_exit_codes(self):
        (self.ws / 'mode.json').write_text(json.dumps({'fail': ['j2']}), encoding='utf-8')
        code, out, _ = self.wrap(wrapper_request(), '--receipt')
        rec = json.loads(out)
        self.assertEqual(code, 3)
        self.assertEqual(rec['not_accepted'], {'total': 1, 'listed': ['j2'], 'omitted': 0})
        self.assertEqual(json.loads(self.out.read_bytes())['jobs']['j2']['status'], 'failed')
        before = self.out.read_bytes()
        for raw in (b'{not json', b'\xff\xfe', json.dumps({'goal': 'x'}).encode()):
            code, out, err = self.wrap(raw, '--receipt')
            self.assertEqual((code, out, self.out.read_bytes()), (2, '', before))
            self.assertTrue(err.startswith('oz: '))
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(W.main(['do', '--receipt'], stdin=io.BytesIO(b''), stdout=out, stderr=err), 2)

    def test_atomic_publication(self):
        self.out.write_bytes(b'old')
        for target in ('os.replace', 'os.fsync'):
            with mock.patch(target, side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    W.publish(self.out, b'new contents')
            self.assertEqual(self.out.read_bytes(), b'old')
            self.assertFalse([p for p in self.tmp.iterdir() if p.name.endswith('.tmp')])
        digest = W.publish(self.out, b'new contents')
        self.assertEqual((self.out.read_bytes(), digest), (b'new contents', hashlib.sha256(b'new contents').hexdigest()))
        # a failed publication inside `oz do` exits 2, prints nothing, and leaves the previous file
        with mock.patch.object(W, 'publish', side_effect=OSError('disk full')):
            code, out, err = self.wrap(wrapper_request(), '--receipt')
        self.assertEqual((code, out, self.out.read_bytes()), (2, '', b'new contents'))
        self.assertIn('cannot publish', err)

    def test_legacy_mode_delegates_unchanged(self):
        raw = wrapper_request()
        code, out, err = self.wrap(raw, legacy=True)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out)['counts'], {'accepted': 4})
        self.assertFalse(self.out.exists())
        self.assertEqual((self.archive / '0000' / 'request.bin').read_bytes(), raw)
        self.assertEqual(json.loads((self.archive / '0000' / 'meta.json').read_text())['mode'], 'legacy')


# ---------- stream parsing and G3 attribution ----------
class TranscriptTests(unittest.TestCase):
    def stream(self):
        req = '{"goal":"g","ops":{"a":"x"},"refs":{},"jobs":[["j1","a"]]}'
        ev = [{'type': 'system'},
              {'type': 'assistant', 'message': {'id': 'm1', 'content': [{'type': 'text', 'text': 'ok'}], 'usage': {'output_tokens': 5}}},
              {'type': 'assistant', 'message': {'id': 'm1', 'content': [{'type': 'tool_use', 'id': 't1', 'name': 'Bash',
               'input': {'command': "oz do --adapter adapter.json <<'EOF'\n" + req + '\nEOF'}}], 'usage': {'output_tokens': 50}}},
              {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't1', 'content': 'x' * 300}]}},
              {'type': 'assistant', 'parent_tool_use_id': 'zz', 'message': {'id': 'sub', 'content': [{'type': 'tool_use', 'id': 's', 'name': 'Bash', 'input': {}}]}},
              {'type': 'assistant', 'message': {'id': 'm2', 'content': [{'type': 'tool_use', 'id': 't2', 'name': 'Bash', 'input': {'command': 'cat results.json'}}], 'usage': {'output_tokens': 20}}},
              {'type': 'assistant', 'message': {'id': 'm3', 'content': [{'type': 'text', 'text': '{"a":1}'}], 'usage': {'output_tokens': 10}}},
              {'type': 'result', 'result': '{"a":1}', 'num_turns': 3, 'is_error': False,
               'modelUsage': {'x': {'inputTokens': 100, 'cacheReadInputTokens': 1000, 'cacheCreationInputTokens': 50, 'outputTokens': 85}}}]
        return '\n'.join(json.dumps(e) for e in ev) + '\nnot json\n'

    def test_parse_stream(self):
        p = K.parse_stream(self.stream())
        self.assertEqual((p['caller_in'], p['caller_out'], p['caller_cache_read'], p['turns']), (1150, 85, 1000, 3))
        self.assertEqual((p['bash_calls'], p['oz_do_calls'], p['unparsed_lines']), (2, 1, 1))
        self.assertEqual([m['id'] for m in p['messages']], ['m1', 'm2', 'm3'])
        self.assertEqual(p['messages'][0]['output_tokens'], 50)
        self.assertEqual(p['tools'][0]['result_bytes'], 300)
        self.assertEqual(p['text'], '{"a":1}')

    def test_attribution(self):
        p = K.parse_stream(self.stream())
        a = K.attribution(p, 2000, count=lambda s: len(s) // 4)
        self.assertEqual(a['carriers'], 1)
        self.assertEqual(a['upper'], 50 * 3)            # message m1 output, read again in m2 and m3
        self.assertAlmostEqual(a['upper_share'], 0.075)
        ratio = 85 / (len(p['emitted']) // 4)
        self.assertAlmostEqual(a['estimate'], (len(p['tools'][0]['input']) // 4) * 3 * ratio)
        self.assertEqual(K.attribution(K.parse_stream(''), 0)['upper_share'], 0.0)


# ---------- end to end with fake caller and fake worker ----------
class EndToEndTests(Temp):
    def setUp(self):
        super().setUp()
        (self.tmp / 'caller.py').write_text(FAKE_CALLER, encoding='utf-8')
        self.worker_dir = self.tmp / 'worker'
        self.worker_dir.mkdir()
        (self.worker_dir / 'worker.py').write_text(FAKE_WORKER, encoding='utf-8')
        self.claude = [sys.executable, str(self.tmp / 'caller.py')]
        self.delegate = [sys.executable, str(self.worker_dir / 'worker.py')]

    def run_cell(self, *cell, tag=None):
        spec = K.build_spec(*cell)
        return K.run_one(spec, self.tmp / 'data' / (tag or spec['tag']), claude=self.claude, delegate=self.delegate)

    def test_every_arm_type(self):
        for cell in [('A', 'reply', 'K0', 64, 3105), ('A', 'reply', 'J', 16, 3005), ('B', 'reply', 'K1f', 16, 7001),
                     ('B', 'art', 'K1r', 16, 7002), ('B', 'art', 'K1f', 64, 7101), ('C', 'art', 'K1r', 64, 7201),
                     ('C', 'art', 'J', 64, 7202)]:
            rec = self.run_cell(*cell)
            run = self.tmp / 'data' / rec['tag']
            self.assertEqual(rec['verified'], cell[3], rec)
            self.assertTrue(rec['usage_complete'])
            self.assertEqual(rec['total_tokens'], 5600 + rec['worker_in'] + rec['worker_out'])
            self.assertTrue((run / 'transcript.jsonl').read_bytes())
            self.assertEqual((run / 'prompt.txt').read_text(encoding='utf-8'), K.build_spec(*cell)['prompt'])
            if cell[2] == 'J':
                self.assertEqual((rec['worker_calls'], rec['attribution']), (0, None))
                continue
            self.assertEqual((rec['worker_calls'], rec['worker_calls_with_usage'], rec['oz_invocations']), (1, 1, 1))
            self.assertEqual(rec['attribution']['carriers'], 1)
            self.assertGreater(rec['attribution']['upper_share'], 0)
            req = json.loads((run / 'archive' / 'oz' / '0000' / 'request.bin').read_bytes())
            self.assertEqual(len(req['jobs']), cell[3])
            packets = (run / 'archive' / 'worker' / 'packets.jsonl').read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(json.loads(packets[0])['request']['ids']), cell[3])
            self.assertTrue(list(run.glob('do/*/calls.jsonl')))
            if cell[2] == 'K0':
                self.assertIsNone(rec['published_sha256'])
            else:
                self.assertTrue(rec['artifact_intact'])
            if cell[0] == 'C':
                self.assertGreater(rec['worker_in'], 0)
                prompt = json.loads(json.loads(packets[0])['request']['prompt'])
                self.assertEqual(sorted(len(r.encode()) for r in prompt['refs']), [K.REF_BYTES] * 16)

    def test_worker_failure_scores_zero_in_artifact_contract(self):
        (self.worker_dir / 'mode.json').write_text(json.dumps({'fail': ['ma_03']}), encoding='utf-8')
        rec = self.run_cell('B', 'art', 'K1r', 16, 7003)
        self.assertEqual((rec['file_jobs_passed'], rec['reply_ok'], rec['verified']), (15, False, 0))
        self.assertIn('not_accepted', rec['reply_error'])
        self.assertIsNone(rec['tokens_per_verified'])
        rec = self.run_cell('B', 'reply', 'K1f', 16, 7003)
        self.assertEqual(rec['verified'], 15)

    def test_counted_run_resumes_and_stops_on_drift(self):
        cells = [('B', 'art', 'K1r', 16, 7001), ('B', 'art', 'J', 16, 7001)]
        out = self.tmp / 'data' / 'k2.jsonl'
        out.parent.mkdir()
        env = {'cli_version': 'x', 'git_head': 'h', 'core_sha256': {'oz_do.py': 'a'}}
        with mock.patch.object(K, 'schedule', return_value=cells), mock.patch.object(K, 'environment', return_value=env), \
                contextlib.redirect_stdout(io.StringIO()):
            digest = K.manifest()[0]
            with self.assertRaises(SystemExit):
                K.counted('0' * 64, out=out)
            K.counted(digest, out=out, claude=self.claude, delegate=self.delegate)
            rows = K.load(out)
            self.assertEqual([r['tag'] for r in rows], ['B-art-K1r-16-7001', 'B-art-J-16-7001'])
            self.assertTrue(all(r['verified'] == 16 and r['manifest'] == digest for r in rows))
            K.counted(digest, out=out, claude=self.claude, delegate=self.delegate)
            self.assertEqual(len(K.load(out)), 2)
            out.write_text(json.dumps(rows[0]) + '\n', encoding='utf-8')   # second run lost: it is redone
            drift = dict(env, core_sha256={'oz_do.py': 'b'})
            with mock.patch.object(K, 'environment', return_value=drift):
                with self.assertRaises(SystemExit):
                    K.counted(digest, out=out, claude=self.claude, delegate=self.delegate)
            K.counted(digest, out=out, claude=self.claude, delegate=self.delegate)
            self.assertEqual(len(K.load(out)), 2)
            self.assertTrue(list(out.with_suffix('').glob('B-art-J-16-7001.aborted-*')))
            gates = K.gates(K.load(out))
            self.assertEqual(gates['G2'], 'incomplete')


if __name__ == '__main__':
    unittest.main()
