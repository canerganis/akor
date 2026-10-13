"""Score the stage-1g Luna cell (arm H, 10 prompts) against the stored oracles.

    python bench/codex_kit_1g/score.py bench/codex_kit_1g/results_gpt-6-luna_medium.jsonl
Replies pasted by hand also work: save each as replies/<prompt file name> and run
    python bench/codex_kit_1g/score.py --replies bench/codex_kit_1g/replies
(usage is then unknown and only correctness is scored).

Judging equals bench/live/run1g.py (standard: product parser, then value == oracle) and bench/live/hetero1g.judge
(typed JSON equality, job failures by code). The first nonblank line must be exactly OZ/1g; nothing is repaired.
Needs only the standard library and oz_reply.py of this repository.
"""
import json, statistics as st, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import oz_reply  # noqa: E402

KIT = Path(__file__).parent
HEADER = 'OZ/1g'
N = 64


def flat(reply, ids):
    """[(ok, value)] in job order, or ValueError. The product parser decides acceptance."""
    lines = reply.split('\n')
    first = next((k for k, line in enumerate(lines) if line.removesuffix('\r').strip(' \t')), None)
    if first is None or lines[first].removesuffix('\r').rstrip(' \t') != HEADER:
        raise ValueError(f'first nonblank line is not {HEADER}')
    p = oz_reply.parse_reply(reply, ids)   # the product parser (profile oz1g-header) checks the header itself
    if p.rejection:
        raise ValueError(f'{p.rejection}: {p.violations[:2]}')
    return [(i in p.accepted, p.accepted.get(i, p.failed.get(i))) for i in ids]


def same(a, b):
    """JSON equality with types: bool is not a number, 1 equals 1.0, objects ignore key order (hetero1g.same)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def score(item, text):
    """(accepted, correct jobs of 64)."""
    oracle = json.loads((KIT / 'oracles' / item['file'].replace('.txt', '.json')).read_text('utf-8'))
    ids = tuple(oracle['jobs'])
    try:
        got = flat(text, ids)
    except Exception:  # noqa: BLE001
        return False, 0
    if oracle['kind'] == 'std':
        return True, sum(g and v == want for (g, v), want in zip(got, oracle['oracle']))
    correct = 0
    for jid, (good, value) in zip(ids, got):
        kind, want = oracle['expected'][jid]
        correct += same(value, want) if kind == 'ok' and good else (kind == 'error' and not good and value[0] == want)
    return True, correct


def main():
    args = sys.argv[1:]
    index = {i['file']: i for i in json.loads((KIT / 'index.json').read_text('utf-8'))}
    if args[:1] == ['--replies']:
        rows = [{**index[f.name], 'text': f.read_text('utf-8'), 'usage': None, 'wall_s': None}
                for f in sorted(Path(args[1]).glob('*.txt'))]
    else:
        rows = [json.loads(l) for l in Path(args[0]).read_text('utf-8').splitlines()]
    rows.sort(key=lambda r: r['file'])
    print('prompt | accepted | correct | passed | input | output | seconds')
    passed = 0
    for r in rows:
        ok, correct = score(r, r['text'])
        good = ok and correct == N
        passed += good
        u = r.get('usage') or {}
        print(f"{r['file']} | {'yes' if ok else 'no'} | {correct}/{N} | {'PASS' if good else 'FAIL'} | "
              f"{u.get('input_tokens', '-')} | {u.get('output_tokens', '-')} | {r['wall_s'] if r.get('wall_s') is not None else '-'}")
    usage = [r['usage'] for r in rows if r.get('usage')]
    if usage:
        print(f"mean input {st.mean(x['input_tokens'] for x in usage):.0f}, mean output {st.mean(x['output_tokens'] for x in usage):.0f}, "
              f"median seconds {st.median(r['wall_s'] for r in rows):.1f}")
    print(f'passed {passed}/{len(index)} (called {len(rows)}); gate for this cell: {len(index)}/{len(index)}')
    print('Note: Codex CLI adds ~24,500 fixed input tokens per call; the reply must be the OZ/1g line and JSON records only.')


if __name__ == '__main__':
    main()
