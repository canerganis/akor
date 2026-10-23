"""Reference 1 for ticket D (evaluator only)."""


def topological_order(jobs):
    ids = [job['id'] for job in jobs]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate id')
    deps = {}
    for job in jobs:
        needed = set(job['deps'])
        for name in needed:
            if name not in ids:
                raise ValueError('missing dependency')
        deps[job['id']] = needed
    done = set()
    order = []
    while len(order) < len(ids):
        pick = None
        for name in ids:
            if name not in done and deps[name] <= done:
                pick = name
                break
        if pick is None:
            raise ValueError('cycle')
        done.add(pick)
        order.append(pick)
    return order


def execution_batches(jobs):
    order = topological_order(jobs)
    deps = {job['id']: job['deps'] for job in jobs}
    level = {}
    for name in order:
        level[name] = 1 + max([level[d] for d in deps[name]]) if deps[name] else 0
    batches = []
    for name in order:
        while len(batches) <= level[name]:
            batches.append([])
        batches[level[name]].append(name)
    return batches
