"""Bounded, lossless OZ/3 compiler. No model calls or live channel mutations."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable, Iterable

from oz import Atom, Channel, Codebook, Error, Macro, TokenMeter
from oz_batch import Batch, render


def explicit(atoms: Iterable[Atom]) -> str:
    atoms = tuple(atoms)
    if atoms[0].code == ':':
        return ':' + atoms[0].text
    return ''.join(a.code + (str(a.ref) if a.ref is not None else '') for a in atoms)


@dataclass(frozen=True)
class Compilation:
    channel: Channel
    messages: tuple[tuple[str, str], ...]
    packet: Batch
    baseline: Batch
    added_macros: tuple[Macro, ...]
    evaluated_dictionaries: int
    tokenizer_evaluations: int

    @property
    def changed(self) -> bool:
        return self.channel.binding != self.baseline.binding


def _templates(frames, existing, *, limit):
    """Mine 2..8-step work patterns; ranking is heuristic, acceptance is measured.

    Normalize one reference at a time to the single parameter. Other references
    stay exact. Overlapping occurrences may affect ranking, never execution.
    """
    counts = Counter()
    for frame in frames:
        for start in range(len(frame)):
            for size in range(2, min(8, len(frame) - start) + 1):
                segment = frame[start:start + size]
                if any(a.code not in {'a', 'r', 't', '>'} for a in segment):
                    break
                variants = {segment}
                for ref in {a.ref for a in segment}:
                    variants.add(tuple(Atom(a.code, 0 if a.ref == ref else a.ref) for a in segment))
                counts.update(variants)
    candidates = [steps for steps, count in counts.items() if count >= 2 and steps not in existing]
    # Prefer parameter reuse when fixed and parameterized patterns tie.
    def rank(steps):
        definition = explicit(steps)
        saving = (len(definition) - (2 if any(a.ref == 0 for a in steps) else 1)) * counts[steps]
        return (-saving + len(definition), -counts[steps], definition)
    return sorted(candidates, key=rank)[:limit]


def compile_messages(channel: Channel, messages: Iterable[tuple[str, str]], *,
                     counters: Iterable[Callable[[str], int]], max_macros: int = 4,
                     template_limit: int = 8, candidate_limit: int = 32,
                     response_contract: str = '', additional_context: str = '') -> Compilation:
    """Choose only dictionary changes reducing complete measured receiver input.

    Every provided tokenizer must be no worse than the current candidate and
    at least one must improve. Includes grammar, definitions, references, IDs,
    supplied response contract and predecessor context. This is calibration on
    the supplied corpus, not a prediction of unseen traffic or task accuracy.
    Returns a NEW channel revision only on improvement; never mutates an inbox.
    """
    if type(max_macros) is not int or not 0 <= max_macros <= 8:
        raise Error('max_macros must be 0..8')
    if type(template_limit) is not int or not 1 <= template_limit <= 32:
        raise Error('template_limit must be 1..32')
    messages = tuple(messages)
    meter = TokenMeter(counters)
    if not meter.counters:
        raise Error('compiler requires actual target token counters')
    cached = tuple(lambda text, i=i: meter.counts(text)[i] for i in range(len(meter.counters)))
    options = dict(counters=cached, candidate_limit=candidate_limit,
                   response_contract=response_contract, additional_context=additional_context)
    # Render first to validate the public input shape and IDs before mining.
    baseline = render(channel, messages, **options)
    frames = tuple(channel.accept(w, binding=channel.binding) for _, w in messages)
    raw = tuple((mid, explicit(atoms)) for (mid, _), atoms in zip(messages, frames))
    original = channel.snapshot()

    def fork(macros):
        snap = dict(original)
        snap['revision'] += 1
        snap['vectors'] = True
        snap['macros'] = [dict(code=m.code, steps=[vars(a) for a in m.steps]) for m in macros]
        return Channel.from_snapshot(snap)

    def improves(packet, best):
        return all(a <= b for a, b in zip(packet.tokens, best.tokens)) and packet.tokens != best.tokens

    current, best, evaluated = channel, baseline, 1
    vector = fork(channel.codebook.macros.values())
    packet = render(vector, raw, **options)
    evaluated += 1
    if improves(packet, best):
        current, best = vector, packet
    added = []
    for _ in range(max_macros):
        available = [chr(n) for n in range(ord('A'), ord('Z') + 1) if chr(n) not in current.codebook.macros]
        if not available:
            break
        patterns = _templates(frames, {m.steps for m in current.codebook.macros.values()}, limit=template_limit)
        winner = None
        for steps in patterns:
            # Score the complete small dictionary for every free code, then
            # measure full receiver packets for the best two. Search is bounded.
            codes = sorted(available, key=lambda c: meter.score(Codebook([Macro(c, steps)]).prompt([c])))[:2]
            for code in codes:
                macro = Macro(code, steps)
                try:
                    candidate = fork([*current.codebook.macros.values(), macro])
                except Error:
                    continue  # incompatible parameter kinds; cannot be used
                candidate_packet = render(candidate, raw, **options)
                evaluated += 1
                if not improves(candidate_packet, best):
                    continue
                score = (max(candidate_packet.tokens), sum(candidate_packet.tokens), len(candidate_packet.text))
                if winner is None or score < winner[0]:
                    winner = (score, candidate, candidate_packet, macro)
        if winner is None:
            break
        _, current, best, macro = winner
        added.append(macro)
    compressed = tuple((mid, wire) for (mid, _), wire in zip(raw, best.wires))
    for (_, wire), expected in zip(compressed, frames):
        if current.accept(wire, binding=current.binding) != expected:
            raise Error('compiler semantic round-trip failed')
    return Compilation(current, compressed, best, baseline, tuple(added), evaluated, len(meter.cache))
