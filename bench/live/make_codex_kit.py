"""Write a self-contained Codex measurement kit: exact prompts, a runner and a scorer.

Same workload as the Claude runs (16 generated materials records x 4 operations, fresh records per rep,
Decimal oracles), arms 0.8-exec and S1c (current wire), sizes 32 and 64, reps 0..2.
Codex has no separate system field, so the OZ system text is placed before the body under fixed headings.
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, '.')
import live11 as Z

OUT = Path(sys.argv[1])
(OUT / 'prompts').mkdir(parents=True, exist_ok=True)
(OUT / 'oracles').mkdir(exist_ok=True)
index = []
for rep in range(3):
    Z.use_records(Z.make_records(1000 + rep))
    for n in (32, 64):
        jobs = Z.X.V.jobs('materials', n)
        oracle = [Z.X.oracle(j[0], int(j[1:])) for j in jobs]
        name = f'rep{rep}_n{n}'
        (OUT / 'oracles' / f'{name}.json').write_text(json.dumps({'jobs': jobs, 'oracle': oracle,
                                                                  'records': Z.X.C}, ensure_ascii=False), 'utf-8')
        for arm in ('0.8-exec', 'S1c'):
            system, user, _, _ = Z.ARMS[arm](n)
            text = user if system is None else f'SYSTEM RULES:\n{system}\n\nINPUT:\n{user}'
            fn = f'{name}_{arm}.txt'
            (OUT / 'prompts' / fn).write_text(text, 'utf-8', newline='\n')
            index.append({'file': fn, 'rep': rep, 'n': n, 'arm': arm, 'o200k': Z.L.count(text)})
(OUT / 'index.json').write_text(json.dumps(index, indent=1), 'utf-8')
print(len(index), 'prompts written to', OUT)
