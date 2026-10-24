"""Frozen datasets of the oz map kill pilot (joint record 3; amendment 2 A2.3). Standard library, deterministic.

Seed 20261024. Every random choice comes from random.Random(sub_seed(...)), sub_seed = the first 16 hex digits of
SHA256(canonical([20261024, *parts])), so each wave, producer, operation and admission set has its own fresh stream.

Materials (operations e, b, m, v; goal and op texts read verbatim from bench/live/live2.py MAT_GOAL and MAT_D):
  cold wave  4 producers x 64 jobs (16 per operation), one fresh record per job
  warm wave  4 producers x 64 fresh jobs, same plan, disjoint texts
  Each producer's 16 jobs per operation follow one predetermined plan: 5 plain, 4 strictly inside the acceptance
  interval, 1 inclusive endpoint from inside, 1 endpoint from outside, 1 zero uncertainty, 1 unknown uncertainty,
  1 unknown method or basis, 1 other spelling (12.500 mm, 0.020 mm, n=03), 1 reordered fields; two of the 16 carry
  a terminal newline (one LF, one CRLF). Boundary and drift tags are recorded per dataset id (TAGS); evaluation
  labels are never computed here (gold stays with oracle.py and score.py).
Admission (per materials operation): exactly 64 cases, 48 representative (the same plan, three times) and 16
  predetermined challenges, disjoint from every evaluation and telemetry text, labeled by oracle.py.
Telemetry: two fresh one-job materials records for the paired Codex telemetry calls.
BoolQ: bench/ozmap/data/boolq-superglue-val.jsonl, the BoolQ validation split as distributed by SuperGLUE
  (BOOLQ_SOURCE; the Google bucket returned 403 and the owner approved this source). Fields idx, question, passage,
  label (JSON boolean; true -> "yes", false -> "no"). The file must hash to BOOLQ_SHA256. A seeded sample of 256
  (4 x 64) evaluation examples plus 64 disjoint admission examples (labels are the dataset's own); job text = passage +
  question in one record. When the file is absent BoolQ is unavailable.

Jobs are exactly {key, op, text, dataset_id} (the host's intake schema).
"""
import ast
import hashlib
import json
from decimal import Decimal
from pathlib import Path
import random

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
LIVE2 = REPO / 'bench' / 'live' / 'live2.py'
BOOLQ_FILE = HERE / 'data' / 'boolq-superglue-val.jsonl'
BOOLQ_SOURCE = {'url': 'https://dl.fbaipublicfiles.com/glue/superglue/data/v2/BoolQ.zip',
                'zip_sha256': '853fbe7922f70c59629f06a39e8d9ca440c3d740e760fd3b87a5ddf3dcba2436',
                'member': 'BoolQ/val.jsonl', 'file': 'bench/ozmap/data/boolq-superglue-val.jsonl',
                'file_sha256': '0c86a5045886e5795fe9052003873f7d94b88ed3028a33007c51d99e44fd66d9', 'lines': 3270,
                'fields': ['idx', 'question', 'passage', 'label'], 'approved_by': 'owner (Google bucket returned 403)'}
BOOLQ_SHA256 = BOOLQ_SOURCE['file_sha256']

SEED = 20261024
PRODUCERS = ('p0', 'p1', 'p2', 'p3')
OPS = ('e', 'b', 'm', 'v')
WAVES = ('cold', 'warm')
PER_PRODUCER = 64
PER_OP = PER_PRODUCER // len(OPS)
PLAN = (['plain'] * 5 + ['inside'] * 4
        + ['endpoint_in', 'endpoint_out', 'zero', 'unknown_u', 'unknown_mb', 'spelling', 'reorder'])
BOUNDARY = frozenset({'endpoint_in', 'endpoint_out', 'zero', 'unknown_u', 'unknown_mb', 'spelling', 'reorder',
                      'newline', 'three_decimals'})
FIELDS = ('length', 'uncertainty', 'n', 'method', 'basis', 'physical_validation')
METHODS = ('micrometer', 'caliper')
BASES = ('expanded', 'resolution', 'repeatability')
BOOLQ_OP = 'boolq'
BOOLQ_OP_TEXT = ('Answer the question using only the passage. Return the JSON string "yes" or "no".')
BOOLQ_GOAL = 'Answer each question from its own passage independently.'
BOOLQ_N = len(PRODUCERS) * PER_PRODUCER
ADMISSION_REPRESENTATIVE, ADMISSION_CHALLENGE = 48, 16


def canonical(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(x):
    return hashlib.sha256(canonical(x)).hexdigest()


def sub_seed(*parts):
    return int(hashlib.sha256(canonical([SEED, *parts])).hexdigest()[:16], 16)


def _live2_texts():
    """MAT_GOAL and MAT_D read from the source of bench/live/live2.py (literal assignments, never imported)."""
    tree = ast.parse(LIVE2.read_bytes())
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in ('MAT_GOAL', 'MAT_D'):
            found[node.targets[0].id] = ast.literal_eval(node.value)
    return found['MAT_GOAL'], {k: found['MAT_D'][k] for k in OPS}


MAT_GOAL, MAT_D = _live2_texts()


# ------------------------------------------------------------------------------------------------- records

def _d(x):
    return Decimal(x)


def _spell(x, places):
    return f'{x:.{places}f}'


def _places(*xs):
    """2 when every value is exact at two decimals, else 3."""
    return 2 if all(x == x.quantize(Decimal('0.01')) for x in xs) else 3


def _tie(x):
    s = x * 100
    return s - int(s) == Decimal('0.5')


def _record(rng, length, unc, *, places=None, n=None, method=None, basis=None, order=None, unc_text=None):
    """(text, tags) of one record. length/unc are Decimals (unc may be 'unknown'); unc_text overrides spelling."""
    tags = set()
    if unc == 'unknown':
        places = places or _places(length)
        u_text = 'unknown'
    else:
        places = places or _places(length, unc)
        u_text = unc_text or (_spell(unc, places) + ' mm')
    if places == 3:
        tags.add('three_decimals')
    values = {'length': _spell(length, places) + ' mm', 'uncertainty': u_text,
              'n': str(n if n is not None else rng.randint(1, 9)),
              'method': method or rng.choice(METHODS + ('unknown',) if rng.random() < 0.3 else METHODS),
              'basis': basis or (rng.choice(BASES) if rng.random() > 0.2 else 'unknown'),
              'physical_validation': 'not_claimed'}
    names = order or FIELDS
    return '; '.join(f'{k}={values[k]}' for k in names), tags


def _grid(lo, hi, step):
    out, x = [], _d(lo)
    while x <= _d(hi):
        out.append(x)
        x += _d(step)
    return out


L2 = _grid('12.40', '12.60', '0.01')
U2 = [_d('0.01'), _d('0.02'), _d('0.03')]


def _inside(rng):
    """Strictly inside: both ends strictly within [12.48, 12.52], no rounding tie at two decimals."""
    while True:
        if rng.random() < 0.5:
            unc = rng.choice([_d('0.00'), _d('0.01')])
            length = rng.choice([x for x in _grid('12.49', '12.51', '0.01')
                                 if _d('12.48') < x - unc and x + unc < _d('12.52')])
        else:
            unc = rng.choice(_grid('0.003', '0.015', '0.001'))
            length = rng.choice(_grid('12.485', '12.515', '0.001'))
        lo, hi = length - unc, length + unc
        if _d('12.48') < lo and hi < _d('12.52') and not _tie(lo) and not _tie(hi):
            return length, unc


ENDPOINT_IN = [('12.50', '0.02'), ('12.49', '0.01'), ('12.51', '0.01'), ('12.48', '0.00'), ('12.52', '0.00'),
               ('12.495', '0.015'), ('12.505', '0.015'), ('12.500', '0.020')]
ENDPOINT_OUT = [('12.47', '0.01'), ('12.53', '0.01'), ('12.46', '0.02'), ('12.54', '0.02'), ('12.50', '0.03'),
                ('12.49', '0.02'), ('12.51', '0.02'), ('12.475', '0.005')]


def _make(rng, category):
    """(text, tags) for one planned category."""
    if category == 'plain':
        text, tags = _record(rng, rng.choice(L2), rng.choice(U2))
    elif category == 'inside':
        length, unc = _inside(rng)
        text, tags = _record(rng, length, unc)
    elif category in ('endpoint_in', 'endpoint_out'):
        a, b = rng.choice(ENDPOINT_IN if category == 'endpoint_in' else ENDPOINT_OUT)
        places = max(len(a.split('.')[1]), len(b.split('.')[1]))
        text, tags = _record(rng, _d(a), _d(b), places=places)
    elif category == 'zero':
        spelling = rng.choice(['0 mm', '0.00 mm', '0.000 mm'])
        text, tags = _record(rng, rng.choice(_grid('12.45', '12.55', '0.01')), _d('0'), places=2,
                             unc_text=spelling)
    elif category == 'unknown_u':
        text, tags = _record(rng, rng.choice(L2), 'unknown')
    elif category == 'unknown_mb':
        pick = rng.choice([('unknown', None), (None, 'unknown'), ('unknown', 'unknown')])
        text, tags = _record(rng, rng.choice(L2), rng.choice(U2), method=pick[0] or rng.choice(METHODS),
                             basis=pick[1] or rng.choice(BASES))
    elif category == 'spelling':
        n = rng.randint(1, 9)
        text, tags = _record(rng, rng.choice(_grid('12.46', '12.54', '0.01')), rng.choice(U2), places=3,
                             n=f'0{n}')
    elif category == 'reorder':
        order = list(FIELDS)
        while tuple(order) == FIELDS:
            rng.shuffle(order)
        text, tags = _record(rng, rng.choice(L2), rng.choice(U2), order=order)
    else:
        raise ValueError(category)
    tags.add(category)
    return text, tags


def _unique(rng, category, taken):
    for _ in range(10000):
        text, tags = _make(rng, category)
        if text not in taken:
            taken.add(text)
            return text, tags
    raise RuntimeError('cannot draw a fresh record for ' + category)


def _plan_jobs(rng, taken):
    """16 (text, tags) for one producer and operation: the plan, shuffled, two with a terminal newline."""
    plan = list(PLAN)
    rng.shuffle(plan)
    out = [_unique(rng, c, taken) for c in plan]
    lf, crlf = rng.sample(range(len(out)), 2)
    for i, ending in ((lf, '\n'), (crlf, '\r\n')):
        text, tags = out[i]
        out[i] = (text + ending, tags | {'newline'})
    return out


# ----------------------------------------------------------------------------------------------- admission

CHALLENGES = [
    # (category tag, length, uncertainty, kwargs) - predetermined before any call
    ('endpoint_in', '12.50', '0.02', {}), ('endpoint_in', '12.49', '0.01', {}), ('endpoint_in', '12.51', '0.01', {}),
    ('zero', '12.48', '0', {'unc_text': '0 mm', 'places': 2}), ('zero', '12.52', '0', {'unc_text': '0.00 mm', 'places': 2}),
    ('endpoint_out', '12.47', '0.01', {}), ('endpoint_out', '12.53', '0.01', {}),
    ('zero', '12.500', '0', {'unc_text': '0.000 mm', 'places': 3}),
    ('unknown_u', '12.50', 'unknown', {}), ('unknown_all', '12.51', 'unknown', {'method': 'unknown', 'basis': 'unknown'}),
    ('spelling', '12.500', '0.020', {'places': 3, 'n': '03'}),
    ('reorder', '12.50', '0.02', {'order': ['uncertainty', 'basis', 'length', 'method', 'physical_validation', 'n']}),
    ('newline_lf', '12.49', '0.02', {}), ('newline_crlf', '12.50', '0.01', {}),
    ('three_decimals', '12.503', '0.011', {}), ('endpoint_in', '12.495', '0.015', {}),
]


def _challenges(rng, taken):
    out = []
    for tag, a, b, kw in CHALLENGES:
        for _ in range(10000):
            unc = 'unknown' if b == 'unknown' else _d(b)
            text, tags = _record(rng, _d(a), unc, **kw)
            if tag == 'newline_lf':
                text += '\n'
            elif tag == 'newline_crlf':
                text += '\r\n'
            if text not in taken and text.rstrip('\r\n') not in taken:
                taken.add(text)
                taken.add(text.rstrip('\r\n'))
                out.append((text, tags | {tag}))
                break
        else:
            raise RuntimeError('cannot draw challenge ' + tag)
    return out


def admission_texts(taken=None):
    """{op: [(case id, text, partition, tags)]}: 48 representative + 16 challenge per materials operation."""
    taken = set() if taken is None else taken
    out = {}
    for op in OPS:
        rng = random.Random(sub_seed('admission', op))
        rows = []
        for rep in range(3):
            for text, tags in _plan_jobs(rng, taken):
                rows.append((f'adm-{op}-r{len(rows):02d}', text, 'representative', sorted(tags)))
        for text, tags in _challenges(rng, taken):
            rows.append((f'adm-{op}-c{len(rows) - ADMISSION_REPRESENTATIVE:02d}', text, 'challenge', sorted(tags)))
        out[op] = rows
    return out


def admission_cases(oracle):
    """{op: 64 registry cases} labeled by the independent oracle (oracle.label)."""
    return {op: [{'id': cid, 'text': text, 'partition': part, 'expected': oracle.label(op, text)}
                 for cid, text, part, _ in rows] for op, rows in admission_texts().items()}


# ------------------------------------------------------------------------------------------------- build

def _resolved(text):
    return text[:-2] if text.endswith('\r\n') else text[:-1] if text.endswith('\n') else text


def materials():
    """{"waves": {wave: {producer: [jobs]}}, "tags": {dataset id: [tags]}, "telemetry": [jobs],
    "admission_texts": {op: [...]}}. Deterministic; every text (raw and resolved) is distinct across all of them."""
    taken = set()
    adm = admission_texts(taken)
    for rows in adm.values():
        for _, text, _, _ in rows:
            taken.add(_resolved(text))
    waves, tags = {}, {}
    for wave in WAVES:
        waves[wave] = {}
        for p in PRODUCERS:
            jobs = []
            for op in OPS:
                rng = random.Random(sub_seed('materials', wave, p, op))
                for i, (text, t) in enumerate(_plan_jobs(rng, taken)):
                    taken.add(_resolved(text))
                    did = f'mat-{wave}-{p}-{op}-{i:02d}'
                    jobs.append({'key': f'{wave[0]}{op}{i:02d}', 'op': op, 'text': text, 'dataset_id': did})
                    tags[did] = sorted(t)
            # submission order within a producer: a seeded interleaving of the four operations
            random.Random(sub_seed('order', wave, p)).shuffle(jobs)
            waves[wave][p] = jobs
    rng = random.Random(sub_seed('telemetry'))
    telemetry = []
    for i in range(2):
        text, t = _unique(rng, 'plain', taken)
        telemetry.append({'key': f't{i}', 'op': 'v', 'text': text, 'dataset_id': f'mat-telemetry-{i}'})
    return {'waves': waves, 'tags': tags, 'telemetry': telemetry, 'admission_texts': adm}


def boolq(path=BOOLQ_FILE, expected_sha256=None):
    """{"available": False, "reason"} or {"available": True, "sha256", "waves": {"cold": {producer: [jobs]}},
    "labels": {dataset id: bool} (scoring only), "admission": [(id, text, partition, answer)]}."""
    path = Path(path)
    if not path.is_file():
        return {'available': False, 'reason': f'{path.relative_to(REPO).as_posix() if path.is_relative_to(REPO) else path} '
                                              'is absent; BoolQ cells are unavailable'}
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is None and path.resolve() == BOOLQ_FILE.resolve():
        expected_sha256 = BOOLQ_SHA256
    if expected_sha256 is not None and sha != expected_sha256:
        raise ValueError(f'{path.name} hashes to {sha}, not the recorded {expected_sha256}')
    rows = []
    for line in raw.decode('utf-8').splitlines():
        if line.strip():
            r = json.loads(line)
            if not isinstance(r.get('question'), str) or not isinstance(r.get('passage'), str) \
                    or type(r.get('label')) is not bool or type(r.get('idx')) is not int:
                raise ValueError('BoolQ rows need idx (int), question (str), passage (str), label (bool)')
            rows.append(r)
    if len(rows) < BOOLQ_N + 64:
        raise ValueError(f'{path.name} has {len(rows)} rows; the pilot needs at least {BOOLQ_N + 64}')
    rng = random.Random(sub_seed('boolq'))
    picked = rng.sample(range(len(rows)), BOOLQ_N + 64)
    texts, labels, waves = set(), {}, {'cold': {p: [] for p in PRODUCERS}}

    def text_of(r):
        return f"passage: {r['passage']}\nquestion: {r['question']}"

    seen = set()
    picked = [i for i in picked if not (text_of(rows[i]) in seen or seen.add(text_of(rows[i])))]
    for n, i in enumerate(picked[:BOOLQ_N]):
        p = PRODUCERS[n // PER_PRODUCER]
        did = f'boolq-val-{rows[i]["idx"]}'
        waves['cold'][p].append({'key': f'q{n % PER_PRODUCER:02d}', 'op': BOOLQ_OP, 'text': text_of(rows[i]),
                                 'dataset_id': did})
        labels[did] = rows[i]['label']
        texts.add(text_of(rows[i]))
    if len(picked) < BOOLQ_N + 64:
        raise ValueError('too few distinct BoolQ texts after removing duplicates')
    # Admission is separated from evaluation by passage, not only by text (council 3 close, B12): BoolQ asks several
    # questions about one passage, so an admission row whose passage is also an evaluation passage is replaced by a
    # seeded draw from the unpicked rows (the evaluation waves, and so their digest, are unchanged).
    eval_passages = {rows[i]['passage'] for i in picked[:BOOLQ_N]}
    spare = [i for i in range(len(rows)) if i not in set(picked)]
    random.Random(sub_seed('boolq-admission-spare')).shuffle(spare)
    chosen = []
    for i in picked[BOOLQ_N:BOOLQ_N + 64]:
        while rows[i]['passage'] in eval_passages or text_of(rows[i]) in {text_of(rows[j]) for j in chosen}:
            if not spare:
                raise ValueError('too few BoolQ rows with a passage outside the evaluation waves')
            i = spare.pop()
        chosen.append(i)
    admission = []
    for n, i in enumerate(chosen):
        part = 'representative' if n < ADMISSION_REPRESENTATIVE else 'challenge'
        admission.append((f'adm-boolq-{n:02d}', text_of(rows[i]), part, rows[i]['label']))
    return {'available': True, 'sha256': sha, 'source': BOOLQ_SOURCE, 'rows': len(rows), 'waves': waves,
            'labels': labels, 'admission': admission}


def boolq_standin():
    """Synthetic stand-ins with BoolQ's shape, for the dry run only when the real file is absent. Never scored as
    BoolQ evidence."""
    rng = random.Random(sub_seed('boolq-standin'))
    waves = {'cold': {p: [] for p in PRODUCERS}}
    labels = {}
    for n in range(BOOLQ_N):
        p = PRODUCERS[n // PER_PRODUCER]
        did = f'boolq-standin-{n}'
        answer = rng.random() < 0.62
        text = (f'passage: synthetic stand-in passage {n} about a river that '
                f'{"does" if answer else "does not"} flow north.\nquestion: does the river flow north {n}')
        waves['cold'][p].append({'key': f'q{n % PER_PRODUCER:02d}', 'op': BOOLQ_OP, 'text': text, 'dataset_id': did})
        labels[did] = answer
    admission = [(f'adm-standin-{n:02d}', f'passage: stand-in admission passage {n}.\nquestion: is it {n}',
                  'representative' if n < ADMISSION_REPRESENTATIVE else 'challenge', n % 2 == 0) for n in range(64)]
    return {'available': False, 'standin': True, 'waves': waves, 'labels': labels, 'admission': admission}


def dataset_digests():
    """SHA256 of every frozen dataset (complete ordered jobs) for the freeze record."""
    mat = materials()
    out = {f'materials/{w}': digest(mat['waves'][w]) for w in WAVES}
    out['materials/tags'] = digest(mat['tags'])
    out['materials/telemetry'] = digest(mat['telemetry'])
    out['materials/admission_texts'] = digest(mat['admission_texts'])
    q = boolq()
    out['boolq'] = digest(q['waves']) if q['available'] else 'unavailable'
    out['boolq/file'] = q.get('sha256', 'unavailable')
    return out
