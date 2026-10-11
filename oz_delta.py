"""OZ/4: exact differences from a bound work program, never implicit success."""
from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import re

from oz import Atom, Channel, Error

DELTA_GRAMMAR = (
    '\nOZ/4 relative frames: ^ requests the whole Base program. '
    '^i=WORK replaces primitive step i; ^i:j=WORK replaces slice [i,j). '
    'Indices are zero-based in the ORIGINAL expanded Base. Empty WORK deletes; '
    'i:i inserts before i. Separate edits with ; in strictly increasing, nonoverlapping order. '
    'Only work requests are allowed. Max 16 edits and 64 resulting steps. '
    '^@A:B,C:D instead substitutes reference IDs simultaneously throughout Base (max 16 mappings). '
    'Each frame starts from Base, never from the previous message. Silence is not success.'
)
WORK = frozenset({'r', 'a', 't', '>'})


def work_program(atoms) -> bool:
    return bool(atoms) and len(atoms) <= 64 and all(
        isinstance(a, Atom) and a.code in WORK and a.text is None
        and type(a.ref) is int and 1 <= a.ref <= 9999 for a in atoms)


def explicit(atoms) -> str:
    return ''.join(a.code + str(a.ref) for a in atoms)


def apply_delta(wire: str, basis: tuple[Atom, ...], decode) -> tuple[Atom, ...]:
    if not basis:
        raise Error('relative frame requires a bound Base program')
    if wire == '^':
        return basis
    if wire.startswith('^@'):
        parts = wire[2:].split(',')
        if not 1 <= len(parts) <= 16:
            raise Error('reference remap requires 1..16 mappings')
        refs, mapping = {a.ref for a in basis}, {}
        for part in parts:
            match = re.fullmatch(r'([1-9][0-9]{0,3}):([1-9][0-9]{0,3})', part)
            if not match:
                raise Error('invalid reference remap')
            source, target = int(match[1]), int(match[2])
            if source not in refs or source in mapping or source == target:
                raise Error('remap source missing, duplicated or unchanged')
            mapping[source] = target
        return tuple(Atom(a.code, mapping.get(a.ref, a.ref)) for a in basis)
    parts = wire[1:].split(';')
    if not 1 <= len(parts) <= 16:
        raise Error('relative frame requires 1..16 edits')
    result, cursor, last_start = [], 0, -1
    for part in parts:
        match = re.fullmatch(r'(0|[1-9][0-9]?)(?::(0|[1-9][0-9]?))?=(.*)', part)
        if not match:
            raise Error('invalid relative edit')
        start = int(match[1])
        end = int(match[2]) if match[2] is not None else start + 1
        if not 0 <= start <= end <= len(basis) or start < cursor or start <= last_start:
            raise Error('relative edits overlap, are unordered or outside Base')
        replacement = decode(match[3]) if match[3] else ()
        if replacement and not work_program(replacement):
            raise Error('relative edits may contain only work requests')
        result.extend(basis[cursor:start])
        result.extend(replacement)
        if len(result) > 64:
            raise Error('relative expansion exceeds 64 steps')
        cursor, last_start = end, start
    result.extend(basis[cursor:])
    if not work_program(result):
        raise Error('relative result must contain 1..64 work requests')
    return tuple(result)


def delta_spellings(basis, atoms) -> tuple[str, ...]:
    """Two splice layouts plus a simultaneous remap, when exactly applicable."""
    if not basis or not work_program(atoms):
        return ()
    if basis == atoms:
        return ('^',)

    def edit(i, j, values):
        span = str(i) if j == i + 1 else f'{i}:{j}'
        return span + '=' + explicit(values)

    # One enclosing splice can beat multiple tiny edits once separators and
    # position tokens are charged. Both are measured as complete strings.
    first = 0
    while first < min(len(basis), len(atoms)) and basis[first] == atoms[first]:
        first += 1
    last, end = len(basis), len(atoms)
    while last > first and end > first and basis[last - 1] == atoms[end - 1]:
        last -= 1
        end -= 1
    candidates = ['^' + edit(first, last, atoms[first:end])]
    edits = [edit(i, j, atoms[a:b]) for tag, i, j, a, b in
             SequenceMatcher(a=basis, b=atoms, autojunk=False).get_opcodes() if tag != 'equal']
    if len(edits) <= 16:
        candidates.append('^' + ';'.join(edits))
    if len(basis) == len(atoms) and all(a.code == b.code for a, b in zip(basis, atoms)):
        remap = {a.ref: b.ref for a, b in zip(basis, atoms) if a.ref != b.ref}
        if len(remap) <= 16 and all(remap.get(a.ref, a.ref) == b.ref for a, b in zip(basis, atoms)):
            candidates.append('^@' + ','.join(f'{a}:{b}' for a, b in sorted(remap.items())))
    return tuple(dict.fromkeys(candidates))


def fit_basis(channel: Channel, messages, *, counters, revision: int, basis_limit: int = 8, **options):
    """Choose one reference program using complete receiver input costs.

    Candidates are actual work messages, ranked by frequency then first
    occurrence. The full Base definition is charged in every batch.
    """
    from oz_batch import render
    if type(basis_limit) is not int or not 1 <= basis_limit <= 16:
        raise Error('basis_limit must be 1..16')
    messages, counters = tuple(messages), tuple(counters)
    frames = tuple(channel.accept(w, binding=channel.binding) for _, w in messages)
    counts = Counter(f for f in frames if work_program(f))
    candidates = [f for f, _ in counts.most_common(basis_limit)]
    baseline = render(channel, messages, counters=counters, **options)
    best_channel, best, evaluated = channel, baseline, 1
    # Use primitives when trying another Base: incoming ^ must never be
    # reinterpreted under a different prediction.
    raw = [(mid, ':' + f[0].text if f[0].code == ':' else
            ''.join(a.code + (str(a.ref) if a.ref is not None else '') for a in f))
           for (mid, _), f in zip(messages, frames)]
    for basis in candidates:
        snapshot = channel.snapshot()
        snapshot['basis'] = [vars(a) for a in basis]
        snapshot['revision'] = revision
        candidate = Channel.from_snapshot(snapshot)
        packet = render(candidate, raw, counters=counters, **options)
        evaluated += 1
        if (all(a <= b for a, b in zip(packet.tokens, best.tokens)) and packet.tokens != best.tokens):
            best_channel, best = candidate, packet
    return best_channel, best, evaluated, baseline.tokens
