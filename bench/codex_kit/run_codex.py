"""Send every prompt in prompts/ to `codex exec` and record the reply and usage.

Run from the repository root:
    python bench/codex_kit/run_codex.py --model gpt-6-luna --effort medium
Results go to bench/codex_kit/results_<model>.jsonl (one line per call, resumable).
"""
import argparse, json, random, shutil, subprocess, time
from pathlib import Path

KIT = Path(__file__).parent


def call(prompt, model, effort):
    start = time.monotonic()
    proc = subprocess.run([shutil.which('codex'), 'exec', '-m', model, '-c', f'model_reasoning_effort="{effort}"',
                           '-s', 'read-only', '--skip-git-repo-check', '--ephemeral', '--json', '-'],
                          input=prompt, capture_output=True, text=True, encoding='utf-8', timeout=900)
    wall = round(time.monotonic() - start, 2)
    events = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith('{')]
    texts = [e['item']['text'] for e in events
             if e.get('type') == 'item.completed' and e['item'].get('type') == 'agent_message']
    usage = [e['usage'] for e in events if e.get('type') == 'turn.completed']
    return {'text': texts[-1] if texts else '', 'usage': usage[-1] if usage else None, 'wall_s': wall,
            'exit_code': proc.returncode}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', required=True)
    ap.add_argument('--effort', default='medium')
    args = ap.parse_args()
    out = KIT / f'results_{args.model}.jsonl'
    done = {json.loads(l)['file'] for l in out.read_text('utf-8').splitlines()} if out.exists() else set()
    index = json.loads((KIT / 'index.json').read_text('utf-8'))
    random.Random(11).shuffle(index)            # interleave arms so drift hits both
    for item in index:
        if item['file'] in done:
            continue
        prompt = (KIT / 'prompts' / item['file']).read_text('utf-8')
        rec = {**item, 'model': args.model, 'effort': args.effort, **call(prompt, args.model, args.effort)}
        with out.open('a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        u = rec['usage'] or {}
        print(item['file'], 'in', u.get('input_tokens'), 'out', u.get('output_tokens'), f"{rec['wall_s']}s", flush=True)


if __name__ == '__main__':
    main()
