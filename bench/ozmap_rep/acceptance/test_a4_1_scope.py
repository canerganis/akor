"""A4.1: scope and precedence. The harness exists, and the frozen material is not touched."""
import subprocess

import pytest

import ozrep_helpers as H

FROZEN_PATHS = ('bench/ozmap/pilot.py', 'bench/ozmap/score.py', 'bench/ozmap/data.py', 'bench/ozmap/oracle.py',
                'bench/ozmap/fake_cli.py', 'bench/ozmap/freeze.json', 'bench/ozmap/registry.json',
                'bench/ozmap/identity.json', 'bench/ozmap/routes.json', 'bench/ozmap/telemetry.json',
                'oz.py', 'oz_accept.py', 'oz_batch.py', 'oz_cli.py', 'oz_do.py', 'oz_fault.py', 'oz_memo.py',
                'examples')


def test_harness_exists():
    """Red until the harness is built: the sentinel module of the guard (INTERFACE.md) must exist."""
    assert H.harness_built(), f'{H.SENTINEL} is missing: the replication harness is not built yet'


def test_a4_1_frozen_pilot_and_core_modules_unmodified():
    try:
        done = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no', '--', *FROZEN_PATHS],
                              cwd=str(H.REPO), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pytest.skip('git unavailable')
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == '', f'frozen files modified:\n{done.stdout}'


def test_a4_1_independent_ops_directory_has_the_four_operations():
    ops = H.REPO / 'bench' / 'ozmap_rep' / 'ops'
    for name in ('ops.md', 'oracle.py', 'data.py', 'test_ops.py'):
        assert (ops / name).exists(), name
    from bench.ozmap_rep.ops import oracle
    assert tuple(oracle.OPS) == ('verdict', 'margin', 'elong', 'temp_class')
