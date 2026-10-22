"""Write the pilot's H workload for one seed as an `oz do` request (oz.do/1) and print it.

Usage: python bench/live/do_request.py SEED N MODEL > request.json
The request carries the same goal, operation texts, reference texts and job IDs that arm H sends, so a run through
`oz do` can be compared with the pilot directly.
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import live11 as M


def request(seed, n, model):
    M.use_records(M.make_records(seed))
    _, user, _, _ = M.ARMS['H'](n)
    body = json.loads(user)
    jobs = [[job, f'op{block[0]}', f'r{ref}'] for block in body['jobs'] for job, ref in block[1:]]
    order = M.X.V.jobs('materials', n)
    jobs.sort(key=lambda j: order.index(j[0]))
    return {'request_id': f'pilot-{seed}-{n}', 'model': model, 'goal': body['goal'],
            'ops': {f'op{i}': text for i, text in enumerate(body['ops'])},
            'refs': {f'r{i}': text for i, text in enumerate(body['refs'])}, 'jobs': jobs}


if __name__ == '__main__':
    print(json.dumps(request(int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]), ensure_ascii=False))
