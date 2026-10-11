"""Run from the repo root: python -m examples.oz_demo"""
from oz import Atom, Channel, Reference


def example_channel():
    return Channel(session='demo', task='T1', revision=1, sender='lead', recipient='worker',
                   goal='SYNTHETIC. Review patch 7, preserve API, report test outcomes honestly.', active=7,
                   references=[Reference(7, 'patch', 'SYNTHETIC patch, revision demo1; add timeout.'),
                               Reference(8, 'test', 'SYNTHETIC 3 checks passed.', 'demo.log@demo1', 'passed'),
                               Reference(9, 'test', 'SYNTHETIC one failing check.', 'demo.log@demo2', 'failed'),
                               Reference(10, 'hypothesis', 'Timeout may be missing.'),
                               Reference(11, 'reason', 'Measurement method unavailable.'),
                               Reference(12, 'proposal', 'Use 5 seconds per attempt.'),
                               Reference(13, 'fact', '12.50 ± 0.02 mm', 'demo.csv:2@demo1'),
                               Reference(14, 'procedure', 'python -m unittest'),
                               Reference(15, 'test', 'Tests not run.', 'notes@demo1', 'not_run')])


def main():
    channel = example_channel()
    for wire in ['a7', '?3', '+8.', '~10', '!11', ':12.50 ± 0.02 mm; method unknown']:
        atoms = channel.accept(wire, binding=channel.binding)
        print(f'{wire} -> {channel.encode(atoms)} -> {channel.describe(atoms)}')
        print('Receiver model needed:', channel.dispatch(wire, binding=channel.binding)['needs_model'])
    print('Only parsing and decoding occurred; no model, test procedure or tool was executed.')


if __name__ == '__main__':
    main()
