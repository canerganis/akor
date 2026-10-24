"""Red team round 3 against the replication harness (bench/ozmap_rep) after the council round 2 fixes (fc60457).

Every test here is expected to FAIL on fc60457 and to pass once the finding it names is fixed. Findings and fixes:
docs/design/ozmap-replication-2026-10-24/council-build-redteam-r3.md.

Fakes and temporary directories only: no real `codex` or `claude` is resolved or spawned (live mode runs the harness'
own fakes through the real lifecycle code, as in test_redteam_r2.Live), Path.home() is redirected to a temporary
owner profile wherever the harness would read the owner's authentication, no real baseline, run directory, experiment
ledger, owner home or Codex session directory is read or written, and the sealed reviewer ASTs are never touched.
"""
import base64
import datetime as dt
import json
import os
from pathlib import Path
import time

import pytest

from bench.ozmap_rep import config, isolation, run

from test_redteam_r2 import Live  # noqa: E402  (the round 2 live-on-fakes construction, reused unchanged)


# ------------------------------------------------------------------------------------------------------- helpers

def _b64(obj):
    raw = obj if isinstance(obj, bytes) else json.dumps(obj, sort_keys=True).encode('utf-8')
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def jwt(claims, sig='sig'):
    """A syntactically valid JWT with an RS256 header and a dummy signature (no key, no secret)."""
    return '.'.join([_b64({'alg': 'RS256', 'typ': 'JWT'}), _b64(claims), _b64(sig.encode())])


def auth_doc(*, session, auth_time, iat, jti, refresh, last_refresh):
    """An auth.json of one ChatGPT login. `session` and `auth_time` identify the login (they survive a refresh);
    `iat`, `jti` and the refresh token change at every rotation."""
    exp = int((dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=9)).timestamp())
    auth = {'chatgpt_account_id': 'acct-redteam', 'chatgpt_plan_type': 'pro', 'user_id': 'user-redteam'}
    access = jwt({'exp': exp, 'iat': iat, 'jti': jti, 'session_id': session, 'pwd_auth_time': auth_time * 1000,
                  'https://api.openai.com/auth': auth, 'scp': ['openid', 'offline_access']})
    id_token = jwt({'exp': iat + 3600, 'iat': iat, 'auth_time': auth_time, 'sid': session, 'email': 'r@t.example',
                    'https://api.openai.com/auth': auth})
    return {'auth_mode': 'chatgpt', 'OPENAI_API_KEY': None, 'last_refresh': last_refresh,
            'tokens': {'id_token': id_token, 'access_token': access, 'refresh_token': refresh,
                       'account_id': 'acct-redteam'}}


def write_auth(directory, doc):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'auth.json').write_text(json.dumps(doc), encoding='utf-8')
    return directory / 'auth.json'


def owner_profile(tmp_path, monkeypatch, with_auth=True):
    """A temporary owner profile as Path.home(): ~/.codex with a separate login of its own (or none)."""
    owner = tmp_path / 'owner-profile'
    (owner / '.codex').mkdir(parents=True, exist_ok=True)
    (owner / '.codex' / 'config.toml').write_text('model = "gpt-6-astra"\n', encoding='utf-8')
    if with_auth:
        write_auth(owner / '.codex', auth_doc(session='authsess_owner', auth_time=1760000000, iat=1761000000,
                                              jti='owner-jti', refresh='rt_owner_current',
                                              last_refresh='2026-10-15T18:40:00Z'))
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: owner))
    return owner


def launch_fixture(root):
    """A worker home holding only auth.json and an empty numbered working directory, laid out like the live run
    directory under a profile (<profile>/.ozmap_rep/runs/replication/{homes/worker-0, work/slot-0}), and the canonical
    argv, environment and frozen hashes for isolation.verify_launch."""
    d = Path(root) / '.ozmap_rep' / 'runs' / 'replication'
    home, work = d / 'homes' / 'worker-0', d / 'work' / 'slot-0'
    home.mkdir(parents=True)
    work.mkdir(parents=True)
    run.synthetic_baseline(home)
    exe = (Path(root) / 'bin' / 'codex.exe').resolve()
    argv = isolation.codex_argv(exe, config.CODEX_MODEL, config.CODEX_EFFORT, work, [])
    env = isolation.child_env(home, {'SYSTEMROOT': 'C:\\Windows'})
    frozen = {'argv_sha256': isolation.argv_sha256(argv), 'exe_sha256': 'e' * 64}
    return {'argv': argv, 'env': env, 'workdir': work, 'exe_sha256': 'e' * 64, 'frozen': frozen}


# ======================================= RT3.1: discovery locations of the pinned CLIs in an ancestor are not checked

# Locations the pinned codex-cli 0.160.0 names in its capability discovery string table (exec-server
# src\discoverV2\capability_locations.rs: `.agents/skills`, `.codex/config.toml`, `.codex/agents`, `.codex/hooks`,
# `mcp.json`, with `.git` as the project root marker), and the Claude Code memory and rule files besides CLAUDE.md.
DISCOVERY_FILES = {
    'agents_skills': '.agents/skills/callister-materials-science/SKILL.md',
    'codex_skills': '.codex/skills/tensile/SKILL.md',
    'codex_config': '.codex/config.toml',
    'codex_agents': '.codex/agents/helper.toml',
    'codex_hooks': '.codex/hooks/session_start.toml',
    'mcp_json': 'mcp.json',
    'claude_dir_memory': '.claude/CLAUDE.md',
    'claude_local_memory': 'CLAUDE.local.md',
    'claude_rules': '.claude/rules/materials.md',
}


@pytest.mark.parametrize('name', sorted(DISCOVERY_FILES))
def test_rt3_1_a_discovery_location_in_an_ancestor_blocks_the_launch(tmp_path, name):
    """A4.2: "Before every call, verify ... effective instruction sources, including ancestors. Mismatch prevents
    launch. If instruction discovery cannot be contained, use an isolated account or container." The pre-launch check
    (isolation.instruction_scan, used by verify_launch for Codex and by prepare_call for Sonnet) looks only for
    AGENTS.md, AGENTS.override.md and CLAUDE.md. Skills, project configuration, custom agents, hooks, MCP server
    lists and Claude memory or rule files in the working directory's ancestors pass, although the pinned CLIs know
    these locations. The live working directories sit under the owner profile, which holds exactly such locations."""
    fx = launch_fixture(tmp_path / 'profile')
    clean = isolation.verify_launch(argv=fx['argv'], env=fx['env'], workdir=fx['workdir'],
                                    exe_sha256=fx['exe_sha256'], frozen=fx['frozen'])
    assert clean == [], f'fixture is not a clean launch: {clean}'
    rel = DISCOVERY_FILES[name]
    planted = tmp_path / 'profile' / rel
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text('Use this when the task mentions tensile tests.\n', encoding='utf-8')
    problems = isolation.verify_launch(argv=fx['argv'], env=fx['env'], workdir=fx['workdir'],
                                       exe_sha256=fx['exe_sha256'], frozen=fx['frozen'])
    found, unreadable = isolation.instruction_scan(fx['workdir'])
    assert problems, (f'{rel} in an ancestor of the working directory passed every pre-launch check (A4.2): '
                      f'verify_launch {problems}, instruction_scan found {found} unreadable {unreadable}')


def test_rt3_1_the_live_working_directories_are_not_below_the_owner_profile():
    """The default live run directory is Path.home()/.ozmap_rep/runs/replication, so every live working directory
    (D/work/slot-<k>) has the owner profile as an ancestor: the directory that holds ~/.codex, ~/.agents/skills and
    ~/.claude by definition. User scope discovery that resolves the profile from the OS (not from HOME or
    USERPROFILE, which the harness overrides) and any ancestor walk reach the owner's skills and configuration."""
    work = config.LIVE_RUN_DIR_DEFAULT / 'work' / 'slot-0'
    home = Path.home().resolve()
    assert home not in work.resolve().parents, (
        f'the live working directory {work} is below the owner profile {home} (A4.2: use a location without owner '
        f'discovery state in any ancestor, or an isolated account or container)')


# ================================== RT3.2: token separation is exact hash equality, so a rotated copy is "separate"

def test_rt3_2_a_rotated_copy_of_the_owner_login_is_not_a_separate_login(tmp_path):
    """RT2.6 asked that a baseline seeded by copying the owner's auth.json never reaches a worker. The fix compares
    SHA256 of the access and refresh token strings only. The owner's Codex app rotates both at its next refresh, so a
    copy taken before that rotation (the same login: same session and auth_time, older access token, the refresh
    token the owner already spent) passes. Its first worker refresh presents an already used refresh token of the
    owner's login, the reuse the pinned CLI reports as "refresh token was already used" and that a rotating
    authorization server answers by revoking the login family, the owner's current tokens included."""
    owner = write_auth(tmp_path / 'owner' / '.codex', auth_doc(
        session='authsess_owner', auth_time=1760000000, iat=1761200000, jti='after-rotation',
        refresh='rt_owner_after_rotation', last_refresh='2026-10-15T18:40:00Z'))
    separate = tmp_path / 'separate-baseline'
    write_auth(separate, auth_doc(session='authsess_baseline', auth_time=1761300000, iat=1761300000,
                                  jti='baseline-login', refresh='rt_baseline_own', last_refresh='2026-10-24T15:18:00Z'))
    assert isolation.token_separation_problems(separate, [owner]) == [], 'control: a separate login must pass'
    stale_copy = tmp_path / 'stale-copy-baseline'
    write_auth(stale_copy, auth_doc(session='authsess_owner', auth_time=1760000000, iat=1760900000,
                                    jti='before-rotation', refresh='rt_owner_before_rotation',
                                    last_refresh='2026-10-07T09:00:00Z'))
    problems = isolation.token_separation_problems(stale_copy, [owner])
    assert problems, ('a baseline copied from the owner auth.json before the owner\'s next token rotation (same login '
                      'session and auth_time) passes the token separation check (A4.2, RT2.6)')


def test_rt3_2_an_owner_credential_outside_auth_json_is_never_treated_as_separate(tmp_path):
    """The joint decision of the round 2 deadlock: "an unreadable existing source or unexplained credential
    representation is never treated as different". cli-flags.json records secret_auth_storage as a stable feature,
    enabled by default, for the owner's own CLI (the frozen argv disables it for workers only). An owner profile whose
    ~/.codex holds configuration but no auth.json (credentials in the OS store) is an unexplained representation, yet
    token_hashes returns {} and the separation check passes with nothing compared."""
    owner_codex = tmp_path / 'owner' / '.codex'
    owner_codex.mkdir(parents=True)
    (owner_codex / 'config.toml').write_text('model = "gpt-6-astra"\n', encoding='utf-8')
    base = tmp_path / 'baseline'
    write_auth(base, auth_doc(session='authsess_owner', auth_time=1760000000, iat=1760900000, jti='copy',
                              refresh='rt_copy', last_refresh='2026-10-07T09:00:00Z'))
    problems = isolation.token_separation_problems(base, [owner_codex / 'auth.json'])
    assert problems, ('the owner Codex home holds no auth.json (credential kept elsewhere, unexplained) and the token '
                      'separation check passed without comparing anything')


# ========================== RT3.3: the live Codex quota stop reads whatever sessions directory the command line names

def test_rt3_3_the_live_quota_stop_reads_the_owner_sessions_not_a_named_directory(tmp_path, monkeypatch):
    """A4.12: Codex stops at primary used_percent >= 80, read from the owner's Codex sessions. `run cell`,
    `telemetry` and `features` accept --codex-sessions-dir in live mode, and the P3 gate reads that directory alone.
    Neither evidence/quota.jsonl nor evidence/quota-gates.jsonl records which directory or file the reading came
    from, so the scorer cannot tell. Here the owner's sessions hold an 85% reading and the named directory a 10% one:
    the telemetry probe and call are both launched and the evidence shows only `percent: 10`."""
    owner_profile(tmp_path, monkeypatch)
    live = Live(tmp_path, monkeypatch)
    owner_sessions = tmp_path / 'owner-sessions'
    folder = owner_sessions / '2026' / '10' / '25'
    folder.mkdir(parents=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    (folder / 'rollout-owner.jsonl').write_text(json.dumps(
        {'timestamp': stamp, 'type': 'event_msg', 'payload': {'type': 'token_count', 'rate_limits': {
            'primary': {'used_percent': 85.0}}}}) + '\n', encoding='utf-8')
    monkeypatch.setattr(config, 'CODEX_SESSIONS_DEFAULT', owner_sessions)
    assert run.quota.codex_gate(config.CODEX_SESSIONS_DEFAULT)['ok'] is False, 'control: the owner reading is 85%'
    code = live.telemetry()
    launched = [a['call_id'] for a in run.jsonl(live.run_dir / 'attempts.jsonl') if a.get('outcome') != 'not_launched']
    gates = run.jsonl(live.run_dir / 'evidence' / 'quota-gates.jsonl')
    assert not launched, (f'with the owner reading at 85% the live telemetry launched {launched} (exit {code}) on a '
                          f'named sessions directory; quota gate evidence: {[{k: g.get(k) for k in ("ok", "percent")} for g in gates]}')
