"""Frozen constants of the oz map clean replication (Amendment 4, A4.13). Standard library only.

Every number here is quoted from docs/design/ozmap-replication-2026-10-24/amendment-4.md (A4.x) or
amendment-4-13-caps.md (A4.13.x). build-notes.md maps each clause to the line that implements it.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

# A4.8: Fable's four independent operations replace the original materials operations.
OPERATIONS = ('verdict', 'margin', 'elong', 'temp_class')
BOOLQ_OP = 'boolq'
SEED = 20261024
PRODUCERS = ('p0', 'p1', 'p2', 'p3')
PER_PRODUCER = 64
BOOTSTRAP_PER_PRODUCER = 16

# A4.2 and A4.7: the frozen route.
CODEX_MODEL = 'gpt-6.1-sol'
CODEX_EFFORT = 'high'
CODEX_CLI_VERSION = 'codex-cli 0.160.0'
SONNET_MODEL = 'claude-sonnet-5-5'
SONNET_EFFORT = None  # the pilot route: effort default (A4.9 keeps Sonnet's pilot prompt and flags)
ROUTE = {'model': CODEX_MODEL, 'effort': CODEX_EFFORT, 'cli_version': CODEX_CLI_VERSION}

# A4.2: the frozen argument head. The canonical argv is
# [exe, *FROZEN_ARGS, <numbered empty dir>, '-m', model, '-c', 'model_reasoning_effort="<effort>"', *disable, '-'].
FROZEN_ARGS = ['exec', '--ignore-user-config', '--ignore-rules', '--ephemeral', '--skip-git-repo-check', '--json',
               '-s', 'read-only', '-C']
# A4.2: the named features plus every other tool feature codex-cli 0.160.0 lists (cli-flags.json records which ones
# the pinned CLI accepts and which stay enabled).
DISABLE_FEATURES = ('plugins', 'apps', 'memories', 'hooks', 'multi_agent', 'skill_search', 'browser_use',
                    'computer_use', 'image_generation', 'view_image',
                    'shell_tool', 'unified_exec', 'unified_exec_tty', 'browser_use_external',
                    'browser_use_full_cdp_access', 'in_app_browser', 'code_mode_host', 'remote_plugin',
                    'plugin_sharing', 'recommended_plugins', 'skill_mcp_dependency_install', 'tool_suggest',
                    'tool_call_mcp_elicitation', 'sleep_tool', 'multi_agent_v2', 'shell_snapshot',
                    'workspace_dependencies', 'secret_auth_storage')
# Council round 2 (items 1, B4, 33; joint decision of the round 2 deadlock): the route security arguments that follow
# the effort argument on every Codex argv. `cli_auth_credentials_store="file"` selects auth.json under CODEX_HOME as
# the only credential store and `skip_host_skill_discovery` turns host skill discovery off (P5); both were accepted by
# codex-cli 0.160.0 in local commands (cli-flags.json, route_security_options). `secret_auth_storage` is disabled
# with the tool features above.
#
# P5 repair (2026-10-25, request boundary probe): on the exec route codex-cli 0.160.0 still lists the owner's
# ~/.agents/skills (resolved from the OS profile, not from CODEX_HOME, HOME or USERPROFILE) and the bundled
# CODEX_HOME skills/.system in the model request although skip_host_skill_discovery is on. `skills.include_instructions
# =false` removes the skills instructions item from the request and `skills.bundled.enabled=false` stops the bundled
# skill set from being written or listed (rulings/P5-effective-context-evidence.json). Both are `-c` overrides, which
# --ignore-user-config does not ignore.
#
# P5 repair 2 (2026-10-25, blocker OB-P5b fix 1): the model metadata is pinned. On the live route the CLI fetches
# /models and the answer can change the base instructions and tools of the frozen model. MODEL_CATALOG_FILE holds the
# catalog bundled in the pinned executable, byte for byte (extracted from codex.exe of codex-cli 0.160.0, sha256
# MODEL_CATALOG_SHA256); `-c model_catalog_json=<that file>` makes the CLI use it and never fetch /models (request
# boundary probe: no /models request with the pin, and a canary /models answer reaches the request only without it).
# isolation.verify_launch checks the file's hash before every Codex launch.
MODEL_CATALOG_FILE = HERE / 'model-catalog.json'
MODEL_CATALOG_SHA256 = '1d39994d11492a3c692c060c621e5c0f01213e18f06fcb5407fcd7d824ebd536'
MODEL_CATALOG_ARG = f"model_catalog_json='{MODEL_CATALOG_FILE}'"
ROUTE_SECURITY_ARGS = ['-c', 'cli_auth_credentials_store="file"', '--enable', 'skip_host_skill_discovery',
                       '-c', 'skills.include_instructions=false', '-c', 'skills.bundled.enabled=false',
                       '-c', MODEL_CATALOG_ARG]
# P5 repair 2 (fix 3): the approved effective context of the frozen route, item by item (effective_context.py).
EFFECTIVE_CONTEXT_FILE = HERE / 'effective-context.json'
PROJECT_DOC_OPTION = 'project_doc_max_bytes'
PROJECT_DOC_ARG = 'project_doc_max_bytes=0'
CLI_FLAGS_FILE = HERE / 'cli-flags.json'

# A4.2: the allowlisted child environment. CODEX_HOME is set by the harness; HOME and USERPROFILE point at the worker
# home for Codex children, so no owner home is reachable through them.
ENV_ALLOWLIST = ('PATH', 'PATHEXT', 'SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'HOME',
                 'USERPROFILE', 'LANG', 'LC_ALL', 'TZ', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'OS')
# Sonnet keeps its pilot route: it authenticates from the owner's Claude login, so its children also get the
# profile directories. API keys are never passed.
SONNET_ENV_EXTRA = ('APPDATA', 'LOCALAPPDATA')

# A4.4 and A4.5: allocations, reserves and caps.
ALLOCATIONS = {
    'codex/materials': {'cold_A': 4, 'bootstrap': 1, 'cold_B': 8, 'cold_C': 4, 'warm_A': 4, 'warm_C': 5},
    'sonnet/materials': {'cold_A': 4, 'bootstrap': 1, 'cold_B': 8, 'cold_C': 4, 'warm_A': 4, 'warm_C': 5},
    'codex/boolq': {'cold_A': 4, 'bootstrap': 1, 'cold_B': 4, 'cold_C': 3},
}
RESERVE_PER_ALLOCATION = 2
RESERVE_REASONS = ('infrastructure_retry', 'audit_overflow')
RESERVE_FORBIDDEN = ('new_learning', 'answer_repair', 'new_condition')
EVAL_CAPS = {'codex': {'nominal': 38, 'telemetry': 4, 'reserve': 20, 'total': 62},
             'sonnet': {'nominal': 26, 'telemetry': 2, 'reserve': 12, 'total': 40}}
# A4.13.1 with revision 1 (A4.13r1.1, signed by Astra A and Opus B, amendment-4-13-caps.md): preparation and review
# caps, cumulative from the start of the replication. The Opus cap becomes 70 and the global cap 236.
PREP_CAPS = {'astra': 20, 'opus': 70, 'fable': 4, 'sonnet': 40}
GLOBAL_CAP = 236
LEDGER_FILE = REPO / 'docs' / 'design' / 'ozmap-replication-2026-10-24' / 'call-ledger.jsonl'

MAX_BATCH = 64
AUDITS = 32
SLOTS = 4
CALL_TIMEOUT_S = 1200

# A4.12 and A4.2.
CODEX_STOP_PERCENT = 80
# P3 repair (2026-10-25): the bucket and freshness rule of the quota source manifest
# (rulings/P3-quota-source-manifest.json, bucket_identity and freshness_rule). A reading counts only for limit_id
# `codex` with a primary window of 10080 minutes, and the latest owner reading must carry an event timestamp at most
# QUOTA_OWNER_MAX_AGE_MINUTES before the gate time.
QUOTA_LIMIT_ID = 'codex'
QUOTA_WINDOW_MINUTES = 10080
QUOTA_OWNER_MAX_AGE_MINUTES = 60
CLAUDE_HANDOFF_PERCENT = 99
EXP_MARGIN_HOURS = 48
BASELINE_DEFAULT = Path.home() / '.ozmap_rep' / 'baseline'
RUNS_DEFAULT = Path.home() / '.ozmap_rep' / 'runs'
BASELINE_INVENTORY_FILE = HERE / 'baseline-inventory.json'
CODEX_SESSIONS_DEFAULT = Path.home() / '.codex' / 'sessions'

# A4.6: the frozen classification (from expressibility-review.md), and A4.7: the archived cache certificate.
CLASSIFICATION_FILE = HERE / 'classification.json'
CERTIFICATE_FILE = HERE / 'certificate' / 'cache-certificate.json'
FREEZE_FILE = HERE / 'freeze.json'

# Sign-off 5 reasoning predicate: o200k_base through tiktoken 0.14.0 with the pinned vocabulary file (pilot freeze).
TOKENIZER = {'tiktoken': '0.14.0', 'encoding': 'o200k_base',
             'cache_files': {'fb374d419588a4632f3f557e76b4b70aebbca790':
                             '446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d'}}
TOKENIZER_PYTHON = REPO / '.venv' / 'Scripts' / 'python.exe'

INPUT_POLICY = {'version': 'oz-input/1', 'terminal_newline': 'strip_one', 'text_ref': 0}

# Exit codes of `run cell` (INTERFACE.md); 12 and above are harness additions recorded in build-notes.md.
EXIT_OK, EXIT_USAGE, EXIT_ALREADY, EXIT_REQUIRES, EXIT_INCOMPLETE = 0, 2, 3, 4, 5
EXIT_QUOTA, EXIT_AUTH_GATE, EXIT_AUTH_STOP, EXIT_TELEMETRY, EXIT_FREEZE, EXIT_INTERRUPTED = 10, 11, 12, 13, 14, 75
EXIT_IDENTITY, EXIT_BUSY, EXIT_SAFETY_KILL, EXIT_CLASSIFICATION = 15, 16, 17, 18
# A4.14.1 (fail closed execution): 19 the cell was interrupted (or settled) earlier and is never resumed or rerun;
# 20 the run is stopped because containment of outstanding work from an interrupted cell was not established, so no
# further cell is admitted.
EXIT_CELL_INTERRUPTED, EXIT_RUN_STOPPED = 19, 20

# Council round 1: the live run directory and the experiment ledger. Live cells run only in the canonical run
# directory (freeze.json may name another one, which needs a new freeze and a recorded council disposition), and every
# live charge is also appended to the experiment ledger outside every run directory, so a new or emptied run
# directory never grants a fresh allocation (RT1.5, item 9).
# Red team round 3 (RT3.1): the live run directory, and with it every worker home and working directory, sits outside
# the owner profile, so no ancestor of a live working directory holds the owner's .codex, .claude or .agents state.
LIVE_RUN_DIR_DEFAULT = Path(Path.home().anchor or '/') / 'ozmap_rep' / 'runs' / 'replication'
LIVE_LEDGER_DEFAULT = RUNS_DEFAULT / 'live-calls.jsonl'

# Signed exceptions (council rounds 1 and 2). Each entry needs a prospective ruling signed by Astra A and Opus B before
# the freeze; all are empty until then, which is the strict reading of A4.2 and A4.3. The round 2 deadlock texts P1 to
# P5 are signed by Astra A only (council-build-deadlock-r2-joint.md section 3) and bind after Opus B confirms them by
# diff; freeze_command refuses until every slot in REQUIRED_RULINGS names its countersigned file (rulings.py).
#
# P1 (A4.3): complete transport event messages (exact match, never a prefix) that are transport events when the stream
# holds no tool item. Astra's P1: empty for codex-cli 0.160.0; every reconnect or fallback event is uncertain.
SIGNED_TRANSPORT_NOTICES = ()
# P4 (A4.3, A4.2): complete CLI notice messages (exact match) of an `item.completed` error item. Inactive until the
# outer event fixture (SIGNED_CLI_NOTICE_EVENT_KEYS) and the identifier syntax (SIGNED_CLI_NOTICE_ID_RE) are approved
# by both signatories; the candidate text is archived in build-notes.md (Fable F6).
SIGNED_CLI_NOTICES = ()
SIGNED_CLI_NOTICE_EVENT_KEYS = None
SIGNED_CLI_NOTICE_ID_RE = None
P4_CANDIDATE_NOTICE = ('Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed; '
                       'enable `features.code_mode_host` and install `codex-code-mode-host`.')
# Disable options that may be left out of the frozen argv, with the signed document that authorizes it (item 8). The
# joint decision keeps code_mode_host disabled, so this stays empty.
SIGNED_OMITTED_DISABLES = {}
# P5 (A4.2): the approved startup manifest (exact canonical relative paths with sha256, file type, origin and role),
# approved by both signatories before the freeze. Absent: no startup file is accepted.
STARTUP_MANIFEST_FILE = HERE / 'startup-manifest.json'
# Instruction bearing runtime file patterns (relative to CODEX_HOME) inspected by the telemetry certificate. A file
# matching one is accepted only when its path and sha256 are in the approved startup manifest.
INSTRUCTION_BEARING = ('AGENTS.md', 'AGENTS.override.md', 'CLAUDE.md', '*.md', 'skills/*', 'skills/**/*',
                       'memories/*', 'rules/*', 'prompts/*', 'plugins/*', 'hooks/*', 'instructions*')
# B1 (freeze refusal): the ruling slots that must be settled before `run freeze`, each as
# {'path': <repo relative ruling file>, 'sha256': <hash of the exact countersigned bytes>}. Empty until signed.
# Closure round 1 (O5, Astra 32): D6, the focused verification and the independent operation attestation, is a
# launch prerequisite bound like the other slots (rulings.ANNEXES_REQUIRED, rulings.d6_problems).
REQUIRED_RULINGS = ('P1', 'P2', 'P3', 'P4', 'P5', 'D1', 'D6')
SIGNED_RULINGS = {}
# P3 (A4.12): worker calls keep `--ephemeral`: A4.2 names it in the frozen arguments and the blind acceptance suite
# tests it. Omitting it needs P3 countersigned by Opus B, which only permits it with a certified persistence and
# harvest lifecycle. Isolation.finish harvests the quota metadata of any worker rollout before the home is emptied.
