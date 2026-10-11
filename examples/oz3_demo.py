"""Exact vector semantics; synthetic instructions, no tool execution."""
import json

from oz import Atom, Channel, Codebook, Macro, Reference


def example_channel(*, vectors=True, macros=True):
    return Channel(session='oz3-demo', task='review', revision=1, sender='lead', recipient='worker',
                   active=1, goal='Synthetic patch reviews; preserve public API, units and uncertainty.',
                   references=[*[Reference(n, 'patch', f'Fixture {n}: timeout=5 s; retries=2; API unchanged.', f'fixture:p{n}@1')
                                 for n in range(1, 25)],
                               Reference(30, 'procedure', 'Check timeout, retry count and API; report actual failures.')],
                   codebook=Codebook([Macro('V', (Atom('r', 0), Atom('a', 0), Atom('t', 30)))]
                                     if macros else [], vectors=vectors))


def main():
    ch = example_channel()
    wire = 'V[1:16]'
    atoms = ch.accept(wire, binding=ch.binding)
    print(json.dumps({'frame': wire, 'primitive_requests': len(atoms),
                      'first_target': [vars(a) for a in atoms[:3]],
                      'last_target': [vars(a) for a in atoms[-3:]],
                      'exact_round_trip': ch.accept(ch.encode(atoms), binding=ch.binding) == atoms,
                      'actual_model_calls': 0, 'actual_tool_executions': 0}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
