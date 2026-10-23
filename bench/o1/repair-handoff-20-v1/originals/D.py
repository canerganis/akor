"""Dependency execution order for job records {"id": str, "deps": [str]}."""


def topological_order(jobs):
    """Order job ids so that every job comes after its dependencies."""
    deps = {job['id']: set(job['deps']) for job in jobs}
    ready = [job['id'] for job in jobs if not deps[job['id']]]
    order = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for job in jobs:
            waiting = deps[job['id']]
            if current in waiting:
                waiting.discard(current)
                if not waiting:
                    ready.append(job['id'])
    return order


def execution_batches(jobs):
    """Group job ids into dependency frontiers."""
    order = topological_order(jobs)
    level = {}
    for job_id in order:
        job = [j for j in jobs if j['id'] == job_id][0]
        level[job_id] = min([level[d] + 1 for d in job['deps']] or [0])
    batches = []
    for job in jobs:
        k = level[job['id']]
        while len(batches) <= k:
            batches.append([])
        batches[k].append(job['id'])
    return batches
