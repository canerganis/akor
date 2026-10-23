"""Dependency execution order for job records {"id": str, "deps": [str]}."""


def topological_order(jobs):
    seen = set()
    for job in jobs:
        if job['id'] in seen:
            raise ValueError('duplicate id')
        seen.add(job['id'])
    deps = {}
    for job in jobs:
        deps[job['id']] = set(job['deps'])
        for dep in job['deps']:
            if dep not in seen:
                raise ValueError('unknown dependency')
    taken = set()
    order = []
    while len(order) < len(jobs):
        chosen = None
        for job in jobs:
            if job['id'] not in taken and deps[job['id']].issubset(taken):
                chosen = job['id']
                break
        if chosen is None:
            raise ValueError('cycle')
        taken.add(chosen)
        order.append(chosen)
    return order


def execution_batches(jobs):
    order = topological_order(jobs)
    by_id = {}
    for job in jobs:
        by_id[job['id']] = job
    level = {}
    for job_id in order:
        deps = by_id[job_id]['deps']
        if deps:
            level[job_id] = 1 + max([level[d] for d in deps])
        else:
            level[job_id] = 0
    batches = []
    for job_id in order:
        k = level[job_id]
        while len(batches) <= k:
            batches.append([])
        batches[k].append(job_id)
    return batches
