"""Dependency execution order for job records {"id": str, "deps": [str]}."""


def topological_order(jobs):
    ids = [j['id'] for j in jobs]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate')
    known = set(ids)
    deps = {}
    for j in jobs:
        d = set(j['deps'])
        if not d.issubset(known):
            raise ValueError('unknown dep')
        deps[j['id']] = d
    order = []
    done = set()
    while len(order) < len(ids):
        for i in ids:
            if i not in done and deps[i].issubset(done):
                order.append(i)
                done.add(i)
                break
        else:
            raise ValueError('cycle')
    return order


def execution_batches(jobs):
    order = topological_order(jobs)
    deps = {j['id']: j['deps'] for j in jobs}
    level = {}
    for i in order:
        level[i] = max([level[d] + 1 for d in deps[i]] or [0])
    batches = []
    for i in order:
        k = level[i]
        while len(batches) <= k:
            batches.append([])
        batches[k].append(i)
    return batches
