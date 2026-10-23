"""oz.adapter/3 stdio adapter: the request's system goes to --system-prompt, the prompt to stdin of `claude -p`.

Accounting (foundation record clause 8): usage comes only from the envelope's `modelUsage`, which sums the whole call
(all turns, all models, subagents). When `modelUsage` is absent or empty, or any model entry lacks a required counter,
the call's usage is unknown and the response carries no `usage` at all; last-turn `usage` is never substituted and a
missing counter is never read as zero. When the runner sets OZ_ENVELOPE_PATH, the raw CLI envelope is published there
before the reduced response is printed, so the runner can keep it with the capture.
"""
import json, os, shutil, subprocess, sys

REQUIRED = (('inputTokens', 'input'), ('cacheReadInputTokens', 'cache_read'),
            ('cacheCreationInputTokens', 'cache_creation'), ('outputTokens', 'output'))


def usage_from_envelope(data):
    """Normalized usage from the envelope's modelUsage, or None when it is unknown."""
    mu = data.get('modelUsage') if isinstance(data, dict) else None
    if not isinstance(mu, dict) or not mu:
        return None
    sums = dict.fromkeys(name for _, name in REQUIRED)
    for entry in mu.values():
        if not isinstance(entry, dict):
            return None
        for key, name in REQUIRED:
            value = entry.get(key)
            if type(value) is not int or value < 0:
                return None
            sums[name] = (sums[name] or 0) + value
    return {'input_tokens': sums['input'] + sums['cache_creation'] + sums['cache_read'],
            'cached_input_tokens': sums['cache_read'],
            'cache_creation_input_tokens': sums['cache_creation'],
            'output_tokens': sums['output']}


def reduce(data):
    """The adapter response for one CLI envelope: the raw reply text, plus usage only when it is known."""
    response = {'reply': data['result']}
    usage = usage_from_envelope(data)
    if usage is not None:
        response['usage'] = usage
    return response


def _publish(path, data):
    temp = path + '.tmp'
    with open(temp, 'wb') as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, path)


def main():
    request = json.load(sys.stdin)
    model = os.environ.get('OZ_MODEL', 'claude-sonnet-5-5')
    proc = subprocess.run([shutil.which('claude'), '-p', '--model', model, '--system-prompt', request['system'],
                           '--tools', '', '--setting-sources', '', '--strict-mcp-config', '--no-session-persistence',
                           '--output-format', 'json'], input=request['prompt'], capture_output=True, text=True,
                          encoding='utf-8', timeout=300)
    if os.environ.get('OZ_ENVELOPE_PATH'):
        _publish(os.environ['OZ_ENVELOPE_PATH'], proc.stdout.encode('utf-8'))
    data = json.loads(proc.stdout)
    # The reply is the model's raw text (stage 1g: the line OZ/1g, then one {"id":result} or [id,"error",code,message]
    # JSON record per job); the worker parses and validates it.
    json.dump(reduce(data), sys.stdout)


if __name__ == '__main__':
    main()
