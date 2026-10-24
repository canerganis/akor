"""A4.12: operational stops. Codex stops at primary used_percent >= 80, Claude handoff at 99% weekly."""
import json
import os
import time

import pytest

from ozrep_helpers import harness, need


def session_file(root, name, percent, day='2026/10/24', mtime=None, extra_lines=()):
    folder = root / day
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    lines = list(extra_lines)
    lines.append(json.dumps({'timestamp': '2026-10-24T12:00:00Z', 'type': 'event_msg', 'payload': {
        'type': 'token_count', 'info': None,
        'rate_limits': {'limit_id': 'codex', 'primary': {'used_percent': percent, 'window_minutes': 10080,
                                                         'resets_at': 1793382106}, 'secondary': None}}}))
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_a4_12_thresholds_are_the_retained_ones():
    cfg = harness('config')
    assert need(cfg, 'CODEX_STOP_PERCENT') == 80
    assert need(cfg, 'CLAUDE_HANDOFF_PERCENT') == 99
    assert need(cfg, 'EXP_MARGIN_HOURS') == 48


@pytest.mark.parametrize('percent,ok', [(0.0, True), (38.0, True), (79.9, True), (80.0, False), (80.1, False),
                                        (100.0, False)])
def test_a4_12_codex_stops_at_primary_used_percent_80(tmp_path, percent, ok):
    gate = need(harness('quota'), 'codex_gate')
    session_file(tmp_path, 'rollout-a.jsonl', percent)
    out = gate(tmp_path)
    assert out['ok'] is ok and out['percent'] == percent


def test_a4_12_the_newest_session_file_is_read_not_the_oldest(tmp_path):
    gate = need(harness('quota'), 'codex_gate')
    now = time.time()
    session_file(tmp_path, 'rollout-old.jsonl', 95.0, day='2026/10/20', mtime=now - 5000)
    session_file(tmp_path, 'rollout-new.jsonl', 12.0, day='2026/10/24', mtime=now)
    assert gate(tmp_path)['ok'] is True and gate(tmp_path)['percent'] == 12.0
    session_file(tmp_path, 'rollout-newer.jsonl', 81.0, day='2026/10/22', mtime=now + 100)
    assert gate(tmp_path)['ok'] is False


def test_a4_12_the_last_rate_limits_object_in_the_file_wins(tmp_path):
    gate = need(harness('quota'), 'codex_gate')
    early = json.dumps({'type': 'event_msg', 'payload': {'rate_limits': {'primary': {'used_percent': 90.0}}}})
    session_file(tmp_path, 'rollout-a.jsonl', 40.0, extra_lines=[early, 'not json at all'])
    assert gate(tmp_path)['percent'] == 40.0 and gate(tmp_path)['ok'] is True


def test_a4_12_unreadable_usage_is_a_stop_not_a_pass(tmp_path):
    gate = need(harness('quota'), 'codex_gate')
    assert gate(tmp_path)['ok'] is False  # no sessions at all
    folder = tmp_path / '2026' / '10' / '24'
    folder.mkdir(parents=True)
    (folder / 'rollout-x.jsonl').write_text('{"type":"event_msg","payload":{}}\n', encoding='utf-8')
    out = gate(tmp_path)
    assert out['ok'] is False and out['percent'] is None


@pytest.mark.parametrize('percent,ok', [(0, True), (63, True), (98.9, True), (99, False), (100, False)])
def test_a4_12_claude_handoff_at_99_percent_weekly(percent, ok):
    gate = need(harness('quota'), 'claude_gate')
    out = gate(percent)
    assert out['ok'] is ok
    if not ok:
        assert out['reason']


def test_a4_12_unknown_claude_usage_is_a_stop():
    assert need(harness('quota'), 'claude_gate')(None)['ok'] is False
