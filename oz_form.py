"""OZ/5: one typed work shape, several independently bound reference slots."""
from __future__ import annotations

from collections import defaultdict
import re

from oz import Atom, Channel, Error, RULES
from oz_delta import WORK, work_program


FORM_GRAMMAR = (
    '\nOZ/5: &v0,v1,... fills every $i in Form with reference vi (zero-based). '
    'Supply every slot exactly once, in order; repeated $i uses the same reference. '
    'Positive constants stay fixed. Expand Form in order into work requests, '
    'never success claims or tool permissions. Each frame is independent.'
)


def validate_form(form, references) -> int:
    """Negative references encode slots: -1=$0, -2=$1; zero is invalid."""
    if not 1 <= len(form) <= 64:
        raise Error('Form requires 1..64 work steps')
    slots = {}
    for atom in form:
        if (not isinstance(atom, Atom) or atom.code not in WORK or atom.text is not None
                or type(atom.ref) is not int or not -32 <= atom.ref <= 9999 or atom.ref == 0):
            raise Error('Form requires explicit work constants or slots $0..$31')
        allowed = RULES[atom.code].kinds
        if atom.ref < 0:
            slot = -atom.ref - 1
            slots[slot] = slots.get(slot, allowed) & allowed
            if not slots[slot]:
                raise Error('Form slot has incompatible reference types')
        elif atom.ref not in references or references[atom.ref].kind not in allowed:
            raise Error('Form fixed reference missing or incompatible')
    if not slots or set(slots) != set(range(len(slots))):
        raise Error('Form slots must be contiguous from $0, with at least one slot')
    return len(slots)


def form_text(form) -> str:
    return ''.join(a.code + ('$' + str(-a.ref - 1) if a.ref < 0 else str(a.ref)) for a in form)


def apply_form(wire, form) -> tuple[Atom, ...]:
    if not form:
        raise Error('slot frame requires a bound Form')
    if not re.fullmatch(r'&[1-9][0-9]{0,3}(?:,[1-9][0-9]{0,3}){0,31}', wire):
        raise Error('invalid Form arguments')
    values = tuple(map(int, wire[1:].split(',')))
    if len(values) != max(-a.ref for a in form if a.ref < 0):
        raise Error('Form requires exactly one value per slot')
    return tuple(Atom(a.code, values[-a.ref - 1] if a.ref < 0 else a.ref) for a in form)


def form_spelling(form, atoms) -> str | None:
    if not form or len(form) != len(atoms) or not work_program(atoms):
        return None
    values = {}
    for step, atom in zip(form, atoms):
        if step.code != atom.code:
            return None
        if step.ref > 0:
            if step.ref != atom.ref:
                return None
        else:
            slot = -step.ref - 1
            if values.setdefault(slot, atom.ref) != atom.ref:
                return None
    return '&' + ','.join(str(values[i]) for i in range(len(values)))


def infer_forms(frames, *, limit=8):
    """Same operation sequence; constants stay fixed, equal columns share a slot.

    Equality is observed across ALL examples in a group, not guessed from one
    frame. A later message breaking the relationship falls back losslessly.
    """
    groups = defaultdict(list)
    for frame in frames:
        if work_program(frame):
            groups[tuple(a.code for a in frame)].append(frame)
    forms = []
    for codes, group in groups.items():
        if len(set(group)) < 2:
            continue
        columns, steps = {}, []
        for i, code in enumerate(codes):
            values = tuple(f[i].ref for f in group)
            ref = values[0] if len(set(values)) == 1 else -1 - columns.setdefault(values, len(columns))
            steps.append(Atom(code, ref))
        if len(columns) <= 32:
            forms.append((len(group) * len(codes), tuple(steps)))
    return tuple(f for _, f in sorted(forms, key=lambda item: -item[0])[:limit])


def fit_form(channel: Channel, messages, *, counters, revision: int, form_limit=8, **options):
    from oz_batch import render
    from oz_compiler import explicit
    if type(form_limit) is not int or not 1 <= form_limit <= 16:
        raise Error('form_limit must be 1..16')
    messages, counters = tuple(messages), tuple(counters)
    baseline = render(channel, messages, counters=counters, **options)
    frames = tuple(channel.accept(w, binding=channel.binding) for _, w in messages)
    raw = [(mid, explicit(f)) for (mid, _), f in zip(messages, frames)]
    best_channel, best, evaluated = channel, baseline, 1
    for form in infer_forms(frames, limit=form_limit):
        snapshot = channel.snapshot()
        snapshot['form'] = [vars(a) for a in form]
        snapshot['revision'] = revision
        candidate = Channel.from_snapshot(snapshot)
        packet = render(candidate, raw, counters=counters, **options)
        evaluated += 1
        if all(a <= b for a, b in zip(packet.tokens, best.tokens)) and packet.tokens != best.tokens:
            best_channel, best = candidate, packet
    return best_channel, best, evaluated, baseline.tokens
