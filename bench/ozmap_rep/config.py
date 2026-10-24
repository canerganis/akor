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
                    'workspace_dependencies')
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
# A4.13.1: preparation and review caps, cumulative from the start of the replication.
PREP_CAPS = {'astra': 20, 'opus': 40, 'fable': 4, 'sonnet': 40}
GLOBAL_CAP = 206
LEDGER_FILE = REPO / 'docs' / 'design' / 'ozmap-replication-2026-10-24' / 'call-ledger.jsonl'

MAX_BATCH = 64
AUDITS = 32
SLOTS = 4
CALL_TIMEOUT_S = 1200

# A4.12 and A4.2.
CODEX_STOP_PERCENT = 80
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

# Exit codes of `run cell` (INTERFACE.md); 12 to 14 are harness additions recorded in build-notes.md.
EXIT_OK, EXIT_USAGE, EXIT_ALREADY, EXIT_REQUIRES, EXIT_INCOMPLETE = 0, 2, 3, 4, 5
EXIT_QUOTA, EXIT_AUTH_GATE, EXIT_AUTH_STOP, EXIT_TELEMETRY, EXIT_FREEZE, EXIT_INTERRUPTED = 10, 11, 12, 13, 14, 75
