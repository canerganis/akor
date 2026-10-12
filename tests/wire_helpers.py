"""Readers for the stage-1f body: jobs are blocks [op_index,[job_id,ref_index,...],...]."""
import json


def body_of(value):
    """The decoded body of a packet, a prompt string or an already decoded body."""
    if isinstance(value, dict):
        return value
    return json.loads(getattr(value, 'text', value))


def rows(value):
    """Every job as [job_id, op_index, ref_index, ...] in body (block) order."""
    return [[row[0], block[0], *row[1:]] for block in body_of(value)['jobs'] for row in block[1:]]


def job_ids(value):
    return [row[0] for row in rows(value)]


def job_instructions(value):
    """[job_id, operation instruction] in body order."""
    body = body_of(value)
    return [[row[0], body['ops'][block[0]]] for block in body['jobs'] for row in block[1:]]
