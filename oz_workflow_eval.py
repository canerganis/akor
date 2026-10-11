"""Offline reproducible workflow check: real tokenizer/stdio, synthetic outcomes."""
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tempfile

from oz import Channel
from oz_runtime import Inbox
from oz_worker import StdioAdapter, Worker, process_host
from oz_workspace import default_channel, token_counters

ROOT = Path(__file__).parent
SCRIPT = (
    'import json,sys; r=json.load(sys.stdin); '
    'json.dump({"results":[[i,1 if i=="m3" and r["attempts"][i]==1 else 0,'
    '"SYNTHETIC receipt; no domain task executed."] for i in r["ids"]]},sys.stdout)'
)


def main():
    os.environ.setdefault('TIKTOKEN_CACHE_DIR', str(ROOT / '.token-cache'))
    count = token_counters(['o200k_base'])
    budget = 350
    channel = default_channel()
    snapshot = channel.snapshot()
    snapshot['recipient'] = 'reviewer'
    reviewer = Channel.from_snapshot(snapshot)
    adapter = StdioAdapter((sys.executable, '-c', SCRIPT), timeout=10)
    reports = []
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'inbox.sqlite'
        with Inbox(path) as box:
            oversized = ':' + 'New measurement uncertainty needs a method. ' * 120
            box.post(channel, 'large', oversized, binding=channel.binding)
            ids = [f'm{i}' for i in range(20)]
            for mid in ids:
                box.post(channel, mid, 'P', binding=channel.binding)
            box.post(reviewer, 'review', 'r1', binding=reviewer.binding, after=ids)
            box.post(channel, 'notice', '!3', binding=channel.binding)
            assert not box.plan(reviewer, counters=count).jobs
            first = box.plan(channel, counters=count, max_tokens=budget)
            assert 'large' in first.deferred and first.packet.tokens[0] <= budget
            worker = Worker(box, channel, adapter, counters=count, max_tokens=budget, timeout=10, retry_delay=0)
            for _ in range(20):
                # Stop before the intentionally oversized remaining job.
                if all(box.inspect(mid)['state'] == 'done' for mid in ids):
                    break
                report = worker.run_once()
                assert report['status'] == 'received', report
                assert max(report['estimated_input_tokens']) <= budget
                reports.append(report)
            assert all(box.inspect(mid)['state'] == 'done' for mid in ids)
            assert box.inspect('m3')['attempts'] == 2
            assert all(box.inspect(mid)['attempts'] == 1 for mid in ids if mid != 'm3')
            assert box.inspect('large')['attempts'] == 0
            assert box.inspect('large')['wire'] == oversized
            review_plan = box.plan(reviewer, counters=count, max_tokens=2048)
            assert 'Predecessor outputs' in review_plan.packet.text
            review = Worker(box, reviewer, adapter, counters=count, max_tokens=2048, timeout=10).run_once()
            assert review['status'] == 'received'
            host = process_host(box, channel)
            assert host['model_calls'] == 0
            states = box.stats()
        with Inbox(path) as restored:
            assert restored.inspect('review')['state'] == 'done'
            assert restored.inspect('large')['attempts'] == 0
            assert restored.inspect('m3')['attempts'] == 2
    result = {
        'package': '0.4.0', 'kind': 'offline_workflow_with_real_stdio_and_tokenizer',
        'tiktoken_version': importlib.metadata.version('tiktoken'), 'encoding': 'o200k_base',
        'input_budget_per_batch': budget, 'work_jobs': 20, 'work_batches': len(reports),
        'review_input_budget': 2048, 'predecessor_outputs_included': True,
        'work_reports': reports, 'review_report': review, 'host_report': host,
        'actual_model_calls': 0, 'stdio_adapter_calls': len(reports) + 1,
        'retried_job': 'm3', 'retry_attempts': 2, 'other_work_attempts': 1,
        'oversized_job_attempts': 0, 'oversized_payload_preserved': True,
        'review_waited_for_all_dependencies': True, 'reopen_preserved_results': True, 'states': states,
        'limitations': ['Synthetic adapter acknowledges IDs; it does not perform or validate domain tasks.',
                        'Input budget includes the worker response contract, not provider system/tool framing.',
                        'No model speed, quality, billing or language-comprehension claim.'],
    }
    path = ROOT / 'reports/oz-workflow.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ['work_reports', 'review_report', 'host_report']}, indent=2))


if __name__ == '__main__':
    main()
