"""Write the prompts, oracles and index of the stage-1g Luna cell (docs/design/stage-1g-final-decision.md, stage D:
Luna medium-64, 5+5, arm H only). Needs the .venv python (live11 imports tiktoken). Deterministic; rerun to verify.

    .venv/Scripts/python bench/codex_kit_1g/make_prompts.py
Standard packets: 64 jobs, data seeds 2005-2009, built as bench/live/run1g.py does. Heterogeneous: hetero1g.packet(1..5).
Codex has no system field, so the H system text goes under SYSTEM RULES: and the packet body under INPUT:.
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bench' / 'live')); sys.path.insert(0, str(ROOT))
import live11 as M
import hetero1g as HG

KIT = Path(__file__).parent
N = 64


def build():
    """[(name, prompt text, oracle, meta)] for the ten prompts."""
    out = []

    def put(name, user, oracle, **meta):
        text = 'SYSTEM RULES:\n' + M.H_SYSTEM + '\n\nINPUT:\n' + user
        out.append((name, text, oracle, {'file': f'{name}.txt', 'arm': 'H', 'n': N, **meta}))

    for seed in range(2005, 2010):
        M.use_records(M.make_records(seed))
        system, user, _, native = M.ARMS['H'](N)
        assert system == M.H_SYSTEM and native is True
        jobs = M.X.V.jobs('materials', N)
        put(f'std_{seed}', user, {'kind': 'std', 'jobs': jobs, 'oracle': [M.X.oracle(j[0], int(j[1:])) for j in jobs]},
            kind='std', seed=seed)
    for k in range(1, 6):
        body, ids, expected = HG.packet(k)
        put(f'het_p{k}', body, {'kind': 'het', 'jobs': list(ids), 'expected': {i: list(v) for i, v in expected.items()}},
            kind='het', packet=k, seed=3000 + k)
    return out


def main():
    (KIT / 'prompts').mkdir(exist_ok=True)
    (KIT / 'oracles').mkdir(exist_ok=True)
    index = []
    for name, text, oracle, meta in build():
        (KIT / 'prompts' / f'{name}.txt').write_text(text, 'utf-8', newline='\n')
        (KIT / 'oracles' / f'{name}.json').write_text(json.dumps(oracle, ensure_ascii=False), 'utf-8', newline='\n')
        index.append({**meta, 'o200k': M.L.count(text)})
    (KIT / 'index.json').write_text(json.dumps(index, indent=1), 'utf-8', newline='\n')
    print(len(index), 'prompts written to', KIT)
    for m in index:
        print(m['file'], m['o200k'])


if __name__ == '__main__':
    main()
