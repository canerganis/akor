"""Provider-neutral, local-only multi-agent orchestration with synthetic data."""
from oz import Atom, Channel, Codebook, Macro, Reference
from oz_runtime import Inbox


def example_channel(recipient='worker'):
    return Channel(
        session='demo', task='review', revision=1, sender='lead', recipient=recipient,
        goal='SYNTHETIC: inspect timeout patch; preserve API and two retries; report uncertainty.',
        active=7,
        references=[Reference(7, 'patch', 'SYNTHETIC diff@abc: timeout=5 s per attempt; retries=2.'),
                    Reference(8, 'test', 'SYNTHETIC report: 3 passed, 0 failed.', 'demo.log@abc', 'passed'),
                    Reference(12, 'proposal', 'SYNTHETIC proposal: preserve 5 s per attempt.'),
                    Reference(13, 'fact', '12.50 ± 0.02 mm; method unknown.', 'demo.csv:2@abc'),
                    Reference(14, 'procedure', 'SYNTHETIC procedure: run timeout and retry tests.')],
        codebook=Codebook([Macro('V', (Atom('r', 0), Atom('a', 0), Atom('t', 14))),
                           Macro('P', (Atom('r', 13), Atom('>', 12)))]))


def main():
    worker = example_channel()
    reviewer = example_channel('reviewer')
    with Inbox() as inbox:
        inbox.post(worker, 'work1', 'V', binding=worker.binding)
        inbox.post(worker, 'work2', 'P', binding=worker.binding)
        inbox.post(reviewer, 'review1', 'r7', binding=reviewer.binding, after=['work1', 'work2'])
        inbox.post(worker, 'status1', '+8.', binding=worker.binding)
        print('V expands to:', worker.describe(worker.accept('V', binding=worker.binding)))
        print('Identical retry inserted:', inbox.post(worker, 'work1', 'r7a7t14', binding=worker.binding))
        print('Reviewer waiting:', inbox.claim(reviewer, owner='reviewer') is None)
        work = inbox.claim(worker, owner='worker')
        print('One delivery:', [j.id for j in work.jobs])
        # Replace only this synthetic adapter with your own provider call.
        # In real work, ACK after successfully processing the actual response.
        inbox.complete(work, {j.id: 'SYNTHETIC adapter accepted instruction; no tools executed.' for j in work.jobs})
        review = inbox.claim(reviewer, owner='reviewer')
        print('Reviewer unblocked:', [j.id for j in review.jobs])
        inbox.complete(review, {'review1': 'SYNTHETIC review receipt; no correctness claim.'})
        host = inbox.claim(worker, owner='host', kind='host')
        print('Host-only events:', worker.dispatch(host.jobs[0].wire, binding=worker.binding)['host_events'])
        inbox.complete(host, {'status1': 'Synthetic claim recorded without model call.'})
        print('Queue:', inbox.stats())
        print('No provider, tool or test procedure was executed by this demo.')


if __name__ == '__main__':
    main()
