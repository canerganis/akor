"""Model-bound text of the replication: OZ/1g packets, the pilot bootstrap template, the pilot Sonnet flags.

Standard library only. Nothing here is new prompt material (A4.9): the system text is oz_batch.SYSTEM, the
bootstrap system text is bootstrap_shim.system_text (Astra's 858 character instruction and the pinned spec excerpt),
the Codex input is the system text, two newlines and the packet (codex_cli_adapter), and the Sonnet argv is
claude_map_adapter.command. The only new text is the operation material, read verbatim from Fable's
bench/ozmap_rep/ops/ops.md (A4.8): its "Record type" section becomes the goal and each operation section becomes that
operation's instruction and contract, with the author's "Expectation:" paragraph removed so that no classification
hint reaches the learner.
"""
from __future__ import annotations

import functools
import hashlib
import json
from pathlib import Path
import re
import sys

from . import config

_EXAMPLES = config.REPO / 'examples'
for _p in (str(config.REPO), str(_EXAMPLES)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import bootstrap_shim  # noqa: E402
import claude_map_adapter  # noqa: E402
import oz_batch  # noqa: E402
import oz_reply  # noqa: E402

INSTRUCTION_SHA256 = bootstrap_shim.INSTRUCTION_SHA256
SONNET_FLAGS = tuple(claude_map_adapter.FLAGS)
SYSTEM = oz_batch.SYSTEM
OPS_MD = config.HERE / 'ops' / 'ops.md'
MAX_IDS = config.MAX_BATCH


def sonnet_bootstrap_system(system, cfg):
    return bootstrap_shim.system_text(system, cfg)


def sonnet_argv(exe, model, effort, system):
    return claude_map_adapter.command(exe, model, effort, system)


# ------------------------------------------------------------------------------------------- operation material

@functools.lru_cache(maxsize=1)
def _sections():
    text = OPS_MD.read_text(encoding='utf-8').replace('\r\n', '\n')
    parts = re.split(r'^## ', text, flags=re.M)
    out = {}
    for part in parts[1:]:
        title, _, body = part.partition('\n')
        out[title.strip()] = body.strip('\n')
    return out


def _strip_expectation(body):
    paragraphs = body.split('\n\n')
    return '\n\n'.join(p for p in paragraphs if not p.startswith('Expectation:')).strip()


@functools.lru_cache(maxsize=1)
def materials_texts():
    """(goal, {op: instruction}) read from ops.md."""
    sections = _sections()
    goal = 'Tensile test records. ' + sections['Record type'].strip()
    instructions = {}
    for title, body in sections.items():
        m = re.match(r'Operation `([a-z_]+)`: (.*)', title)
        if m and m.group(1) in config.OPERATIONS:
            instructions[m.group(1)] = f'Operation {m.group(1)} ({m.group(2)}). ' + _strip_expectation(body)
    missing = set(config.OPERATIONS) - set(instructions)
    if missing:
        raise RuntimeError(f'ops.md lacks operations {sorted(missing)}')
    return goal, instructions


def contracts():
    """Registry and bootstrap contracts of the four materials operations."""
    goal, instructions = materials_texts()
    return {op: {'name': f'tensile_{op}', 'family': 'materials', 'deterministic': True, 'goal': goal,
                 'instruction': instructions[op], 'result': 'one JSON string, exactly the output the operation names',
                 'input': 'one tensile test record per job'} for op in config.OPERATIONS}


def boolq_texts():
    from .workload import boolq
    q = boolq()
    return q['goal'], {config.BOOLQ_OP: q['op_text']}


def texts_for(workload):
    return materials_texts() if workload == 'materials' else boolq_texts()


def bootstrap_config(workload):
    """The oz.bootstrap.config/2 document of a backend's bootstrap: every operation of the workload with its contract
    and the eligibility the registry derives (materials eligible through rule_provenance/1, BoolQ never)."""
    if workload == 'materials':
        ops = list(config.OPERATIONS)
        cons = contracts()
        return {'schema': bootstrap_shim.CONFIG_SCHEMA, 'ops': ops, 'contracts': {op: cons[op] for op in ops},
                'eligibility': {op: True for op in ops}}
    goal, inst = boolq_texts()
    return {'schema': bootstrap_shim.CONFIG_SCHEMA, 'ops': [config.BOOLQ_OP],
            'contracts': {config.BOOLQ_OP: {'name': 'boolq_answer', 'dataset': 'BoolQ', 'deterministic': False,
                                            'goal': goal, 'instruction': inst[config.BOOLQ_OP],
                                            'result': 'the string yes or no'}},
            'eligibility': {config.BOOLQ_OP: False}}


# ---------------------------------------------------------------------------------------------------- packets

def packet_ids(n):
    return [f'j{i:02d}' for i in range(n)]


def packet(jobs, workload):
    """(body text, {packet id: job id}) of one OZ/1g packet for these jobs (at most 64), in the given order. refs
    carry each job's text after the D2 input policy; job IDs on the wire are neutral packet IDs."""
    from .workload import resolve
    if not 1 <= len(jobs) <= MAX_IDS:
        raise ValueError('a packet holds 1 to 64 jobs')
    goal, instructions = texts_for(workload)
    ops, refs, blocks, mapping = [], [], {}, {}
    for pid, job in zip(packet_ids(len(jobs)), jobs):
        inst = instructions[job['op']]
        if inst not in ops:
            ops.append(inst)
        k = ops.index(inst)
        refs.append(resolve(job['text']))
        blocks.setdefault(k, [k]).append([pid, len(refs) - 1])
        mapping[pid] = job['id']
    body = {'v': oz_batch.VERSION, 'goal': goal, 'ops': ops, 'refs': refs, 'jobs': [blocks[k] for k in sorted(blocks)]}
    oz_batch.validate_packet(body)
    return oz_batch.J(body), mapping


def model_input(jobs, workload, bootstrap=False):
    """{system, body, stdin_codex, mapping, ops}: the complete model-bound text of one call."""
    body, mapping = packet(jobs, workload)
    cfg = bootstrap_config(workload) if bootstrap else None
    system = bootstrap_shim.system_text(SYSTEM, cfg) if bootstrap else SYSTEM
    return {'system': system, 'body': body, 'stdin_codex': system + '\n\n' + body, 'mapping': mapping,
            'ops': list(cfg['ops']) if cfg else None}


def prompt_record(inp):
    """The text stored in prompts/<call id>.txt: the system text, two newlines, the packet."""
    return inp['system'] + '\n\n' + inp['body']


def sha256(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def parse_answers(reply, mapping):
    """({job id: value}, {job id: (code, message)}, rejection or None) of an OZ/1g reply for this call."""
    if not isinstance(reply, str):
        return {}, {}, 'no reply text'
    parsed = oz_reply.parse_reply(reply, list(mapping))
    if parsed.rejection:
        return {}, {}, parsed.rejection
    return ({mapping[k]: v for k, v in parsed.accepted.items()},
            {mapping[k]: list(v) for k, v in parsed.failed.items()}, None)


def parse_bootstrap(reply, ops):
    """(answers reply, rules {op: {"none": True} | {"ast_b64", "ast_sha256", "bytes"}}) or raises Malformed."""
    return bootstrap_shim.parse_envelope(reply, ops)


Malformed = bootstrap_shim.Malformed


def learner_prompt_leaks(prompt, admission):
    """Admission case texts (raw or after the input policy) found in a prompt. A label alone is an ordinary output
    word that contracts name (pass, room, unknown), so a label counts as leaked only with its case text."""
    from .workload import resolve
    found = []
    for cases in (admission or {}).values():
        for c in cases:
            for t in {c['text'], resolve(c['text'])}:
                if t and t in prompt:
                    found.append(t)
                    break
    return found
