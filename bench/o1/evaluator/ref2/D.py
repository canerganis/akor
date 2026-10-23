"""Reference 2 for ticket D (evaluator only), written apart from reference 1."""


def topological_order(jobs):
    position = {}
    for index, job in enumerate(jobs):
        if job['id'] in position:
            raise ValueError('duplicate job id')
        position[job['id']] = index
    waiting = {}
    users = {name: [] for name in position}
    for job in jobs:
        needs = []
        for dep in job['deps']:
            if dep not in position:
                raise ValueError('unknown dependency')
            if dep not in needs:
                needs.append(dep)
        waiting[job['id']] = len(needs)
        for dep in needs:
            users[dep].append(job['id'])
    ready = sorted([position[name] for name in position if waiting[name] == 0])
    order = []
    while ready:
        index = ready.pop(0)
        name = jobs[index]['id']
        order.append(name)
        for user in users[name]:
            waiting[user] -= 1
            if waiting[user] == 0:
                ready.append(position[user])
        ready.sort()
    if len(order) != len(jobs):
        raise ValueError('dependency cycle')
    return order


def execution_batches(jobs):
    order = topological_order(jobs)
    deps = {}
    for job in jobs:
        deps[job['id']] = job['deps']
    depth = {}

    def level(name):
        if name not in depth:
            depth[name] = max([level(d) + 1 for d in deps[name]] + [0])
        return depth[name]
    result = []
    for name in order:
        k = level(name)
        while len(result) <= k:
            result.append([])
        result[k].append(name)
    return result
