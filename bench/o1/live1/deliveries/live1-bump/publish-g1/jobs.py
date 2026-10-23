"""Dependency execution order for job records {"id": str, "deps": [str]}."""


def topological_order(jobs):
    ids = [job['id'] for job in jobs]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate id')
    deps = {}
    for job in jobs:
        d = set(job['deps'])
        for x in d:
            if x not in ids:
                raise ValueError('unknown dependency')
        deps[job['id']] = d
    taken = set()
    order = []
    while len(order) < len(ids):
        found = None
        for i in ids:
            if i not in taken and deps[i].issubset(taken):
                found = i
                break
        if found is None:
            raise ValueError('cycle')
        taken.add(found)
        order.append(found)
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
