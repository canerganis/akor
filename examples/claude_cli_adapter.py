"""oz.adapter/3 stdio adapter: the request's system goes to --system-prompt, the prompt to stdin of `claude -p`."""
import json, os, shutil, subprocess, sys

request = json.load(sys.stdin)
model = os.environ.get('OZ_MODEL', 'claude-sonnet-5-5')
proc = subprocess.run([shutil.which('claude'), '-p', '--model', model, '--system-prompt', request['system'],
                       '--tools', '', '--setting-sources', '', '--strict-mcp-config', '--no-session-persistence',
                       '--output-format', 'json'], input=request['prompt'], capture_output=True, text=True,
                      encoding='utf-8', timeout=300)
data = json.loads(proc.stdout)
# `usage` covers only the last turn; modelUsage sums the whole call (all turns, all models, subagents).
mu = data.get('modelUsage') or {}
total = lambda key: sum(m.get(key, 0) for m in mu.values())
if mu:
    u = {'input_tokens': total('inputTokens'), 'cache_read_input_tokens': total('cacheReadInputTokens'),
         'cache_creation_input_tokens': total('cacheCreationInputTokens'), 'output_tokens': total('outputTokens')}
else:
    u = data['usage']
usage = {'input_tokens': u['input_tokens'] + u['cache_creation_input_tokens'] + u['cache_read_input_tokens'],
         'cached_input_tokens': u['cache_read_input_tokens'],
         'cache_creation_input_tokens': u['cache_creation_input_tokens'],
         'output_tokens': u['output_tokens']}
# The reply is the model's raw text (stage 1g: the line OZ/1g, then one {"id":result} or [id,"error",code,message] JSON record per job); the worker parses and validates it.
json.dump({'reply': data['result'], 'usage': usage}, sys.stdout)
