"""oz map adapter for the Claude CLI: the frozen claude_cli_adapter.py plus route identity (amendment D7).

The frozen adapter is imported, never copied or edited: its reply reduction and usage accounting are reused as they are.
This wrapper adds what the frozen one lacks:
 * the effort: OZ_EFFORT is passed as `claude --effort`; without it no flag is sent and the identity says "default";
 * `--identity`: one JSON line with the effective backend, model, effort, `claude --version` and the flags, no model call;
 * a missing `claude` executable exits 127 with an explicit diagnostic;
 * tool-use detection (council 3 close, Opus N1): the call runs with `--tools ''` (no built-in tool exists),
   `--setting-sources ''` (no settings, hooks or permissions are loaded) and `--strict-mcp-config` without an MCP
   config (no MCP tool exists). The CLI's result envelope still reports `num_turns` and `permission_denials`; a call
   with more than one turn or any permission denial used, or tried to use, a tool. It exits EXIT_LEAKAGE (86) with
   `oz-leakage:` on stderr and no reply, so its answers are never accepted; the raw envelope (with its usage) is still
   published to OZ_ENVELOPE_PATH, and the host marks the run's efficiency invalid.
The call itself is the frozen adapter's call (same flags, same 300 second timeout, same OZ_ENVELOPE_PATH capture).
"""
import json, os, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_cli_adapter as frozen

FLAGS = ('-p', '--tools', '', '--setting-sources', '', '--strict-mcp-config', '--no-session-persistence',
         '--output-format', 'json')
MISSING = 'claude executable not found on PATH; install Claude Code or fix PATH'
EXIT_LEAKAGE = 86


def cli_version(exe):
    try:
        done = subprocess.run([exe, '--version'], capture_output=True, text=True, encoding='utf-8', timeout=30,
                              stdin=subprocess.DEVNULL)
        return (done.stdout.strip() or done.stderr.strip() or 'unknown')[:200]
    except (OSError, subprocess.SubprocessError) as exc:
        return f'unknown ({type(exc).__name__})'


def command(exe, model, effort, system):
    """The exact claude argv of one call: tools disabled (`--tools ''`), no settings, no MCP servers."""
    return [exe, '-p', '--model', model, *(['--effort', effort] if effort else []), '--system-prompt', system,
            *FLAGS[1:]]


def tool_use(data):
    """[reason, ...] when the CLI result envelope shows tool use or a tool attempt; [] for one plain turn."""
    if not isinstance(data, dict):
        return []
    found = []
    turns = data.get('num_turns')
    if type(turns) is int and turns != 1:
        found.append(f'num_turns={turns}')
    denials = data.get('permission_denials')
    if isinstance(denials, list) and denials:
        found.append(f'permission_denials={len(denials)}')
    # usage_from_envelope sums every modelUsage entry, so a model other than the pinned one is extra work to flag.
    pinned = os.environ.get('OZ_MODEL', 'claude-sonnet-5-5')
    usage = data.get('modelUsage')
    if isinstance(usage, dict):
        found += [f'unexpected_model={name}' for name in sorted(usage) if not str(name).startswith(pinned)]
    return found


def main():
    model = os.environ.get('OZ_MODEL', 'claude-sonnet-5-5')
    effort = os.environ.get('OZ_EFFORT') or None
    exe = shutil.which('claude')
    if exe is None:
        sys.stderr.write(MISSING)
        sys.exit(127)
    if '--identity' in sys.argv:
        json.dump({'backend': 'claude', 'model': model, 'effort': effort or 'default', 'effort_applicable': True,
                   'cli_version': cli_version(exe), 'flags': list(FLAGS) + (['--effort'] if effort else [])},
                  sys.stdout)
        return
    request = json.load(sys.stdin)
    proc = subprocess.run(command(exe, model, effort, request['system']), input=request['prompt'],
                          capture_output=True, text=True, encoding='utf-8', timeout=300)
    if os.environ.get('OZ_ENVELOPE_PATH'):
        frozen._publish(os.environ['OZ_ENVELOPE_PATH'], proc.stdout.encode('utf-8'))
    data = json.loads(proc.stdout)
    leaked = tool_use(data)
    if leaked:
        sys.stderr.write('oz-leakage: the claude result envelope shows tool use: ' + ', '.join(leaked))
        sys.exit(EXIT_LEAKAGE)
    json.dump(frozen.reduce(data), sys.stdout)


if __name__ == '__main__':
    main()
