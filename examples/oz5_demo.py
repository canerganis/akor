"""Synthetic four-module review bundles with independently varying procedures."""
import json

from examples.oz4_demo import example_channel as previous_channel
from oz import Atom, Channel


def example_channel(*, form=False, phased=True):
    snapshot = previous_channel(relative=False).snapshot()
    snapshot['session'] = 'oz5-code-review'
    if form:
        # Four modules; the last procedure is shared across all four reviews.
        steps = [(Atom('r', -1 - n), Atom('a', -1 - n),
                  Atom('t', -5 - n), Atom('t', -9)) for n in range(4)]
        program = [a for stage in zip(*steps) for a in stage] if phased else [a for row in steps for a in row]
        snapshot['form'] = [vars(a) for a in program]
    return Channel.from_snapshot(snapshot)


def messages(*, phased=True):
    ch = example_channel(form=True, phased=phased)
    rows = []
    for i in range(64):
        patches = [(i + offset) % 24 + 1 for offset in (0, 7, 13, 19)]
        procedures = [30 + (i // (3 ** n)) % 3 for n in range(4)]
        wire = ch.fill_form(*patches, *procedures, 32)
        atoms = ch.accept(wire, binding=ch.binding)
        rows.append((f'm{i}', ''.join(a.code + str(a.ref) for a in atoms)))
    assert len({w for _, w in rows}) == 64
    return rows


def main():
    ch = example_channel(form=True)
    wire = ch.fill_form(1, 8, 14, 20, 30, 31, 30, 31, 32)
    print(json.dumps({'frame': wire, 'form': ch.prompt(),
                      'atoms': [vars(a) for a in ch.accept(wire, binding=ch.binding)],
                      'actual_model_calls': 0}, indent=2))


if __name__ == '__main__':
    main()
