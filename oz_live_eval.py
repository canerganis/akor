"""Bounded, opt-in live comprehension smoke test through existing CLIs.

Only synthetic fixtures are supplied. No API keys are read or written here.
The first provider emits frames; the second classifies those exact frames.
This is not an end-to-end coding, quality, cost or latency benchmark.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from examples.oz_demo import example_channel
from oz import Atom, Channel, RULES, Error

ROOT = Path(__file__).parent
FIXTURES = [
    ('Review patch 7; preserve public API; run relevant tests; report failures.', 'a7'),
    ('Request missing reference 3; do not guess.', '?3'),
    ('Report passed tests using report 8, then mark assigned step complete.', '+8.'),
    ('Report failed tests using report 9; do not finish the step.', '-9'),
    ('Report hypothesis 10 as an inference, not a proven fact.', '~10'),
    ('Report that work is blocked for reason 11.', '!11'),
    ('Propose plan 12 without claiming it has been applied.', '>12'),
    ('Report the sourced observation in reference 13.', '=13'),
    ('Request execution of test procedure 14; do not claim an outcome.', 't14'),
    ('Request stopping this task.', '/'),
    ('Send this exact new information as a literal: 12.50 ± 0.02 mm; method unknown.', ':12.50 ± 0.02 mm; method unknown.'),
    ('Read source reference 13, retaining exact values and uncertainty.', 'r13'),
]
MACRO_FIXTURES = [
    ('Read patch 7 preserving constraints, then audit patch 7 preserving API and testing, then request test procedure 14.', 'V'),
    ('Read sourced observation 13 exactly, then propose plan 12 without applying it.', 'P'),
    ('Perform the read/audit/test-procedure request sequence on patch 7, then request missing reference 3.', 'V?3'),
    ('Request the read/audit/test sequence for patch 7, report the existing passed report 8, then mark the assigned step complete.', 'V+8.'),
    ('Report failed test report 9, then report inability to proceed for reason 11.', '-9!11'),
    ('Read reference 15 exactly; it says tests were not run. Do not claim success.', 'r15'),
    ('Request the read/audit/test sequence for patch 7, then read observation 13 and propose plan 12.', 'VP'),
    ('Send exactly this literal data, including its newline: V7 is data\n12.50 ± 0.02 mm; not validated.',
     ':V7 is data\n12.50 ± 0.02 mm; not validated.'),
]


def fixtures(suite='oz1'):
    return FIXTURES + MACRO_FIXTURES if suite == 'oz2' else FIXTURES


def setup_context(suite='oz1'):
    ch = example_channel()
    if suite == 'oz2':
        snapshot = ch.snapshot()
        snapshot['macros'] = [dict(code='V', steps=[vars(a) for a in (Atom('r', 0), Atom('a', 0), Atom('t', 14))]),
                              dict(code='P', steps=[vars(a) for a in (Atom('r', 13), Atom('>', 12))])]
        ch = Channel.from_snapshot(snapshot)
    all_atoms = [atom for _, wire in fixtures(suite) for atom in ch.accept(wire, binding=ch.binding)]
    return ch, ch.context(all_atoms)


def encode_prompt(suite='oz1'):
    ch, context = setup_context(suite)
    return ('This is a text-only language conformance test. Do not use tools, files, network or agents. '
            'Only supplied synthetic data matters. Return JSON {"frames":[string,...]} in case order, '
            f'with exactly {len(fixtures(suite))} strings. Each is an OZ frame, without explanations or Markdown. '
            'Use declared macros when their exact expansions match; do not invent shorter meanings.\n'
            + ch.codebook.prompt() + '\n' + context + '\nCASES:\n'
            + '\n'.join(f'{i}. {text}' for i, (text, _) in enumerate(fixtures(suite), 1)))


def decode_prompt(frames, suite='oz1'):
    ch, context = setup_context(suite)
    labels = {k: r.name for k, r in RULES.items()}
    return ('This is a text-only language comprehension test. Do not use tools, files, network or agents. '
            'Decode the received frames. Return JSON {"decoded":[[atom,...],...]} in frame order. '
            'Each atom is {"op":label,"ref":integer_or_null}; literal uses '
            '{"op":"literal","ref":null,"text":exact_text}. Do not return code symbols as labels. '
            'Expand macros into all primitive atoms, in order. Only return JSON, without Markdown.\n' + ch.codebook.prompt() + '\nLabels: '
            + json.dumps(labels) + '\n' + context + '\nFrames:\n' + json.dumps(frames, ensure_ascii=False))


def run_cli(provider, text, work):
    start = time.monotonic()
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    if provider == 'codex':
        exe = shutil.which('codex.exe')
        if not exe:
            return {'status': 'unavailable', 'reason': 'codex.exe not found'}
        final = work / 'codex-final.json'
        cmd = [exe, '--no-daemon', '-a', 'never', 'exec', '-s', 'read-only',
               '--ephemeral', '--json', '-o', str(final), '-']
    else:
        exe = shutil.which('claude.exe') or shutil.which('claude')
        if not exe:
            return {'status': 'unavailable', 'reason': 'claude not found'}
        cmd = [exe, '--print', '--output-format', 'json', '--tools', '',
               '--no-session-persistence', '--permission-mode', 'dontAsk',
               '--system-prompt', 'You perform text-only language tests. Return the requested JSON. Use no tools.']
    try:
        proc = subprocess.run(cmd, input=text, text=True, encoding='utf-8', errors='replace',
                              capture_output=True, cwd=ROOT, env=env, timeout=180,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except subprocess.TimeoutExpired:
        return {'status': 'timeout', 'wall_seconds': round(time.monotonic() - start, 3)}
    except OSError as exc:
        return {'status': 'unavailable', 'reason': type(exc).__name__}
    result = {'status': 'completed' if proc.returncode == 0 else 'failed',
              'returncode': proc.returncode, 'wall_seconds': round(time.monotonic() - start, 3)}
    # Never persist arbitrary CLI stderr, credentials, settings or tool outputs.
    try:
        if provider == 'codex':
            result['answer'] = final.read_text(encoding='utf-8') if final.exists() else ''
            events = []
            for line in proc.stdout.splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
            result['usage'] = [e['usage'] for e in events if isinstance(e, dict) and 'usage' in e]
            result['model'] = 'configured CLI default; not inferred from memory'
            result['unexpected_tool_items'] = sum(
                1 for e in events if isinstance(e, dict) and e.get('type') == 'item.completed'
                and isinstance(e.get('item'), dict) and e['item'].get('type') in
                {'command_execution', 'mcp_tool_call', 'web_search', 'file_change'})
        else:
            data = json.loads(proc.stdout)
            result['answer'] = data.get('result', '')
            result['usage'] = data.get('usage', {})
            result['model_usage'] = data.get('modelUsage', {})
            result['reported_duration_ms'] = data.get('duration_ms')
            result['reported_api_duration_ms'] = data.get('duration_api_ms')
            result['provider_error'] = bool(data.get('is_error', False))
            if result['provider_error']:
                result['status'] = 'failed'
    except (ValueError, OSError, TypeError):
        result['status'] = 'unparseable_cli_result'
    return result


def expected_decoding(atoms):
    return [dict(op='literal', ref=None, text=a.text) if a.code == ':'
            else dict(op=RULES[a.code].name, ref=a.ref) for a in atoms]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Actually call configured Codex and Claude CLIs')
    parser.add_argument('--suite', choices=['oz1', 'oz2'], default='oz1')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output is None:
        args.output = ROOT / ('reports/oz2-live.json' if args.suite == 'oz2' else 'reports/oz-live.json')
    if not args.live:
        print(encode_prompt(args.suite))
        return
    work = ROOT / '.oz-eval'
    work.mkdir(exist_ok=True)
    # Prevent old output from being mistaken for this invocation's result.
    stamp = str(time.time_ns())
    work = work / stamp
    work.mkdir()
    print('Running encoder conformance test through configured Codex CLI.', flush=True)
    encoder = run_cli('codex', encode_prompt(args.suite), work)
    report = {'kind': 'cross_cli_protocol_smoke_test', 'suite': args.suite, 'encoder': encoder,
              'limitations': ['One synthetic batch, no repeated trials or held-out task-success comparison.',
                              'CLI defaults and tool/system overhead differ; do not compare latency as a speedup.',
                              'No real coding, test execution, physical validation or production orchestration.']}
    try:
        data = json.loads(encoder.get('answer', ''))
        frames = data['frames']
        if encoder['status'] != 'completed' or not isinstance(frames, list) or len(frames) != len(fixtures(args.suite)):
            raise ValueError('invalid encoder batch')
        ch, _ = setup_context(args.suite)
        outcomes, expected = [], []
        for emitted, (_, wire) in zip(frames, fixtures(args.suite)):
            wanted = ch.accept(wire, binding=ch.binding)
            expected.append(expected_decoding(wanted))
            try:
                outcomes.append(ch.accept(emitted, binding=ch.binding) == wanted)
            except (Error, TypeError):
                outcomes.append(False)
        report['encoder_cases_correct'] = sum(outcomes)
        report['encoder_cases_total'] = len(outcomes)
        report['encoder_case_results'] = outcomes
        if not all(outcomes) or encoder.get('unexpected_tool_items', 0):
            report['decoder_status'] = 'not_run_due_to_encoder_failure'
        else:
            print('Sending the exact emitted frames to configured Claude CLI for independent decoding.', flush=True)
            decoder = run_cli('claude', decode_prompt(frames, args.suite), work)
            report['decoder'] = decoder
            decoded = json.loads(decoder.get('answer', ''))['decoded']
            if decoder['status'] != 'completed' or not isinstance(decoded, list) or len(decoded) != len(expected):
                raise ValueError('invalid decoder batch')
            results = [actual == want for actual, want in zip(decoded, expected)]
            report['decoder_cases_correct'] = sum(results)
            report['decoder_cases_total'] = len(results)
            report['decoder_case_results'] = results
    except (ValueError, KeyError, TypeError) as exc:
        report['evaluation_error'] = type(exc).__name__
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Wrote {args.output}', flush=True)


if __name__ == '__main__':
    main()
