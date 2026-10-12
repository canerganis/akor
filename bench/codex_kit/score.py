"""Score Codex replies against the oracles and print the same table as the Claude runs.

    python bench/codex_kit/score.py bench/codex_kit/results_gpt-6-luna.jsonl
Replies pasted by hand also work: save each as replies/<prompt file name> and run
    python bench/codex_kit/score.py --replies bench/codex_kit/replies
(usage is then unknown and only correctness is scored).
"""
import json, statistics as st, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from oz_reply import parse_reply  # noqa: E402  (the product parser: strict JSONL, per-index acceptance)

KIT = Path(__file__).parent


def same(a, b):
    if isinstance(a, str) and not isinstance(b, str):
        try:
            a = json.loads(a.strip())
        except ValueError:
            return a.strip() == str(b)
    return a == b


def score(item, text):
    oracle = json.loads((KIT / 'oracles' / f"rep{item['rep']}_n{item['n']}.json").read_text('utf-8'))['oracle']
    n = item['n']
    try:
        if item['arm'] == '0.8-exec':
            rows = json.loads(text)['results']
            got = {r[0]: r[2] for r in rows if isinstance(r, list) and len(r) == 3 and r[1] == 0}
            values = [got.get(f'ma_{i + 1:02d}') for i in range(n)]
            ok = [v is not None for v in values]
        else:
            ids = json.loads((KIT / 'oracles' / f"rep{item['rep']}_n{item['n']}.json").read_text('utf-8'))['jobs']
            parsed = parse_reply(text, ids, 'jsonl')
            if parsed.rejection:
                return False, 0
            ok = [True] * n
            values = [parsed.accepted[i] for i in ids]
    except (ValueError, KeyError, TypeError):
        return False, 0
    return True, sum(g and same(v, want) for g, v, want in zip(ok, values, oracle))


def main():
    args = sys.argv[1:]
    if args[:1] == ['--replies']:
        rows = []
        index = {i['file']: i for i in json.loads((KIT / 'index.json').read_text('utf-8'))}
        for f in sorted(Path(args[1]).glob('*.txt')):
            rows.append({**index[f.name], 'text': f.read_text('utf-8'), 'usage': None, 'wall_s': None})
    else:
        rows = [json.loads(l) for l in Path(args[0]).read_text('utf-8').splitlines()]
    print('n | arm | valid | correct | input | output | total | vs 0.8 | median s')
    for n in (32, 64):
        base = None
        for arm in ('0.8-exec', 'S1d', 'S1c'):
            v = [r for r in rows if r['n'] == n and r['arm'] == arm]
            if not v:
                continue
            s = [score(r, r['text']) for r in v]
            u = [r['usage'] for r in v if r.get('usage')]
            if u:
                i = st.mean(x['input_tokens'] for x in u); o = st.mean(x['output_tokens'] for x in u); t = i + o
                base = t if arm == '0.8-exec' else base
                cost = f"{i:.0f} | {o:.0f} | {t:.0f} | {(t / base - 1) if base else 0:+.0%}"
                med = f"{st.median(r['wall_s'] for r in v):.1f}"
            else:
                cost, med = '- | - | - | -', '-'
            print(f"{n} | {arm} | {sum(x[0] for x in s)}/{len(v)} | {sum(x[1] for x in s)}/{n * len(v)} | {cost} | {med}")
    print('Note: Codex CLI adds ~24,500 fixed input tokens per call; compare outputs and correctness first.')


if __name__ == '__main__':
    main()
