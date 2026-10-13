"""Smoke test of the measurement scripts against the current product code. Prints PASS/FAIL per check.

    TIKTOKEN_CACHE_DIR=.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/selftest.py
Needs tiktoken (live11 imports it through run_live), so run it with the .venv python from the repo root.
"""
import importlib.util, json, sys, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'bench'))
from oz_reply import encode_reply, Failure  # noqa: E402

RESULTS = []


def check(name):
    def deco(fn):
        try:
            fn()
            RESULTS.append(True); print(f'PASS {name}')
        except Exception as exc:  # noqa: BLE001
            RESULTS.append(False); print(f'FAIL {name}: {type(exc).__name__}: {exc}')
            traceback.print_exc(limit=3)
        return fn
    return deco


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def totals(mod, rows, arm, n):
    sel = [r for r in rows if r['arm'] == arm and r['n'] == n]
    s = [mod.score(r, r['text']) for r in sel]
    return f'{sum(x[0] for x in s)}/{len(sel)} valid', f'{sum(x[1] for x in s)}/{n * len(sel)}'


def rows_of(path):
    return [json.loads(l) for l in Path(path).read_text('utf-8').splitlines()]


KIT = ROOT / 'bench' / 'codex_kit'
score_d = load(KIT / 'score.py', 'score_kit')
score_e = load(ROOT / 'bench' / 'codex_kit_1e' / 'score.py', 'score_kit_1e')


@check('codex_kit/score.py scores every recorded results file (S1d and S1c)')
def _():
    files = sorted(KIT.glob('results_*.jsonl')) + sorted((KIT / 'old_s1c').glob('results_*.jsonl'))
    assert len(files) == 10, files
    for f in files:
        for r in rows_of(f):
            valid, correct = score_d.score(r, r['text'])
            assert isinstance(valid, bool) and 0 <= correct <= r['n']


@check('S1d Astra medium: 96/96 and 192/192')
def _():
    rows = rows_of(KIT / 'results_gpt-6-astra_medium.jsonl')
    got = (totals(score_d, rows, 'S1d', 32)[1], totals(score_d, rows, 'S1d', 64)[1])
    assert got == ('96/96', '192/192'), got


@check('old_s1c Luna medium S1c: 93/96 and 138/192')
def _():
    rows = rows_of(KIT / 'old_s1c' / 'results_gpt-6-luna_medium.jsonl')
    got = (totals(score_d, rows, 'S1c', 32)[1], totals(score_d, rows, 'S1c', 64)[1])
    assert got == ('93/96', '138/192'), got


def oracle_rows(arm, mod_dir):
    out = []
    for p in sorted((mod_dir / 'oracles').glob('rep*_n*.json')):
        d = json.loads(p.read_text('utf-8'))
        rep, n = (int(x) for x in p.stem.replace('rep', '').split('_n'))
        jobs, oracle = d['jobs'], d['oracle']
        if arm == 'S1c':
            lines = [json.dumps([i, v], ensure_ascii=False) for i, v in enumerate(oracle)]
        else:
            lines = [json.dumps([j, v], ensure_ascii=False) for j, v in zip(jobs, oracle)]
        out.append({'rep': rep, 'n': n, 'arm': arm, 'text': '\n'.join(lines) + '\n'})
    return out


@check('oracle replies score full marks for S1c, S1d, S1e, S1f (both score.py files)')
def _():
    for mod, kit in ((score_d, KIT), (score_e, ROOT / 'bench' / 'codex_kit_1e')):
        for arm in ('S1c', 'S1d', 'S1e', 'S1f'):
            for r in oracle_rows(arm, kit):
                assert mod.score(r, r['text']) == (True, r['n']), (kit.name, arm, r['rep'], r['n'])


@check('a job-error line is valid but not correct; a malformed S1f reply is invalid')
def _():
    r = oracle_rows('S1f', KIT)[0]
    lines = r['text'].splitlines()
    first = json.loads(lines[0])[0]
    lines[0] = json.dumps([first, 'error', 'missing_data', 'no data'])
    assert score_d.score(r, '\n'.join(lines)) == (True, r['n'] - 1)
    assert score_d.score(r, r['text'] + r['text'].splitlines()[0]) == (False, 0)
    assert score_d.score(r, '```\n' + r['text'] + '```') == (False, 0)


@check('bench/live/live11 imports')
def _():
    global X, live11
    sys.path.insert(0, str(ROOT / 'bench' / 'live'))
    import live11  # noqa: F401
    import live6 as X  # noqa: F401


def encode_1f(results, ids=None):
    """Stage-1f reply text ([id,value] / [id,"error",code,message] lines), as S1e and S1f arms expect."""
    def line(mid):
        v = results[mid]
        return json.dumps([mid, 'error', v.code, v.message] if isinstance(v, Failure) else [mid, v], ensure_ascii=False)
    return '\n'.join(line(mid) for mid in (results if ids is None else ids))


def decode_oracle(arm, n=8, encode=None, head=''):
    """Packet of the arm builds; the oracle answer (1f lines for S1e/S1f, 1g lines otherwise, head first) decodes n/n."""
    system, user, dec, native = live11.ARMS[arm](n)
    assert system and user and native is True
    jobs = X.V.jobs('materials', n)
    reply = head + (encode or encode_reply)({j: X.oracle(j[0], int(j[1:])) for j in jobs})
    flat = dec(reply)
    assert sum(g and X.check(j, v, native) for (g, v), j in zip(flat, jobs)) == n
    return jobs, dec


for _arm in ('S1e', 'S1f'):
    @check(f'live11 arm {_arm}: packet builds, oracle answer in 1f form decodes 8/8')
    def _(arm=_arm):
        decode_oracle(arm, encode=encode_1f)


@check('live11 arm S1f: a job-error line decodes as not ok; a rejected reply raises; 1g lines and blank lines reject')
def _():
    jobs, dec = decode_oracle('S1f', encode=encode_1f)
    values = {j: X.oracle(j[0], int(j[1:])) for j in jobs[1:]} | {jobs[0]: Failure('missing_data', 'x')}
    assert [g for g, _ in dec(encode_1f(values, ids=jobs))] == [False] + [True] * 7
    good = encode_1f({j: X.oracle(j[0], int(j[1:])) for j in jobs})
    for bad in ('not json', encode_reply({j: 1 for j in jobs}), good.replace('\n', '\n\n', 1), 'OZ/1g\n' + good):
        try:
            dec(bad)
        except ValueError:
            continue
        raise AssertionError(f'rejected reply did not raise: {bad[:40]!r}')


@check('live11 arm S1f: 1f system text and body v "1f"; arms C, G, H carry the 1g body')
def _():
    import oz_batch
    system, user, _, _ = live11.ARMS['S1f'](8)
    assert system.startswith('You execute OZ/1f.\n\n') and system.endswith('Escape newlines inside JSON strings.')
    body = json.loads(user)
    assert list(body) == ['v', 'goal', 'ops', 'refs', 'jobs'] and body['v'] == '1f'
    for arm in ('C', 'G', 'H'):
        system, user, _, _ = live11.ARMS[arm](8)
        assert json.loads(user)['v'] == '1g' and system.startswith('You execute OZ/1g.\n\n'), arm
    assert live11.ARMS['C'](8)[0] == oz_batch.SYSTEM
    assert live11.ARMS['G'](8)[0] == live11.G_SYSTEM and live11.G_SYSTEM != oz_batch.SYSTEM
    h = live11.ARMS['H'](8)[0]
    assert h == oz_batch.SYSTEM.replace(live11.H_FROM, live11.H_TO) and h != oz_batch.SYSTEM


for _arm in ('C', 'G', 'H'):
    @check(f'live11 arm {_arm}: packet builds, oracle answer in 1g form decodes 64/64')
    def _(arm=_arm):
        decode_oracle(arm, 64, head='OZ/1g\n' if arm == 'H' else '')


@check('live11 arm C and G: blank lines are skipped, CRLF works, a job-error line is not ok, bad replies raise')
def _():
    for arm in ('C', 'G'):
        jobs, dec = decode_oracle(arm, 8)
        values = {j: X.oracle(j[0], int(j[1:])) for j in jobs}
        good = encode_reply(values)
        assert all(g for g, _ in dec('\n \t\n' + good.replace('\n', '\n\n') + '\n\n'))
        assert all(g for g, _ in dec(good.replace('\n', '\r\n') + '\r\n'))
        failed = encode_reply(values | {jobs[0]: Failure('missing_data', 'x')}, ids=jobs)
        assert [g for g, _ in dec(failed)] == [False] + [True] * 7
        old_form = encode_1f(values)
        for bad in ('not json', '', '\n \n', old_form, 'OZ/1g\n' + good, good + '\n' + good.splitlines()[0],
                    good + '\nDone.', '```\n' + good + '\n```'):
            try:
                dec(bad)
            except ValueError:
                continue
            raise AssertionError(f'{arm}: rejected reply did not raise: {bad[:40]!r}')


@check('live11 arm H: the first nonblank line must be exactly OZ/1g; the rest follows the C rules')
def _():
    jobs, dec = decode_oracle('H', 8, head='OZ/1g\n')
    values = {j: X.oracle(j[0], int(j[1:])) for j in jobs}
    good = encode_reply(values)
    assert all(g for g, _ in dec('\n \t\nOZ/1g\r\n' + good + '\n'))
    assert all(g for g, _ in dec('OZ/1g\n\n' + good.replace('\n', '\n\n')))
    failed = encode_reply(values | {jobs[0]: Failure('conflict', 'x')}, ids=jobs)
    assert [g for g, _ in dec('OZ/1g\n' + failed)] == [False] + [True] * 7
    assert all(g for g, _ in dec('OZ/1g \t\n' + good))  # trailing SP/TAB on the header line is stripped, as in live11
    for bad in (good, '', 'OZ/1g', 'oz/1g\n' + good, 'OZ/1f\n' + good, '```\nOZ/1g\n' + good + '```',
                'OZ/1g\nOZ/1g\n' + good, 'OZ/1g\n' + good + '\n' + good.splitlines()[0], 'Here:\nOZ/1g\n' + good,
                '\xa0OZ/1g\n' + good, 'OZ/1g\n' + encode_1f(values)):
        try:
            dec(bad)
        except ValueError:
            continue
        raise AssertionError(f'H: rejected reply did not raise: {bad[:40]!r}')


@check('oldwire.judge_s1f follows the 1f rules: blank line, wrong shape and duplicate ID reject; errors are not values')
def _():
    from oldwire import judge_s1f
    ids = ('a', 'b')
    assert judge_s1f('["a",1]\n["b",2]\n', ids) == (True, {'a': 1, 'b': 2})
    assert judge_s1f('["b","error","conflict","x"]\r\n["a",null]', ids) == (True, {'a': None})
    for bad in ('', '\n', '["a",1]\n\n["b",2]', '["a",1]\n  \n["b",2]', '{"a":1}\n{"b":2}', '["a",1]', '["a",1]\n["a",1]\n["b",2]',
                '["a",1,2]\n["b",2]', '["a","error","timeout","x"]\n["b",2]', '["a","error","conflict"," "]\n["b",2]',
                '["a",1]\n["b",2]\n\n', '["a",NaN]\n["b",2]', '["a",{"k":1,"k":2}]\n["b",2]'):
        assert judge_s1f(bad, ids) == (False, {}), bad


@check('live11 retired decoders (S1c index lines, S1d id lines) still decode oracle answers')
def _():
    jobs = X.V.jobs('materials', 8)
    want = [X.oracle(j[0], int(j[1:])) for j in jobs]
    flat = live11.jsonl_flat('\n'.join(json.dumps([i, v]) for i, v in enumerate(want)), 8)
    assert [v for _, v in flat] == want and all(g for g, _ in flat)
    flat = live11.stage1d_flat('\n'.join(json.dumps([j, v]) for j, v in zip(jobs, want)), jobs)
    assert [v for _, v in flat] == want


@check('hetero1g: five 64-job single-family packets validate; oracle judges 64/64, one wrong value 63/64, P5 success line is wrong')
def _():
    import hetero1g as HG, oz_batch
    first = {1: lambda v: v == [], 2: lambda v: not isinstance(v, (list, dict)), 3: lambda v: isinstance(v, dict),
             4: lambda v: isinstance(v, list) and v and all(isinstance(x, list) for x in v)}
    for k in range(1, 6):
        body, ids, expected = HG.packet(k)
        assert (body, ids, expected) == HG.packet(k) and len(ids) == 64 and set(ids) == set(expected)
        oz_batch.validate_packet(json.loads(body))
        if k < 5:
            assert all(t == 'ok' and first[k](v) for t, v in expected.values()), k
        else:
            assert sorted(v for _, v in expected.values()) == sorted(c for c in ('missing_data', 'invalid_data', 'conflict', 'unsupported') for _ in range(16))
        values = {i: Failure(expected[i][1], 'x') if k == 5 else expected[i][1] for i in ids}
        for header in (True, False):
            head = 'OZ/1g\n' if header else ''
            assert HG.judge(head + encode_reply(values, ids), ids, expected, header) == (True, 64, '')
            bad = dict(values); bad[ids[0]] = 12345 if k == 5 else ('x' if k != 2 else [1])
            assert HG.judge(head + encode_reply(bad, ids), ids, expected, header) == (True, 63, '')
            assert HG.judge(encode_reply(values, ids) if header else 'OZ/1g\n' + encode_reply(values, ids), ids, expected, header)[:2] == (False, 0)
    assert {'error', 'id'} <= {i for k in range(1, 6) for i in HG.packet(k)[1]}
    ids = HG.packet(5)[1]
    wrong = {i: Failure(HG.packet(5)[2][i][1], 'x') for i in ids} | {ids[0]: Failure('conflict' if HG.packet(5)[2][ids[0]][1] != 'conflict' else 'unsupported', 'x')}
    assert HG.judge(encode_reply(wrong, ids), ids, HG.packet(5)[2], False)[:2] == (True, 63)
    assert not HG.same(True, 1) and not HG.same(1, True) and HG.same(1, 1.0) and not HG.same(0, False) and not HG.same([1], [True])
    assert not HG.same({'a': 1}, {'a': 1, 'b': 2}) and not HG.same('1', 1) and HG.same({'a': [1.5]}, {'a': [1.5]})


print(f'{sum(RESULTS)}/{len(RESULTS)} checks passed')
sys.exit(0 if all(RESULTS) else 1)
