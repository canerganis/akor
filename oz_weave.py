"""OZ/5 column packets: preserve independent jobs while sharing argument structure."""
from __future__ import annotations

import re
from functools import lru_cache

from oz import Channel, Error, TokenMeter, _dump
from oz_form import form_spelling


WEAVE_GRAMMAR = (
    '\nOZ/5 matrix: ids names independent requests in order; cols[i] expands to slot $i '
    'values for those requests. In each column, comma concatenates; L:H is an ascending '
    'inclusive range; N*K repeats N K times; (SERIES)*K repeats the whole flat series K times. '
    'No nesting. Every column must expand to exactly len(ids) values. '
    'For request ids[j], fill Form with value j from each column. '
    'Keep one result per ID; do not merge jobs or assume parallel execution.'
)


def expand_column(text: str, *, count: int) -> tuple[int, ...]:
    """Strict bounded grammar, without eval, recursion or guessed defaults."""
    if type(count) is not int or not 1 <= count <= 64:
        raise Error('column requires 1..64 values')
    if not isinstance(text, str) or not 1 <= len(text) <= 4096:
        raise Error('invalid column text')

    def flat(part):
        result = []
        for token in part.split(','):
            match = re.fullmatch(r'([1-9][0-9]{0,3})(?:(:)([1-9][0-9]{0,3})|(\*)([1-9][0-9]?))?', token)
            if not match:
                raise Error('invalid column term')
            value = int(match[1])
            if match[2]:
                end = int(match[3])
                size = end - value + 1
                if not 1 <= size <= count - len(result):
                    raise Error('column range exceeds bounds or descends')
                result.extend(range(value, end + 1))
            else:
                size = int(match[5]) if match[4] else 1
                if not 1 <= size <= count - len(result):
                    raise Error('column repetition exceeds bounds')
                result.extend([value] * size)
        return result

    values, pos = [], 0
    # Split only between top-level terms. Parentheses are a single flat group.
    while pos < len(text):
        if text[pos] == '(':
            match = re.match(r'\(([^()]*)\)\*([1-9][0-9]?)(?=,|$)', text[pos:])
            if not match:
                raise Error('invalid column group')
            block, repeats = flat(match[1]), int(match[2])
            if len(block) * repeats > count - len(values):
                raise Error('column group exceeds bounds')
            values.extend(block * repeats)
        else:
            match = re.match(r'[^,()]+(?=,|$)', text[pos:])
            if not match:
                raise Error('invalid column term')
            values.extend(flat(match[0]))
        pos += match.end()
        if len(values) > count:
            raise Error('column exceeds expected length')
        if pos < len(text):
            if text[pos] != ',' or pos == len(text) - 1:
                raise Error('invalid column separator')
            pos += 1
    if len(values) != count:
        raise Error('column length does not match message count')
    return tuple(values)


def compact_column(values, *, counters=()) -> str:
    """Bounded shortest-byte paths plus whole-column token scoring.

    Token counts are not additive. This is a finite candidate search; the final
    complete receiver packet is measured independently before selection.
    """
    values = tuple(values)
    if not 1 <= len(values) <= 64 or any(type(n) is not int or not 1 <= n <= 9999 for n in values):
        raise Error('column values must be 1..64 reference IDs')

    @lru_cache(maxsize=256)
    def paths(sequence, groups):
        size = len(sequence)
        best = [()] * size + [('',)]
        for i in range(size - 1, -1, -1):
            edges = [(i + 1, str(sequence[i]))]
            for j in range(i + 2, size + 1):
                segment = sequence[i:j]
                if all(n == segment[0] for n in segment):
                    edges.append((j, f'{segment[0]}*{len(segment)}'))
                if all(b == a + 1 for a, b in zip(segment, segment[1:])):
                    edges.append((j, f'{segment[0]}:{segment[-1]}'))
            if groups:
                for period in range(2, (size - i) // 2 + 1):
                    block = sequence[i:i + period]
                    repeats = 1
                    while sequence[i + repeats * period:i + (repeats + 1) * period] == block:
                        repeats += 1
                    if repeats >= 2:
                        spelling = paths(block, False)[0]
                        for k in range(2, repeats + 1):
                            edges.append((i + period * k, f'({spelling})*{k}'))
            candidates = {part + (',' + tail if tail else '') for j, part in edges for tail in best[j]}
            best[i] = tuple(sorted(candidates, key=lambda s: (len(s), s))[:8])
        return best[0]

    candidates = (*paths(values, True), ','.join(map(str, values)))
    meter = TokenMeter(counters)
    chosen = min(candidates, key=meter.score)
    if expand_column(chosen, count=len(values)) != values:
        raise Error('column semantic round-trip failed')
    return chosen


def decode_matrix(channel: Channel, value: dict, *, binding: str) -> tuple[tuple[str, str], ...]:
    from oz_batch import valid_id
    if binding != channel.binding or not channel.form:
        raise Error('matrix channel/Form mismatch')
    if not isinstance(value, dict) or set(value) != {'ids', 'cols'}:
        raise Error('matrix requires ids and cols only')
    ids, columns = value['ids'], value['cols']
    if (not isinstance(ids, (list, tuple)) or not 1 <= len(ids) <= 64
            or any(not valid_id(mid) for mid in ids) or len(set(ids)) != len(ids)):
        raise Error('invalid matrix message IDs')
    slots = max(-a.ref for a in channel.form if a.ref < 0)
    if not isinstance(columns, (list, tuple)) or len(columns) != slots:
        raise Error('matrix column count must match Form slots')
    expanded = [expand_column(c, count=len(ids)) for c in columns]
    return tuple((mid, channel.fill_form(*args)) for mid, args in zip(ids, zip(*expanded)))


def encode_matrix(channel: Channel, ids, frames, *, counters=()):
    ids, frames, counters = tuple(ids), tuple(frames), tuple(counters)
    if len(ids) != len(frames):
        raise Error('matrix IDs and frames must have the same length')
    wires = [form_spelling(channel.form, f) for f in frames]
    if not wires or any(w is None for w in wires):
        return None
    arguments = [tuple(map(int, w[1:].split(','))) for w in wires]
    value = {'ids': list(ids), 'cols': [compact_column(c, counters=counters) for c in zip(*arguments)]}
    recovered = decode_matrix(channel, value, binding=channel.binding)
    if tuple(w for _, w in recovered) != tuple(wires):
        raise Error('matrix semantic round-trip failed')
    return value


def matrix_body(channel: Channel, ids, frames, *, counters):
    value = encode_matrix(channel, ids, frames, counters=counters)
    if value is None:
        return None
    wires = [w for _, w in decode_matrix(channel, value, binding=channel.binding)]
    return channel.dictionary(wires) + WEAVE_GRAMMAR + '\n' + _dump(value)
