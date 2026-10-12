"""Bounded, opt-in OpenRouter smoke runner; standard library only."""
import argparse
import concurrent.futures
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from cases import ROOT, HERE, build_cases, load_module

JEV = load_module('jev_validation', ROOT / '.darwin/skills/jev/scripts/jev.py')
MAX_CALLS = 12
CONCURRENCY = 2
SPEND_STOP_USD = Decimal('0.01')  # Observed spend cutoff, not a guaranteed invoice cap.
EXTRA_REVIEW = ['missing', 'ambiguous']


def cli(request, live=False):
    args = ['jev-decide', 'decide', '-', '--provider', 'openrouter', '--timeout', '30']
    for label in EXTRA_REVIEW:
        args += ['--review-label', label]
    if not live:
        args += ['--dry-run']
    try:
        result = subprocess.run(args, input=json.dumps(request, ensure_ascii=False),
                                capture_output=True, text=True, timeout=40)
    except subprocess.TimeoutExpired:
        return {'exit': 1, 'error': 'CLI timeout; outcome ambiguous; no replay', 'ambiguous': live}
    if result.returncode not in (0, 2):
        return {'exit': result.returncode, 'error': result.stderr.strip(), 'ambiguous': live}
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {'exit': 1, 'error': 'CLI returned invalid JSON; no replay', 'ambiguous': live}
    return {'exit': result.returncode, 'report': report}


def assess(item, result):
    if result['exit'] not in (0, 2) or 'report' not in result:
        return dict(result, checks=[], passed=False)
    report = result['report']
    try:
        assert report['mode'] == 'jev_api' and report['jev_called'] is True
        assert report['transport'] == 'openrouter'
        verified = JEV.build_report(item['request'], report['response'],
                                    review_labels=JEV.REVIEW_LABELS | set(EXTRA_REVIEW))
        assert report['decisions'] == verified['decisions']
        assert set(report['response']['answers']) == set(item['expected'])
        expected_exit = 2 if any(d['status'] == 'needs_review' for d in report['decisions'].values()) else 0
        assert result['exit'] == expected_exit
    except (AssertionError, KeyError, TypeError, ValueError) as error:
        return dict(result, checks=[], passed=False, error=f'Invalid live receipt: {type(error).__name__}')
    checks = []
    for name, expected in item['expected'].items():
        actual = report['decisions'][name]
        if 'range' in expected:
            low, high = expected['range']
            value_ok = low <= actual['value'] <= high
        else:
            value_ok = type(actual['value']) is type(expected['value']) and actual['value'] == expected['value']
        checks.append({'question': name, 'expected': expected, 'actual': actual,
                       'passed': value_ok and actual['status'] == expected['status']})
    return dict(result, checks=checks, passed=all(check['passed'] for check in checks))


def cost_of(result):
    try:
        cost = Decimal(str(result['report']['response']['usage']['cost']))
        return cost if cost.is_finite() and cost >= 0 else None
    except (KeyError, TypeError, ArithmeticError):
        return None


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def run_bounded(cases, invoke, record, assess_result=assess):
    if len(cases) > MAX_CALLS:
        raise ValueError('Request count exceeds fixed live bound')
    results, spent, stop = [], Decimal(0), None
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        for offset in range(0, len(cases), CONCURRENCY):
            batch = cases[offset:offset + CONCURRENCY]
            futures = [pool.submit(invoke, item['request']) for item in batch]
            for item, future in zip(batch, futures):
                try:
                    result = assess_result(item, future.result())
                except Exception as error:
                    result = {'exit': 1, 'error': type(error).__name__, 'checks': [], 'passed': False}
                row = {'id': item['id'], 'skill': item['skill'], **result}
                results.append(row)
                record(row)
                # Let already in-flight requests settle; never schedule another wave on an API/protocol error.
                if row.get('error') or row['exit'] not in (0, 2):
                    stop = 'API/protocol failure or ambiguous outcome; no retries or provider switch'
                cost = cost_of(row)
                if cost is None:
                    stop = stop or 'Usage cost absent or invalid; cannot enforce observed-spend cutoff'
                else:
                    spent += cost
                if spent >= SPEND_STOP_USD:
                    stop = stop or 'Observed spend cutoff reached'
            if stop:
                break
    return results, {'wall_seconds': round(time.monotonic() - started, 6),
                     'reported_cost_usd': str(spent), 'stop_reason': stop,
                     'not_started': len(cases) - len(results)}


def summarize(cases, rows, execution):
    checks = [check for row in rows for check in row['checks']]
    responses = [row['report']['response'] for row in rows if 'report' in row]
    usage = [response.get('usage', {}) for response in responses]
    def total(field):
        return sum(u[field] for u in usage) if all(field in u for u in usage) else None
    return {**execution, 'planned_requests': len(cases), 'attempted_requests': len(rows),
            'responses_received': len(responses), 'cases_passed': sum(r['passed'] for r in rows),
            'questions_planned': sum(len(c['expected']) for c in cases),
            'questions_assessed': len(checks), 'questions_passed': sum(c['passed'] for c in checks),
            'review_questions': sum(c['actual']['status'] == 'needs_review' for c in checks),
            'input_tokens': total('input_tokens'), 'output_tokens': total('output_tokens'),
            'cost_receipts': sum(cost_of(row) is not None for row in rows),
            'cost_unavailable_requests': sum(cost_of(row) is None for row in rows),
            'models': sorted({r.get('model', 'missing') for r in responses}),
            'complete_pass': (len(rows) == len(cases) and all(r['passed'] for r in rows)
                              and execution['stop_reason'] is None)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicit opt-in to paid OpenRouter requests')
    parser.add_argument('--output', type=Path, help='New JSONL receipt file; refuses overwrite')
    args = parser.parse_args()
    cases = build_cases()
    for item in cases:
        JEV.validate_request(item['request'])
        assert len(json.dumps(item['request']).encode()) < 20000
        dry = cli(item['request'])
        assert dry['exit'] == 0 and dry['report'] == item['request'], item['id']
    print(json.dumps({'mode': 'offline_validation', 'requests': len(cases),
                      'questions': sum(len(c['expected']) for c in cases),
                      'suite_sha256': fingerprint(cases)}, ensure_ascii=False), flush=True)
    if not args.live:
        return 0
    if not args.output:
        parser.error('--live requires --output to retain original receipts')
    if not os.environ.get('OPENROUTER_API_KEY', '').strip():
        parser.error('OPENROUTER_API_KEY unavailable; no request sent')
    # Snapshot both requests and independent goldens before the first paid call.
    with args.output.open('x', encoding='utf-8') as output:
        def record(row):
            output.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
            output.flush()
        record({'kind': 'manifest', 'suite_sha256': fingerprint(cases), 'cases': cases,
                'provider': 'openrouter', 'max_calls': MAX_CALLS, 'concurrency': CONCURRENCY,
                'spend_stop_usd': str(SPEND_STOP_USD), 'retries': 0,
                'started_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
        def live_record(row):
            record({'kind': 'result', **row})
            print(json.dumps({'id': row['id'], 'exit': row['exit'], 'passed': row['passed'],
                              'mismatches': [c for c in row['checks'] if not c['passed']],
                              'error': row.get('error')}, ensure_ascii=False), flush=True)
        rows, execution = run_bounded(cases, lambda request: cli(request, live=True), live_record)
        summary = summarize(cases, rows, execution)
        record({'kind': 'summary', **summary})
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary['complete_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

