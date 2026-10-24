"""Fixtures for the blind acceptance tests. Helpers live in ozrep_helpers.py; the guard is described in INTERFACE.md."""
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ozrep_helpers as H  # noqa: E402


@pytest.fixture
def baseline(tmp_path):
    """An authentication only baseline whose access token expires in 10 days."""
    directory = tmp_path / 'baseline'
    H.write_auth(directory, H.auth_doc(H.now_utc() + dt.timedelta(days=10)))
    return directory


@pytest.fixture
def summary():
    return H.passing_summary()
