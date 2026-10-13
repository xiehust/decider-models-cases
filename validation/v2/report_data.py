"""Load raw JSONL receipts and compute every figure the report shows.

Nothing here is typed by hand: counts, costs and latencies come from receipts.
"""
from decimal import Decimal
import json
import statistics
from pathlib import Path

V2 = Path(__file__).resolve().parent
VALIDATION = V2.parent
RUN_MAIN = V2 / 'live-v2-20261012.jsonl'
RUN_FOLLOWUP = V2 / 'live-v2-grid-planned-20261012.jsonl'
RUN_V1 = VALIDATION / 'live-20261012.jsonl'
LOOP_SKILL = {'npc': 'jev-simulation', 'grid': 'jev-simulation', 'grid_planned': 'jev-simulation',
              'ui_settings': 'jev-ui', 'ui_checkout': 'jev-ui'}


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def call_receipts(all_rows):
    """Every row that carries a live Jev report (static results and loop turns)."""
    return [r for r in all_rows if r.get('kind') in ('result', 'loop_turn') and r.get('report')]


def usage_totals(receipts):
    cost = sum((Decimal(str(r['report']['response']['usage']['cost'])) for r in receipts), Decimal(0))
    inp = sum(r['report']['response']['usage']['input_tokens'] for r in receipts)
    out = sum(r['report']['response']['usage']['output_tokens'] for r in receipts)
    lat = [r['report']['elapsed_seconds'] for r in receipts if 'elapsed_seconds' in r['report']]
    models = sorted({r['report']['response']['model'] for r in receipts})
    return {'calls': len(receipts), 'cost': cost, 'input_tokens': inp, 'output_tokens': out,
            'latency': lat, 'latency_median': statistics.median(lat) if lat else None,
            'latency_p90': sorted(lat)[int(0.9 * (len(lat) - 1))] if lat else None,
            'latency_max': max(lat) if lat else None, 'models': models}


def checks_of(row):
    """Normalized per-question checks for static results and graded loop turns."""
    if row.get('checks'):
        return row['checks']
    return []


class Data:
    def __init__(self):
        self.main = rows(RUN_MAIN)
        self.followup = rows(RUN_FOLLOWUP)
        self.v1 = rows(RUN_V1)
        self.manifest = self.main[0]
        self.cases = {c['id']: c for c in self.manifest['cases']}
        self.results = {r['id']: r for r in self.main if r['kind'] == 'result'}
        self.setup = [r for r in self.main if r['kind'] == 'setup']
        self.turns = {}
        for r in self.main + self.followup:
            if r['kind'] == 'loop_turn':
                self.turns.setdefault(r['scenario'], []).append(r)
        self.loop_summaries = {r['scenario']: r for r in self.main + self.followup if r['kind'] == 'loop_summary'}
        self.summary_main = next(r for r in self.main if r['kind'] == 'summary')
        self.summary_followup = next(r for r in self.followup if r['kind'] == 'summary')
        self.receipts = call_receipts(self.main) + call_receipts(self.followup)
        self.usage = usage_totals(self.receipts)
        self.usage_v1 = usage_totals(call_receipts(self.v1))
        self.v1_summary = next(r for r in self.v1 if r.get('kind') == 'summary')
        self._reconcile()

    def _reconcile(self):
        """Receipt sums must match the runners' own summaries exactly."""
        reported = Decimal(self.summary_main['reported_cost_usd']) + Decimal(self.summary_followup['reported_cost_usd'])
        assert self.usage['cost'] == reported, (self.usage['cost'], reported)
        assert self.usage['calls'] == self.summary_main['calls'] + self.summary_followup['calls']
        assert self.usage_v1['cost'] == Decimal(self.v1_summary['reported_cost_usd'])

    # --- per-skill ----------------------------------------------------------------
    def static_checks(self, skill):
        out = []
        for cid, r in self.results.items():
            if r['skill'] == skill:
                for c in r['checks']:
                    out.append(dict(c, case=cid))
        return out

    def loop_checks(self, scenario):
        """Each loop turn as one judgment; passed = oracle-matching and host-acceptable."""
        return self.turns.get(scenario, [])

    def answer(self, case_id, qid):
        return self.results[case_id]['report']['response']['answers'][qid]

    def decision(self, case_id, qid):
        return self.results[case_id]['report']['decisions'][qid]

    # --- cross-cutting -------------------------------------------------------------
    def all_judgments(self):
        """(skill, question, passed, value_ok, status, probability, kind) for every graded judgment."""
        out = []
        for cid, r in self.results.items():
            for c in r['checks']:
                kind = self.cases[cid]['request']['questions'][c['question']]['type']
                exp, val = c['expected'], c['actual']['value']
                value_ok = (exp['range'][0] <= val <= exp['range'][1]) if 'range' in exp else val == exp['value']
                out.append({'skill': r['skill'], 'case': cid, 'question': c['question'], 'passed': c['passed'],
                            'value_ok': value_ok, 'status': c['actual']['status'],
                            'probability': c['actual'].get('probability'), 'kind': kind, 'value': val})
        skill_of = LOOP_SKILL
        for scen, turns in self.turns.items():
            for t in turns:
                if scen == 'ui_checkout':
                    for c in t.get('checks', []):
                        out.append({'skill': 'jev-ui', 'case': scen, 'question': c['question'], 'passed': c['passed'],
                                    'value_ok': c['actual']['value'] == c['expected']['value'],
                                    'status': c['actual']['status'], 'probability': c['actual'].get('probability'),
                                    'kind': 'noul' if c['question'] == 'total_ok' else 'choice', 'value': c['actual']['value']})
                    continue
                value_ok = t.get('optimal') if scen.startswith('grid') else t.get('chosen') == t.get('oracle')
                out.append({'skill': skill_of[scen], 'case': scen, 'question': f'turn{t["turn"]}',
                            'passed': bool(t.get('passed')), 'value_ok': bool(value_ok), 'status': t.get('status'),
                            'probability': t.get('probability'), 'kind': 'choice', 'value': t.get('chosen')})
        return out

    def calls_by_skill(self):
        """Live Jev calls per skill: one per static request, one per loop turn."""
        out = {}
        for r in self.results.values():
            out[r['skill']] = out.get(r['skill'], 0) + 1
        for scen, turns in self.turns.items():
            out[LOOP_SKILL[scen]] = out.get(LOOP_SKILL[scen], 0) + len(turns)
        return out

    def skill_table(self, exclude=('grid',)):
        """Per-skill tallies; the lenient unplanned grid run is a control, reported separately."""
        table = {}
        for j in self.all_judgments():
            if j['case'] in exclude:
                continue
            row = table.setdefault(j['skill'], {'total': 0, 'passed': 0, 'review': 0, 'value_ok': 0})
            row['total'] += 1
            row['passed'] += j['passed']
            row['value_ok'] += j['value_ok']
            row['review'] += j['status'] == 'needs_review'
        return table

    def calibration(self, bins=(0.5, 0.8, 0.95, 1.0001), exclude=()):
        """Top-label probability vs. label agreement with the fixed oracle (choice/noul only)."""
        points = []
        for j in self.all_judgments():
            if j['kind'] == 'score' or j['probability'] is None or j['case'] in exclude:
                continue
            p = j['probability'] if j['kind'] == 'choice' else max(j['probability'], 1 - j['probability'])
            points.append((p, j['value_ok']))
        out, low = [], 0.0
        for high in bins:
            group = [ok for p, ok in points if low <= p < high]
            out.append({'range': (low, min(high, 1.0)), 'n': len(group),
                        'agree': sum(group), 'rate': (sum(group) / len(group)) if group else None})
            low = high
        return out


def fmt_usd(value):
    return f'{Decimal(value):.6f}'.rstrip('0').rstrip('.') if Decimal(value) else '0'


if __name__ == '__main__':
    d = Data()
    print(json.dumps({'usage': {k: (str(v) if isinstance(v, Decimal) else v) for k, v in d.usage.items() if k != 'latency'},
                      'usage_v1': {k: (str(v) if isinstance(v, Decimal) else v) for k, v in d.usage_v1.items() if k != 'latency'},
                      'skills': d.skill_table(), 'calibration': d.calibration()}, ensure_ascii=False, indent=1))
