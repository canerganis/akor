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


def decode_oracle(arm, n=8):
    system, user, dec, native = live11.ARMS[arm](n)
    assert system and user and native is True
    jobs = X.V.jobs('materials', n)
    reply = encode_reply({j: X.oracle(j[0], int(j[1:])) for j in jobs})
    flat = dec(reply)
    assert sum(g and X.check(j, v, native) for (g, v), j in zip(flat, jobs)) == n
    return jobs, dec


for _arm in ('S1e', 'S1f'):
    @check(f'live11 arm {_arm}: packet builds, oracle answer decodes 8/8')
    def _(arm=_arm):
        decode_oracle(arm)


@check('live11 arm S1f: a job-error line decodes as not ok; a rejected reply raises')
def _():
    jobs, dec = decode_oracle('S1f')
    reply = encode_reply({j: X.oracle(j[0], int(j[1:])) for j in jobs[1:]} | {jobs[0]: Failure('missing_data', 'x')},
                         ids=jobs)
    assert [g for g, _ in dec(reply)] == [False] + [True] * 7
    try:
        dec('not json')
    except ValueError:
        return
    raise AssertionError('rejected reply did not raise')


@check('live11 retired decoders (S1c index lines, S1d id lines) still decode oracle answers')
def _():
    jobs = X.V.jobs('materials', 8)
    want = [X.oracle(j[0], int(j[1:])) for j in jobs]
    flat = live11.jsonl_flat('\n'.join(json.dumps([i, v]) for i, v in enumerate(want)), 8)
    assert [v for _, v in flat] == want and all(g for g, _ in flat)
    flat = live11.stage1d_flat('\n'.join(json.dumps([j, v]) for j, v in zip(jobs, want)), jobs)
    assert [v for _, v in flat] == want


print(f'{sum(RESULTS)}/{len(RESULTS)} checks passed')
sys.exit(0 if all(RESULTS) else 1)
