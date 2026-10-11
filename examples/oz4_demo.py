"""A shared code-review program, transmitted through exact differences."""
import json

from examples.oz3_demo import example_channel as previous_channel
from oz import Channel

ORDER = [9, 2, 7, 3, 11, 1, 6, 4, 10, 5, 8, 12, 19, 17, 15, 18]


def example_channel(*, relative=True):
    old = previous_channel()
    snapshot = old.snapshot()
    snapshot['session'] = 'oz4-code-review'
    snapshot['goal'] = 'SYNTHETIC code-review requests. Keep API and test requirements; report actual outcomes only.'
    snapshot['references'].extend([
        dict(number=31, kind='procedure', text='Request boundary and retry tests for the supplied patch.', source='', status=''),
        dict(number=32, kind='procedure', text='Request regression tests; preserve failure details.', source='', status=''),
    ])
    snapshot['references'].extend(dict(number=40 + n, kind='proposal', text=f'Propose fixture change {n}; not applied.', source='', status='')
                                  for n in range(1, 9))
    ch = Channel.from_snapshot(snapshot)
    if relative:
        snapshot['basis'] = [vars(a) for a in ch.accept(''.join(f'V{n}' for n in ORDER), binding=ch.binding)]
        return Channel.from_snapshot(snapshot)
    return ch


def messages():
    ch = example_channel()
    # Every request has a distinct plan; most of a 48-step program is shared.
    frames = []
    for i in range(64):
        position = i % 16 * 3 + 2
        procedure = 31 if i < 32 else 32
        # Vary a second work step in another region to avoid an identical
        # message corpus masquerading as 64 independent efficiency gains.
        read = (i * 7) % 24 + 1
        positions = {position: f't{procedure}', 46: f'r{read}'}
        wire = '^' + ';'.join(f'{p}={s}' for p, s in sorted(positions.items()))
        atoms = ch.accept(wire, binding=ch.binding)
        frames.append((f'm{i}', ''.join(a.code + str(a.ref) for a in atoms)))
    assert len({w for _, w in frames}) == 64
    return frames


def main():
    ch = example_channel()
    examples = ['^', '^2=t31', '^@30:31', '^0:2=r4a4']
    print(json.dumps([{'frame': w, 'primitive_requests': len(ch.accept(w, binding=ch.binding)),
                       'first_steps': [vars(a) for a in ch.accept(w, binding=ch.binding)[:6]]}
                      for w in examples], indent=2))


if __name__ == '__main__':
    main()
