"""V2 bounded runner: static scenarios in parallel, closed loops turn by turn.

Offline by default (schema + CLI dry-run). --live sends paid OpenRouter requests.
"""
import argparse
import concurrent.futures
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

V2 = Path(__file__).resolve().parent
sys.path.insert(0, str(V2.parent))
sys.path.insert(0, str(V2))
from run import JEV, cli, assess, cost_of, fingerprint  # noqa: E402
from cases_v2 import build_cases  # noqa: E402
import loops_v2  # noqa: E402

MAX_CALLS = 80
CONCURRENCY = 4
SPEND_STOP_USD = Decimal('0.02')  # Observed-spend cutoff, not an invoice cap.


class Budget:
    """Shared call/spend guard; refuses new calls after any error or the cutoff."""

    def __init__(self):
        self.lock, self.calls, self.spent, self.stop = threading.Lock(), 0, Decimal(0), None

    def decide(self, request):
        with self.lock:
            if self.stop or self.calls >= MAX_CALLS:
                self.stop = self.stop or 'call bound reached'
                return {'exit': 1, 'error': f'not sent: {self.stop}'}
            self.calls += 1
        started = time.monotonic()
        result = cli(request, live=True)
        result['wall_seconds'] = round(time.monotonic() - started, 4)
        with self.lock:
            cost = cost_of(result)
            if result.get('error') or result['exit'] not in (0, 2):
                self.stop = self.stop or 'API/protocol failure; no retry or provider switch'
            elif cost is None:
                self.stop = self.stop or 'usage cost missing'
            else:
                self.spent += cost
                if self.spent >= SPEND_STOP_USD:
                    self.stop = self.stop or 'observed spend cutoff'
        return result


def setup_checks():
    """jev-setup: presence-only reports under three synthetic environments, no network."""
    base = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'LANG')}
    variants = {'no_keys': {}, 'openrouter_only': {'OPENROUTER_API_KEY': 'placeholder-not-a-key'},
                'typesafe_only': {'TYPESAFE_API_KEY': 'placeholder-not-a-key'}}
    rows = []
    for name, extra in variants.items():
        out = subprocess.run(['jev-decide', 'setup'], capture_output=True, text=True, env={**base, **extra}, timeout=30)
        report = json.loads(out.stdout)
        leaked = 'placeholder-not-a-key' in out.stdout
        rows.append({'kind': 'setup', 'variant': name, 'exit': out.returncode, 'report': report, 'value_leaked': leaked})
    return rows


def offline():
    cases = build_cases()
    for item in cases:
        JEV.validate_request(item['request'])
        dry = cli(item['request'])
        assert dry['exit'] == 0 and dry['report'] == item['request'], item['id']
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--followup', action='store_true',
                        help='Run only the planner-assisted, strict-policy grid loop (variant B)')
    args = parser.parse_args()
    cases = offline()
    print(json.dumps({'mode': 'offline_validation', 'requests': len(cases),
                      'questions': sum(len(c['expected']) for c in cases),
                      'suite_sha256': fingerprint(cases)}, ensure_ascii=False), flush=True)
    if not args.live:
        return 0
    if not args.output:
        parser.error('--live requires --output')
    if not os.environ.get('OPENROUTER_API_KEY', '').strip():
        parser.error('OPENROUTER_API_KEY unavailable; no request sent')
    budget = Budget()
    if args.followup:
        with args.output.open('x', encoding='utf-8') as output:
            def record(row):
                output.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
                output.flush()
            record({'kind': 'manifest', 'loops': ['grid_planned'], 'policy': 'strict', 'provider': 'openrouter',
                    'max_calls': MAX_CALLS, 'spend_stop_usd': str(SPEND_STOP_USD), 'retries': 0,
                    'reason': 'Variant B after first run: host planner supplies route; apply selected only.',
                    'started_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
            summary = loops_v2.run_grid(budget.decide, record, planner=True, strict=True)
            record({'kind': 'loop_summary', **summary})
            record({'kind': 'summary', 'calls': budget.calls, 'reported_cost_usd': str(budget.spent),
                    'stop_reason': budget.stop, 'loops': ['grid_planned']})
            print(json.dumps(summary, ensure_ascii=False), flush=True)
        return 0
    with args.output.open('x', encoding='utf-8') as output:
        lock = threading.Lock()

        def record(row):
            with lock:
                output.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
                output.flush()

        record({'kind': 'manifest', 'suite_sha256': fingerprint(cases), 'cases': cases,
                'loops': ['npc', 'grid', 'ui_settings', 'ui_checkout'], 'provider': 'openrouter',
                'max_calls': MAX_CALLS, 'concurrency': CONCURRENCY, 'spend_stop_usd': str(SPEND_STOP_USD),
                'retries': 0, 'started_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
        for row in setup_checks():
            record(row)
        started = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = {pool.submit(budget.decide, c['request']): c for c in cases}
            for future in concurrent.futures.as_completed(futures):
                item = futures[future]
                result = future.result()
                row = {'kind': 'result', 'id': item['id'], 'skill': item['skill'],
                       'wall_seconds': result.get('wall_seconds'), **assess(item, result)}
                record(row)
                print(json.dumps({'id': row['id'], 'exit': row['exit'], 'passed': row['passed'],
                                  'miss': [c['question'] for c in row['checks'] if not c['passed']],
                                  'error': row.get('error')}, ensure_ascii=False), flush=True)
        static_wall = round(time.monotonic() - started, 4)
        loop_summaries = []
        for runner in (loops_v2.run_npc, loops_v2.run_grid, loops_v2.run_ui_settings, loops_v2.run_ui_checkout):
            if budget.stop:
                break
            summary = runner(budget.decide, record)
            record({'kind': 'loop_summary', **summary})
            loop_summaries.append(summary)
            print(json.dumps(summary, ensure_ascii=False), flush=True)
        summary = {'kind': 'summary', 'calls': budget.calls, 'reported_cost_usd': str(budget.spent),
                   'stop_reason': budget.stop, 'static_parallel_wall_seconds': static_wall,
                   'loops': [s['scenario'] for s in loop_summaries]}
        record(summary)
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
