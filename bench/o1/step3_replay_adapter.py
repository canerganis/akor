"""Zero-call replay adapter for the step 3 control-match checks (oz.adapter/3). Not a model transport.

It is the O1 fixture adapter with one difference: each job is answered with the archived Sonnet accepted function for
that job and ticket revision, read from replay.json in OZ_FIXTURE_DIR ({"core_A@1": "<source>", ...}), so the executor
renders the adapter packets from the control's own accepted cores. A job with no archived answer stops the process
with an error: nothing is ever invented. Everything else (envelope, invocation log, usage reduction) is the fixture
adapter's own code, unchanged.
"""
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fixture_adapter as F  # noqa: E402


def answer(record: str, job: str, first: bool, mode: dict):
    parts = F.record_parts(record)
    table = json.loads((Path(os.environ['OZ_FIXTURE_DIR']) / 'replay.json').read_text(encoding='utf-8'))
    key = f"{job}@{parts['revision']}"
    if key not in table:
        raise SystemExit(f'replay: no archived answer for {key}')
    return ('value', table[key])


F.answer = answer

if __name__ == '__main__':
    F.main()
