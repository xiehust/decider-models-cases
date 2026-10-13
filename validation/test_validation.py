"""Offline tests: setup, schema, goldens, failure bounds and synthetic host checks."""
import copy
from decimal import Decimal
import json
import os
import subprocess
import unittest
from unittest.mock import patch

import cases
import run

class SetupTests(unittest.TestCase):
    def test_missing_keys_do_not_call_network(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(run.JEV, 'http_json', side_effect=AssertionError):
            report = run.JEV.setup_report()
        self.assertEqual(report['available'], {'openrouter': False, 'typesafe': False})
        self.assertIsNone(report['recommended_provider'])
        self.assertTrue(report['requires_user_choice'])
        self.assertFalse(report['jev_called'])

    def test_presence_does_not_authenticate_or_expose_key(self):
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'offline-placeholder-not-a-key'}, clear=True):
            report = run.JEV.setup_report()
        self.assertTrue(report['available']['openrouter'])
        self.assertFalse(report['jev_called'])
        self.assertNotIn('offline-placeholder-not-a-key', json.dumps(report))

    def test_typesafe_presence_is_not_silent_switch(self):
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'offline-placeholder'}, clear=True):
            report = run.JEV.setup_report()
        self.assertEqual(report['recommended_provider'], 'typesafe')
        self.assertTrue(report['requires_user_choice'])
        self.assertFalse(report['jev_called'])


class FixtureTests(unittest.TestCase):
    def test_suite_schema_and_coverage(self):
        suite = cases.build_cases()
        skills = {p.parent.name for p in cases.SKILLS.glob('jev*/SKILL.md')}
        self.assertEqual({c['skill'] for c in suite} | {'jev-setup'}, skills)
        self.assertEqual(len(suite), run.MAX_CALLS)
        for item in suite:
            run.JEV.validate_request(item['request'])
            self.assertEqual(set(item['request']), {'model', 'state', 'questions'})
            self.assertEqual(set(item['request']['questions']), set(item['expected']))
            self.assertNotIn('expected', item['request']['state'])

    def test_parser_receipts_are_real(self):
        receipts = cases.parser_evidence()['receipts']
        self.assertFalse(receipts['original_regression']['passed'])
        self.assertTrue(receipts['weakened_test']['passed'])
        self.assertTrue(receipts['fixed_regression']['passed'])

    def test_find_code_selected_candidate_behavior(self):
        module = cases.load_module('billing_fixture', cases.HERE / 'fixtures/billing.py')
        payments = [dict(id='p1', order_id='o1', amount=10, currency='USD'),
                    dict(id='p2', order_id='o1', amount=10, currency='USD'),
                    dict(id='p3', order_id='o1', amount=10, currency='EUR')]
        self.assertEqual(module.duplicate_charges(payments), ['p2'])

    def test_redteam_whitelists_and_canary_ground_truth(self):
        fixtures = list(cases.redteam_cases())
        self.assertEqual([c['expected']['outcome']['value'] for c in fixtures],
                         ['boundary_held', 'boundary_breached', 'unknown'])
        self.assertTrue(all('expected' not in c['request']['state'] for c in fixtures))
        self.assertEqual([c['request']['state']['case_id'] for c in fixtures], ['R01', 'R02', 'R03'])

    def test_ui_fixture_does_not_claim_browser_observation(self):
        item = next(c for c in cases.interaction_cases() if c['skill'] == 'jev-ui')
        state = item['request']['state']
        self.assertFalse(state['browser_observation_available'])
        self.assertIn('NOT a captured', state['provenance'])
        self.assertIn('<button disabled>', state['html_source'])

    def test_simulation_transitions_and_staleness(self):
        item = next(c for c in cases.interaction_cases() if c['skill'] == 'jev-simulation')
        w1, w2 = item['request']['state']['worlds'].values()
        self.assertEqual(cases.apply_world(w1, 'recharge', 1)['energy'], 3)
        self.assertTrue(cases.apply_world(w2, 'deliver', 7)['delivered'])
        self.assertEqual(w1['energy'], 1)
        with self.assertRaises(ValueError):
            cases.apply_world(w1, 'recharge', 0)
        with self.assertRaises(ValueError):
            cases.apply_world(w1, 'deliver', 1)

    def test_malformed_native_request_is_rejected(self):
        bad = {'model': cases.MODEL, 'state': {}, 'questions': {'q': {'type': 'choice', 'instructions': 'Pick'}}}
        with self.assertRaises(run.JEV.JevError):
            run.JEV.validate_request(bad)


def fake_result(item):
    answers = {}
    for name, question in item['request']['questions'].items():
        expected = item['expected'][name]
        if question['type'] == 'choice':
            answers[name] = {'type': 'choice', 'choice': expected['value'], 'confidence': 1,
                             'probabilities': {k: int(k == expected['value']) for k in question['criteria']}}
        elif question['type'] == 'noul':
            answers[name] = {'type': 'noul', 'noul': int(expected['value'])}
        else:
            level = round(sum(expected['range']) / 2)
            labels = {str(i): description for i, description in enumerate(question['criteria'])}
            answers[name] = {'type': 'score', 'score': level, 'legend': labels, 'confidence': 1,
                             'probabilities': {k: int(int(k) == level) for k in labels}}
    response = {'answers': answers, 'model': 'offline-mock',
                'usage': {'input_tokens': 1, 'output_tokens': 1, 'cost': 0.00001}}
    report = run.JEV.build_report(item['request'], response,
                                  review_labels=run.JEV.REVIEW_LABELS | set(run.EXTRA_REVIEW))
    report.update(mode='jev_api', jev_called=True, transport='openrouter')
    exit_code = 2 if any(d['status'] == 'needs_review' for d in report['decisions'].values()) else 0
    return {'exit': exit_code, 'report': report}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.suite = cases.build_cases()

    def run_sequence(self, responses):
        by_request = {run.fingerprint(c['request']): result for c, result in zip(self.suite, responses)}
        calls, recorded = [], []
        def invoke(request):
            calls.append(run.fingerprint(request))
            return by_request[run.fingerprint(request)]
        rows, execution = run.run_bounded(self.suite, invoke, recorded.append)
        self.assertEqual(rows, recorded)
        return rows, execution, calls

    def test_golden_assessment_and_expected_review(self):
        responses = [fake_result(c) for c in self.suite]
        rows, execution, calls = self.run_sequence(responses)
        summary = run.summarize(self.suite, rows, execution)
        self.assertTrue(summary['complete_pass'])
        self.assertEqual(len(calls), len(self.suite))
        self.assertGreater(summary['review_questions'], 0)
        self.assertEqual(Decimal(summary['reported_cost_usd']), Decimal('0.00012'))

    def test_api_errors_stop_after_inflight_wave_without_retry(self):
        for status in (400, 401, 402, 403, 429, 500):
            with self.subTest(status=status):
                failures = [{'exit': 1, 'error': f'HTTP {status}'}] * len(self.suite)
                rows, execution, calls = self.run_sequence(failures)
                self.assertEqual(len(calls), run.CONCURRENCY)
                self.assertEqual(len(set(calls)), len(calls))
                self.assertEqual(execution['not_started'], len(self.suite) - run.CONCURRENCY)
                self.assertIsNotNone(execution['stop_reason'])

    def test_missing_cost_stops_instead_of_assuming_zero(self):
        responses = [fake_result(c) for c in self.suite]
        del responses[0]['report']['response']['usage']['cost']
        rows, execution, calls = self.run_sequence(responses)
        self.assertEqual(len(calls), run.CONCURRENCY)
        self.assertIn('cost absent', execution['stop_reason'])

    def test_observed_spend_cutoff(self):
        responses = [fake_result(c) for c in self.suite]
        responses[0]['report']['response']['usage']['cost'] = 0.02
        rows, execution, calls = self.run_sequence(responses)
        self.assertEqual(len(calls), run.CONCURRENCY)
        self.assertEqual(execution['stop_reason'], 'Observed spend cutoff reached')

    def test_false_answer_is_not_success_just_because_exit_zero(self):
        item = self.suite[0]
        result = fake_result(item)
        result['report']['response']['answers']['finished']['noul'] = 1
        result['report']['decisions']['finished'].update(value=True, probability=1)
        assessed = run.assess(item, result)
        self.assertFalse(assessed['passed'])
        self.assertFalse(next(c for c in assessed['checks'] if c['question'] == 'finished')['passed'])

    def test_malformed_response_stops_future_waves(self):
        responses = [fake_result(c) for c in self.suite]
        del responses[0]['report']['response']['answers']['next']
        rows, execution, calls = self.run_sequence(responses)
        self.assertEqual(len(calls), run.CONCURRENCY)
        self.assertIsNotNone(execution['stop_reason'])

    def test_cli_timeout_is_ambiguous_and_not_retried(self):
        with patch.object(run.subprocess, 'run', side_effect=subprocess.TimeoutExpired('jev-decide', 40)) as mocked:
            result = run.cli(self.suite[0]['request'], live=True)
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(result['exit'], 1)
        self.assertTrue(result['ambiguous'])

    def test_hard_request_bound(self):
        with self.assertRaises(ValueError):
            run.run_bounded(self.suite + self.suite, lambda _: self.fail('must not call'), lambda _: None)


class LoopRequestTests(unittest.TestCase):
    """A loop turn's request must stay exactly as sent; replay tooling keeps the request objects."""

    def test_ui_settings_turn_requests_are_not_rewritten_by_later_turns(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v2'))
        import loops_v2
        clicked = []

        def fake_pw(*args, timeout=60):  # no browser, no screenshots
            if args and args[0] == 'click':
                clicked.append(args[1])
            return ''

        def fake_observe():
            controls = {'e7': {'role': 'checkbox', 'name': '营销与活动邮件', 'flags': []},
                        'e9': {'role': 'checkbox', 'name': '发票邮件通知', 'flags': ['checked'] if 'e9' in clicked else []},
                        'e12': {'role': 'button', 'name': '保存设置', 'flags': []},
                        'e14': {'role': 'button', 'name': '删除账户', 'flags': []}}
            return f'snapshot after {len(clicked)} clicks', controls

        def fake_page():
            invoice = 'e9' in clicked
            return {'invoice': invoice, 'marketing': False,
                    'status': '设置已保存：发票邮件通知已开启' if invoice and 'e12' in clicked else ''}

        plan, sent, at_call = ['click_e9', 'click_e12', 'done'], [], []

        def decide(request):
            sent.append(request)
            at_call.append(copy.deepcopy(request))
            label = plan[len(sent) - 1]
            return fake_result({'request': request, 'expected': {'next': {'value': label}}})

        with patch.object(loops_v2, 'pw', fake_pw), patch.object(loops_v2, 'observe', fake_observe), \
                patch.object(loops_v2, 'ui_page_state', fake_page):
            summary = loops_v2.run_ui_settings(decide, lambda row: None)
        self.assertTrue(summary['task_verified'])
        self.assertEqual([r['state']['actions_taken'] for r in at_call],
                         [[], ['clicked checkbox "发票邮件通知"'],
                          ['clicked checkbox "发票邮件通知"', 'clicked button "保存设置"']])
        self.assertEqual(sent, at_call)  # nothing appended after a turn was sent


if __name__ == '__main__':
    unittest.main()
