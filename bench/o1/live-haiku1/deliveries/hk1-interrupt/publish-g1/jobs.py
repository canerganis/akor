"""Dependency execution order for job records {"id": str, "deps": [str]}."""


def topological_order(jobs):
    ids = [job['id'] for job in jobs]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate id')
    known = set(ids)
    deps_map = {}
    for job in jobs:
        deps = set(job['deps'])
        for dep in deps:
            if dep not in known:
                raise ValueError('unknown dependency')
        deps_map[job['id']] = deps
    taken = set()
    order = []
    while len(order) < len(ids):
        found = False
        for job_id in ids:
            if job_id not in taken and deps_map[job_id].issubset(taken):
                order.append(job_id)
                taken.add(job_id)
                found = True
                break
        if not found:
            raise ValueError('cycle')
    return order


def execution_batches(jobs):
    order = topological_order(jobs)
    deps = {}
    for job in jobs:
        deps[job['id']] = job['deps']
    level = {}
    for job_id in order:
        level[job_id] = max([level[d] + 1 for d in deps[job_id]] or [0])
    batches = []
    for job_id in order:
        k = level[job_id]
        while len(batches) <= k:
            batches.append([])
        batches[k].append(job_id)
    return batches
