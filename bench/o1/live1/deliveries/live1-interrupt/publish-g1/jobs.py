"""Dependency execution order for job records {"id": str, "deps": [str]}."""


def topological_order(jobs):
    ids = [j['id'] for j in jobs]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate id')
    deps = {j['id']: set(j['deps']) for j in jobs}
    for d in deps.values():
        for x in d:
            if x not in deps:
                raise ValueError('unknown dependency')
    done = set()
    order = []
    while len(order) < len(ids):
        for i in ids:
            if i not in done and deps[i].issubset(done):
                done.add(i)
                order.append(i)
                break
        else:
            raise ValueError('cycle')
    return order


def execution_batches(jobs):
    order = topological_order(jobs)
    deps = {j['id']: j['deps'] for j in jobs}
    level = {}
    batches = []
    for i in order:
        level[i] = max([level[d] + 1 for d in deps[i]] or [0])
        while len(batches) <= level[i]:
            batches.append([])
        batches[level[i]].append(i)
    return batches
