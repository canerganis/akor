"""Fixture answers for ticket D: a third valid implementation the zero-token adapter returns."""


def topological_order(jobs):
    names = [job['id'] for job in jobs]
    needs = []
    for job in jobs:
        if names.count(job['id']) > 1:
            raise ValueError('duplicate id')
        wanted = set(job['deps'])
        if not wanted.issubset(set(names)):
            raise ValueError('missing dependency')
        needs.append(wanted)
    placed = []
    remaining = list(range(len(jobs)))
    while remaining:
        chosen = -1
        for index in remaining:
            if needs[index].issubset(set(placed)):
                chosen = index
                break
        if chosen < 0:
            raise ValueError('cycle')
        remaining.remove(chosen)
        placed.append(names[chosen])
    return placed


def execution_batches(jobs):
    order = topological_order(jobs)
    deps = dict([(job['id'], job['deps']) for job in jobs])
    rank = {}
    for name in order:
        rank[name] = max([rank[d] + 1 for d in deps[name]]) if deps[name] else 0
    groups = []
    for name in order:
        while rank[name] >= len(groups):
            groups.append([])
        groups[rank[name]].append(name)
    return groups
