"""Cost comparison page: Jev vs. the same requests judged directly by LLMs on Bedrock Runtime.

All figures are computed from receipts:
  Jev  - validation/v2/live-v2-*.jsonl (usage.cost reported by OpenRouter)
  LLM  - validation/v2/llm-baseline*-20261012.jsonl (Bedrock usage; prices are user-supplied assumptions)
"""
from decimal import Decimal
import json
import statistics
from html import escape
from pathlib import Path

import report_charts as C

V2 = Path(__file__).resolve().parent
LLM_FILE = V2 / 'llm-baseline-20261012.jsonl'
MODELS = {  # key -> receipt file and display label; prices are read from each run's manifest
    'opus': {'file': V2 / 'llm-baseline-20261012.jsonl', 'label': 'Claude Opus 5.5', 'api': 'Converse'},
    'haiku': {'file': V2 / 'llm-baseline-haiku-20261012.jsonl', 'label': 'Claude Haiku 5.5', 'api': 'Converse'},
    'gpt6luna': {'file': V2 / 'llm-baseline-gpt6luna-20261012.jsonl', 'label': 'GPT-6 Luna', 'api': 'Responses API'},
}
STYLE_NAME = {'reasoned': 'LLM · 答案+一句理由', 'terse': 'LLM · 只输出答案'}
STYLE_SHORT = {'reasoned': '答案+理由', 'terse': '只答案'}


def e(v):
    return escape(str(v), quote=True)


def usd(v, digits=6):
    return f'${Decimal(v):.{digits}f}'


class ModelRun:
    """One LLM's receipts: per-style token, cost, accuracy and latency totals, all reconciled."""

    def __init__(self, key, spec, items):
        rows = [json.loads(l) for l in spec['file'].read_text().splitlines()]
        self.key, self.label, self.api = key, spec['label'], spec['api']
        self.manifest = rows[0]
        self.summary = next(r for r in rows if r['kind'] == 'summary')
        self.walls = {r['style']: r['wall_seconds'] for r in rows if r['kind'] == 'style_wall'}
        self.llm = [r for r in rows if r['kind'] == 'llm_result']
        assert not [r for r in rows if r['kind'] in ('error', 'skipped')]
        assert {r['id'] for r in self.llm} == set(items)
        self.styles = self.manifest['styles']
        self.p_in = Decimal(self.manifest.get('price_in_per_m', '4')) / 10 ** 6
        self.p_out = Decimal(self.manifest.get('price_out_per_m', '20')) / 10 ** 6
        self.t = {}
        for s in self.styles:
            rs = [r for r in self.llm if r['style'] == s]
            i, o = sum(r['usage']['inputTokens'] for r in rs), sum(r['usage']['outputTokens'] for r in rs)
            cost = sum(Decimal(r['cost_usd']) for r in rs)
            assert cost == i * self.p_in + o * self.p_out
            graded = [v for r in rs for v in r['graded'].values()]
            walls = sorted(r['wall_seconds'] for r in rs)
            norm = [v for r in rs if not r['id'].startswith('grid:') for v in r['graded'].values()]
            n_norm = sum(len(items[r['id']]['request']['questions']) if items[r['id']]['grade']['kind'] == 'expected' else 1
                         for r in rs if not r['id'].startswith('grid:'))
            self.t[s] = {'n': len(rs), 'in': i, 'out': o, 'cost_in': i * self.p_in, 'cost_out': o * self.p_out,
                         'cost': cost, 'correct': sum(graded), 'answered': len(graded),
                         'correct_norm': sum(norm), 'total_norm': n_norm,
                         'filtered': [r['id'] for r in rs if r['stop_reason'] != 'end_turn'],
                         'thinking': sum(r['has_reasoning'] for r in rs),
                         'reasoning_tokens': sum(r['usage'].get('reasoningTokens') or 0 for r in rs),
                         'out_think': [r['usage']['outputTokens'] for r in rs if r['has_reasoning']],
                         'out_plain': [r['usage']['outputTokens'] for r in rs if not r['has_reasoning']],
                         'wrong': [(r['id'], q) for r in rs for q, v in r['graded'].items() if not v],
                         # Client-measured round trip, same basis as Jev's CLI elapsed_seconds.
                         'lat': statistics.median(walls), 'p90': walls[int(0.9 * (len(walls) - 1))],
                         'lat_server': statistics.median(r['latency_ms'] for r in rs) / 1000, 'wall': self.walls[s]}
        assert sum(self.t[s]['cost'] for s in self.styles) == Decimal(self.summary['cost_usd'])


class SelfHosted:
    """Self-hosted decision model: tokens are free; cost is instance time for this batch.
    Batch cost = on-demand $/hour x serial wall time of the 76 requests (a utilization-based
    lower bound: the instance also costs money while idle)."""

    def __init__(self, items):
        path = V2 / 'llm-baseline-decider-20261012.jsonl'
        rows = [json.loads(l) for l in path.read_text().splitlines()]
        self.manifest = rows[0]
        self.summary = next(r for r in rows if r['kind'] == 'summary')
        self.llm = [r for r in rows if r['kind'] == 'llm_result']
        assert not [r for r in rows if r['kind'] in ('error', 'skipped')]
        assert {r['id'] for r in self.llm} == set(items)
        self.wall = Decimal(str(next(r for r in rows if r['kind'] == 'style_wall')['wall_seconds']))
        inst = self.manifest['instance']
        self.instance = inst
        self.rate = Decimal(inst['usd_per_hour'])
        self.cost = self.rate * self.wall / 3600
        self.per_day = self.rate * 24
        self.throughput = Decimal(len(self.llm)) / self.wall
        self.concurrency = self.manifest['concurrency']
        failed = [json.loads(l) for l in (V2 / 'llm-baseline-decider-concurrency4-failed-20261012.jsonl').read_text().splitlines()]
        self.failed_errors = [r['error'] for r in failed if r['kind'] == 'error']
        graded = [v for r in self.llm for v in r['graded'].values()]
        norm = [v for r in self.llm if not r['id'].startswith('grid:') for v in r['graded'].values()]
        walls = sorted(r['wall_seconds'] for r in self.llm)
        self.correct, self.answered = sum(graded), len(graded)
        self.correct_norm = sum(norm)
        self.inp = sum(r['usage']['inputTokens'] for r in self.llm)
        self.out = sum(r['usage']['outputTokens'] for r in self.llm)
        self.lat = statistics.median(walls)
        self.p90 = walls[int(0.9 * (len(walls) - 1))]
        # Review behaviour on choice/noul (score questions carry no review status).
        self.review = {'right_sel': 0, 'right_rev': 0, 'wrong_sel': [], 'wrong_rev': 0}
        for r in self.llm:
            for q, ok in r['graded'].items():
                st = r['decisions'][q]['status']
                if st == 'scored':
                    continue
                if ok:
                    self.review['right_sel' if st == 'selected' else 'right_rev'] += 1
                elif st == 'selected':
                    self.review['wrong_sel'].append((r['id'], q))
                else:
                    self.review['wrong_rev'] += 1
        self.score_q = [(r['id'], q, ok) for r in self.llm for q, ok in r['graded'].items()
                        if r['decisions'][q]['status'] == 'scored']
        self.by_id = {r['id']: r for r in self.llm}


class CostData:
    def __init__(self, d):
        self.items = {i['id']: i for i in json.loads((V2 / 'llm-requests.json').read_text())}
        self.runs = {k: ModelRun(k, spec, self.items) for k, spec in MODELS.items()}
        self.decider = SelfHosted(self.items)
        opus = self.runs['opus']  # aliases kept for the single-model sections
        self.manifest, self.summary, self.walls, self.llm = opus.manifest, opus.summary, opus.walls, opus.llm
        self.jev = {}
        for r in d.main + d.followup:
            if r.get('kind') == 'result':
                self.jev[r['id']] = r
            elif r.get('kind') == 'loop_turn':
                self.jev[f'{r["scenario"]}:turn{r["turn"]}'] = r
        assert set(self.jev) == set(self.items)
        self.styles = opus.styles
        self.n_judg = sum(len(i['request']['questions']) if i['grade']['kind'] == 'expected' else 1
                          for i in self.items.values())
        self._totals(d)

    def _totals(self, d):
        jr = [r['report'] for r in self.jev.values()]
        self.jev_in = sum(r['response']['usage']['input_tokens'] for r in jr)
        self.jev_out = sum(r['response']['usage']['output_tokens'] for r in jr)
        self.jev_cost = sum(Decimal(str(r['response']['usage']['cost'])) for r in jr)
        assert self.jev_cost == self.jev_in * Decimal('0.042') / 10 ** 6  # list price reconciles exactly
        assert self.jev_cost == d.usage['cost']
        self.jev_lat = statistics.median(r['elapsed_seconds'] for r in jr)
        lat = sorted(r['elapsed_seconds'] for r in jr)
        self.jev_p90 = lat[int(0.9 * (len(lat) - 1))]
        self.t = self.runs['opus'].t

    def jev_correct(self, exclude_grid=False):
        """Jev label agreement on the same judgments (value only, like the LLM grading).
        exclude_grid drops the 30-turn unplanned grid control (the misuse case)."""
        ok = total = 0
        for cid, r in self.jev.items():
            if exclude_grid and cid.startswith('grid:'):
                continue
            item = self.items[cid]
            g = item['grade']
            if g['kind'] == 'one_of':
                total += 1
                ok += r['report']['decisions'][g['question']]['value'] in g['accept']
            else:
                for qid, exp in g['expected'].items():
                    total += 1
                    val = r['report']['decisions'][qid]['value']
                    ok += (exp['range'][0] <= val <= exp['range'][1]) if 'range' in exp else val == exp['value']
        return ok, total

    def jev_review(self):
        """Same breakdown as SelfHosted.review, for Jev's own receipts on the same judgments."""
        out = {'right_sel': 0, 'right_rev': 0, 'wrong_sel': [], 'wrong_rev': 0}
        for cid, r in self.jev.items():
            g = self.items[cid]['grade']
            qids = [g['question']] if g['kind'] == 'one_of' else list(g['expected'])
            for q in qids:
                dec = r['report']['decisions'][q]
                if dec['status'] == 'scored':
                    continue
                if g['kind'] == 'one_of':
                    ok = dec['value'] in g['accept']
                else:
                    exp = g['expected'][q]
                    ok = dec['value'] == exp['value']
                if ok:
                    out['right_sel' if dec['status'] == 'selected' else 'right_rev'] += 1
                elif dec['status'] == 'selected':
                    out['wrong_sel'].append((cid, q))
                else:
                    out['wrong_rev'] += 1
        return out

    def per_skill(self, model='opus'):
        out = {}
        for cid, item in self.items.items():
            row = out.setdefault(item['skill'], {'n': 0, 'jev': Decimal(0), **{s: Decimal(0) for s in self.styles}})
            row['n'] += 1
            row['jev'] += Decimal(str(self.jev[cid]['report']['response']['usage']['cost']))
        for r in self.runs[model].llm:
            out[r['skill']][r['style']] += Decimal(r['cost_usd'])
        return out

    def cascade(self, style='terse', model='opus'):
        """Counterfactual composition of observed receipts: Jev on everything, and the LLM only
        for requests where Jev returned any needs_review decision (no new calls were made)."""
        llm = {r['id']: r for r in self.runs[model].llm if r['style'] == style}
        escalate = [cid for cid, r in self.jev.items()
                    if any(dec['status'] == 'needs_review' for dec in r['report']['decisions'].values())]
        cost = self.jev_cost + sum(Decimal(llm[c]['cost_usd']) for c in escalate)
        ok = total = 0
        for cid, item in self.items.items():
            g = item['grade']
            qids = [g['question']] if g['kind'] == 'one_of' else list(g['expected'])
            if cid in escalate:
                graded = llm[cid]['graded']
                ok += sum(graded.get(q, False) for q in qids)
            else:
                dec = self.jev[cid]['report']['decisions']
                for q in qids:
                    val = dec[q]['value']
                    if g['kind'] == 'one_of':
                        ok += val in g['accept']
                    else:
                        exp = g['expected'][q]
                        ok += (exp['range'][0] <= val <= exp['range'][1]) if 'range' in exp else val == exp['value']
            total += len(qids)
        return {'escalated': len(escalate), 'cost': cost, 'correct': ok, 'total': total}
# --- page ------------------------------------------------------------------------
SKILL_LABEL = {'jev': 'Agent 检查点', 'jev-code-review': '代码评审', 'jev-context': '上下文压缩', 'jev-documents': '合同文档',
               'jev-find-code': '定位代码', 'jev-route': '工具路由', 'jev-triage': '工单分诊', 'jev-simulation': '仿真（60 回合）',
               'jev-ui': '浏览器 UI', 'jev-redteam': '红队评估'}


VARIANT_COLOR = {('opus', 'reasoned'): C.RED, ('opus', 'terse'): '#f87171', ('haiku', 'reasoned'): C.VIOLET,
                 ('haiku', 'terse'): '#a78bfa', ('gpt6luna', 'reasoned'): C.BLUE, ('gpt6luna', 'terse'): '#60a5fa'}
DECIDER_COLOR = '#ea580c'
DECIDER_NAME = 'Strands Decider 2B（自托管）'


def decider_section(c, d):
    """Dedicated section: deployment, the two ways to cost a self-hosted model, the concurrency
    defect found, and how often its wrong answers were already routed to review."""
    dd = c.decider
    jr = c.jev_review()
    jev_wrong_sel_norm = [w for w in jr['wrong_sel'] if not w[0].startswith('grid:')]
    per_req_jev = c.jev_cost / len(c.items)
    per_req_full_util = dd.rate / 3600 / dd.throughput
    breakeven = dd.per_day / per_req_jev
    max_per_day = dd.throughput * 86400
    sq_right = sum(ok for *_, ok in dd.score_q)
    checkout = dd.by_id['ui_checkout:turn1']['raw_answers']['next']['probabilities']
    pay_label = max(checkout, key=checkout.get)
    pay_desc = c.items['ui_checkout:turn1']['request']['questions']['next']['criteria'][pay_label]
    wrong_sel = '、'.join(judgment_name(d, *w) for w in dd.review['wrong_sel']) or '无'
    h1 = dd.by_id['jev-code-review:pr']['raw_answers']['H1_severity']['probabilities']
    h1_txt = ' / '.join(f'{h1[k]:.2f}' for k in sorted(h1))
    review_rows = ''.join(
        f'<tr><td><b>{e(name)}</b></td><td class="num">{rv["right_sel"]}</td><td class="num">{rv["right_rev"]}</td>'
        f'<td class="num">{rv["wrong_rev"]}</td><td class="num {"bad-text" if rv["wrong_sel"] else "ok-text"}">{len(rv["wrong_sel"])}</td></tr>'
        for name, rv in [('Jev', jr), (DECIDER_NAME, dd.review)])
    review_rows += (f'<tr><td class="small muted" colspan="5">Jev 直接选定却答错的 {len(jr["wrong_sel"])} 个判断全部来自网格误用对照组；'
                    f'去掉这一组后为 {len(jev_wrong_sel_norm)} 个。</td></tr>')
    errors = sorted({err.split(': ', 1)[-1][:140] for err in dd.failed_errors})
    return f'''<div class="grid g2">
  <div class="card"><h3>部署与计价</h3><ul class="clean small">
    <li><b>模型：</b><code>{e(dd.manifest["model_id"])}</code>（Qwen3.5-2B-Base 上的 LoRA + 读出头，与 Jev 同类的决策模型），
        同 VPC 内自托管，接口 <code>/v1/systemone</code>，请求格式与 Jev 完全相同，76 个请求原样发送。</li>
    <li><b>实例：</b>{e(dd.instance["type"])}（1 × NVIDIA A10G 24 GB），按需价格 <b>${dd.rate}/小时</b>（{e(dd.instance["source"])}）。
        token 不计费，成本只来自机时。</li>
    <li><b>本批次机时成本：</b>${dd.rate}/小时 × {dd.wall} 秒 = <b>{usd(dd.cost)}</b>，是 Jev 的 {dd.cost / c.jev_cost:.2f} 倍。
        这是“机器只为这批请求开着”的下限；实例空闲时同样计费。</li>
    <li><b>常驻成本：</b>全天开机约 ${dd.per_day:.2f}/天。按 Jev 本次每个请求 {usd(per_req_jev, 7)} 计算，每天需要约
        {breakeven:,.0f} 个请求才与 Jev 持平；而本次串行实测吞吐约 {dd.throughput:.1f} 个请求/秒，单机满负荷每天约 {max_per_day:,.0f} 个，
        满负荷时每个请求约 {usd(per_req_full_util, 7)}，仍是 Jev 的 {per_req_full_util / per_req_jev:.2f} 倍。</li>
  </ul></div>
  <div class="card"><h3>发现的问题</h3><ul class="clean small">
    <li><b>并发不安全：</b>以并发 4 运行时，第一批请求就返回 HTTP 422，报错包括：{"；".join(f"<code>{e(x)}</code>" for x in errors)}。
        同一请求串行发送时正常；另一次手动复现中，两个请求并发时有一个失败，报错变成 <code>zip() argument 2 is longer than argument 1</code>
        （该复现结果未单独存档）。这表明服务端在并发时会混用不同请求的状态；并发下即使返回 200，结果是否可靠也无法保证（未验证）。因此本组结果按并发 {dd.concurrency} 串行测得，
        失败的那次回执原样保留在 <code>llm-baseline-decider-concurrency4-failed-20261012.jsonl</code>。</li>
    <li><b>评分题偏弱：</b>{len(dd.score_q)} 个 score 题只有 {sq_right} 个落在预设区间，分布普遍很平
        （例如代码评审 H1 严重度三个等级的概率为 {h1_txt}）。模型卡也写明 score 和 noul 对训练分布之外的评分标准迁移较差。</li>
    <li><b>付款步骤：</b>结算页上它以 {checkout[pay_label]:.3f} 的概率选择了 <code>{e(pay_label)}</code>（{e(pay_desc)}），只因略低于 0.8 的门槛才进入复核；
        门槛稍低就会被放行。这一步必须依赖宿主侧的硬拦截。</li>
    <li><b>直接选定却答错的判断（{len(dd.review["wrong_sel"])} 个）：</b>{e(wrong_sel)}。</li>
  </ul></div>
</div>
<div style="height:16px"></div>
<div class="table-wrap"><table><thead><tr><th>方案（choice / noul 题）</th><th>答对且直接选定</th><th>答对但送复核</th><th>答错但已送复核</th><th>答错且直接选定</th></tr></thead>
<tbody>{review_rows}</tbody></table></div>
<p class="small muted" style="margin-top:8px">复核门槛统一采用 CLI 默认值（最高概率 ≥ 0.8 且领先 ≥ 0.15，兜底标签总是复核），由 Jev 自带的校验器对两者的原始回执计算。
score 题没有复核状态，不计入此表。</p>'''


def variants(c):
    return [(k, s, run, run.t[s]) for k, run in c.runs.items() for s in run.styles]


def vname(run, s):
    return f'{run.label} · {STYLE_SHORT[s]}'


def fmt_x(ratio):
    return f'{ratio:.0f}×' if ratio >= 10 else f'{ratio:.1f}×'


def judgment_name(d, cid, q):
    title = d.cases.get(cid, {}).get('title')
    return f'{cid}（{title}）· {q}' if title else f'{cid} · {q}'


def by_skill_label(c, wrong):
    counts = {}
    for cid, _ in wrong:
        sk = SKILL_LABEL.get(c.items[cid]['skill'], c.items[cid]['skill'])
        counts[sk] = counts.get(sk, 0) + 1
    return '、'.join(f'{k} {v} 个' for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))


def cost_body(d, sec, footer):
    c = CostData(d)
    n = len(c.items)
    jev_ok, jev_total = c.jev_correct()
    V = variants(c)
    overview = [j for j in d.all_judgments() if j['case'] != 'grid']
    overview_pass, overview_total = sum(j['passed'] for j in overview), len(overview)
    xr = {(k, s): x['cost'] / c.jev_cost for k, s, _, x in V}

    def rng(k, field, fmt):
        vals = [c.runs[k].t[s][field] for s in c.runs[k].styles]
        return fmt(min(vals)), fmt(max(vals))

    kpis = [(usd(c.jev_cost, 4), f'Jev · {n} 次调用', f'输入 {c.jev_in:,} tokens × $0.042/M，输出免费')]
    for k, run in c.runs.items():
        lo, hi = rng(k, 'cost', lambda v: usd(v, 4))
        xs = [xr[(k, s)] for s in run.styles]
        kpis.append((f'{lo}～{hi}', f'{run.label}（${run.manifest["price_in_per_m"]} / ${run.manifest["price_out_per_m"]} 每百万）',
                     f'是 Jev 的 {min(xs):.1f}～{max(xs):.1f} 倍'))
    lats = [x['lat'] for _, _, _, x in V]
    kpis.append((f'{c.jev_lat:.2f}s', 'Jev 单次中位耗时', f'LLM 为 {min(lats):.1f}～{max(lats):.1f} 秒'))
    kpis.append((usd(c.decider.cost, 4), DECIDER_NAME, f'{c.decider.instance["type"]} 机时折算，是 Jev 的 {c.decider.cost / c.jev_cost:.1f} 倍；'
                 f'中位 {c.decider.lat:.2f} 秒，答对 {c.decider.correct}/{c.decider.answered}'))
    kpi_html = ''.join(f'<div class="card kpi"><div class="v" style="font-size:24px">{v}</div><div class="l">{e(l)}</div>'
                       f'<div class="s">{e(s)}</div></div>' for v, l, s in kpis)

    head = ('<tr><th>方案</th><th>接口</th><th>输入 tokens</th><th>输出 tokens</th><th>输入费用</th><th>输出费用</th><th>总费用</th>'
            '<th>相对 Jev</th><th>中位耗时</th><th>答对 / 作答</th></tr>')
    trs = [f'<tr><td><b>Jev</b></td><td class="small">OpenRouter</td><td class="num">{c.jev_in:,}</td><td class="num">{c.jev_out:,}<span class="muted small">（不计费）</span></td>'
           f'<td class="num">{usd(c.jev_cost)}</td><td class="num">$0</td><td class="num"><b>{usd(c.jev_cost)}</b></td><td class="num">1.0×</td>'
           f'<td class="num">{c.jev_lat:.2f}s</td><td class="num">{jev_ok}/{jev_total}</td></tr>']
    dd = c.decider
    trs.append(f'<tr><td><b>{e(DECIDER_NAME)}</b></td><td class="small">/v1/systemone（{e(dd.instance["type"])}）</td><td class="num">{dd.inp:,}</td>'
               f'<td class="num">{dd.out:,}<span class="muted small">（不计费）</span></td><td class="num" colspan="2"><span class="small">机时 ${dd.rate}/h × {dd.wall}s</span></td>'
               f'<td class="num"><b>{usd(dd.cost)}</b></td><td class="num">{dd.cost / c.jev_cost:.1f}×</td><td class="num">{dd.lat:.2f}s</td>'
               f'<td class="num">{dd.correct}/{dd.answered}<br><span class="muted small">串行（并发 {dd.concurrency}）</span></td></tr>')
    for k, s, run, x in V:
        reasoning = f'<br><span class="muted small">其中推理 {x["reasoning_tokens"]:,}</span>' if x['reasoning_tokens'] else ''
        filt = f'<br><span class="warn-text small">{len(x["filtered"])} 个请求被过滤</span>' if x['filtered'] else ''
        trs.append(f'<tr><td><b>{e(vname(run, s))}</b></td><td class="small">{e(run.api)}</td><td class="num">{x["in"]:,}</td>'
                   f'<td class="num">{x["out"]:,}{reasoning}</td><td class="num">{usd(x["cost_in"])}</td><td class="num">{usd(x["cost_out"])}</td>'
                   f'<td class="num"><b>{usd(x["cost"])}</b></td><td class="num">{xr[(k, s)]:.1f}×</td><td class="num">{x["lat"]:.2f}s</td>'
                   f'<td class="num">{x["correct"]}/{x["answered"]}{filt}</td></tr>')
    table = (f'<div class="table-wrap"><table><thead>{head}</thead><tbody>{"".join(trs)}</tbody></table></div>'
             '<p class="small muted" style="margin-top:8px">LLM 费用 = 回执中的输入 tokens × 输入单价 + 输出 tokens × 输出单价；单价为你给定的假设值。'
             'Jev 费用与 OpenRouter 回执中的 usage.cost 逐笔一致。“答对 / 作答”按与 Jev 相同的预设答案逐题打分，共 '
             f'{jev_total} 个判断。</p>')

    dec_bar = (DECIDER_NAME + '（机时）', float(c.decider.cost), DECIDER_COLOR, f'  {c.decider.cost / c.jev_cost:.1f}×')
    all_bars = C.hbars([('Jev', float(c.jev_cost), C.TEAL, ''), dec_bar] +
                       [(vname(run, s), float(x['cost']), VARIANT_COLOR[(k, s)], f'  {xr[(k, s)]:.1f}×')
                        for k, s, run, x in sorted(V, key=lambda v: v[3]['cost'])],
                       width=820, label_w=230, fmt=lambda v: f'${v:.4f}')
    cheap = [v for v in V if v[0] != 'opus']
    zoom = C.hbars([('Jev', float(c.jev_cost), C.TEAL, ''), dec_bar] +
                   [(vname(run, s), float(x['cost']), VARIANT_COLOR[(k, s)], f'  {xr[(k, s)]:.1f}×')
                    for k, s, run, x in sorted(cheap, key=lambda v: v[3]['cost'])],
                   width=820, label_w=230, fmt=lambda v: f'${v:.4f}')
    tok_in = C.hbars([('Jev', c.jev_in, C.TEAL, '')] + [(vname(run, s), x['in'], VARIANT_COLOR[(k, s)], '') for k, s, run, x in V],
                     width=820, label_w=230, fmt=lambda v: f'{v:,}')
    tok_out = C.hbars([('Jev（不计费）', c.jev_out, C.SLATE, '')] + [(vname(run, s), x['out'], VARIANT_COLOR[(k, s)], '') for k, s, run, x in V],
                      width=820, label_w=230, fmt=lambda v: f'{v:,}')
    comp = C.stacked([(vname(run, s), [('输入', float(x['cost_in']), C.BLUE), ('输出', float(x['cost_out']), C.VIOLET)]) for k, s, run, x in V]
                     + [('Jev', [('输入', float(c.jev_cost), C.TEAL)])], width=820, label_w=230)

    per = {k: c.per_skill(k) for k in c.runs}
    skills = sorted(per['opus'], key=lambda sk: -per['opus'][sk]['terse'])
    srows = ''.join(f'<tr><td>{e(SKILL_LABEL.get(sk, sk))}</td><td class="num">{per["opus"][sk]["n"]}</td><td class="num">{usd(per["opus"][sk]["jev"])}</td>'
                    + ''.join(f'<td class="num">{usd(per[k][sk]["terse"])}<span class="muted small"> · {fmt_x(per[k][sk]["terse"] / per[k][sk]["jev"])}</span></td>'
                              for k in c.runs) + '</tr>' for sk in skills)
    skill_table = ('<div class="table-wrap"><table><thead><tr><th>场景</th><th>调用</th><th>Jev</th>'
                   + ''.join(f'<th>{e(run.label)}<br>只答案</th>' for run in c.runs.values()) + '</tr></thead>'
                   f'<tbody>{srows}</tbody></table></div><p class="small muted" style="margin-top:8px">为便于阅读只列“只输出答案”这一档（各模型的成本下限）；'
                   '“答案+理由”的总额见上表。</p>')

    scale_rows = ([('Jev', c.jev_cost), (DECIDER_NAME + '（按本批次机时，不含空闲）', c.decider.cost)]
                  + [(vname(run, s), x['cost']) for k, s, run, x in V])
    scale_table = ('<div class="table-wrap"><table><thead><tr><th>方案</th><th>每个判断</th><th>1 万个判断</th><th>100 万个判断</th></tr></thead><tbody>'
                   + ''.join(f'<tr><td>{e(name)}</td><td class="num">{usd(cost / c.n_judg, 7)}</td><td class="num">{usd(cost / c.n_judg * 10_000, 2)}</td>'
                             f'<td class="num">{usd(cost / c.n_judg * 1_000_000, 2)}</td></tr>' for name, cost in scale_rows)
                   + f'</tbody></table></div><p class="small muted" style="margin-top:8px">按本次每个判断的平均费用（总费用 ÷ {c.n_judg} 个判断）线性外推，'
                   '是估算而非实测；实际费用取决于上下文长度和每个请求合并的问题数。</p>')

    jev_wrong = []
    for cid, r in c.jev.items():
        g = c.items[cid]['grade']
        if g['kind'] == 'one_of':
            if r['report']['decisions'][g['question']]['value'] not in g['accept']:
                jev_wrong.append((cid, g['question']))
        else:
            for q, exp in g['expected'].items():
                val = r['report']['decisions'][q]['value']
                if not ((exp['range'][0] <= val <= exp['range'][1]) if 'range' in exp else val == exp['value']):
                    jev_wrong.append((cid, q))
    grid_wrong = sum(cid.startswith('grid:') for cid, _ in jev_wrong)

    def wrong_cell(items):
        if not items:
            return '<span class="ok-text">无</span>'
        grid = [w for w in items if w[0].startswith('grid:')]
        rest = [judgment_name(d, cid, q) for cid, q in items if not cid.startswith('grid:')]
        parts = ([f'网格变体 A 的 {len(grid)} 个回合'] if grid else []) + rest
        return '<br>'.join(e(p) for p in parts)
    acc_rows = [f'<tr><td><b>Jev</b></td><td class="num">{jev_ok}/{jev_total}</td><td class="num">0</td><td class="small">{wrong_cell(jev_wrong)}</td></tr>']
    dd_wrong = [(r['id'], q) for r in c.decider.llm for q, v in r['graded'].items() if not v]
    acc_rows.append(f'<tr><td><b>{e(DECIDER_NAME)}</b></td><td class="num">{c.decider.correct}/{c.decider.answered}</td><td class="num">0</td>'
                    f'<td class="small">共 {len(dd_wrong)} 个，分布在 {e(by_skill_label(c, dd_wrong))}；其中 {c.decider.review["wrong_rev"]} 个已被自身标为 needs_review'
                    '（明细见下文“自托管决策模型”）</td></tr>')
    for k, s, run, x in V:
        acc_rows.append(f'<tr><td><b>{e(vname(run, s))}</b></td><td class="num">{x["correct"]}/{x["answered"]}</td>'
                        f'<td class="num">{jev_total - x["answered"]}</td><td class="small">{wrong_cell(x["wrong"])}'
                        + (f'<br><span class="warn-text">被过滤未作答：{e("、".join(x["filtered"]))}</span>' if x['filtered'] else '') + '</td></tr>')
    acc_table = ('<div class="table-wrap"><table><thead><tr><th>方案</th><th>答对 / 作答</th><th>未作答</th><th>答错或未作答的判断</th></tr></thead>'
                 f'<tbody>{"".join(acc_rows)}</tbody></table></div>'
                 f'<p class="small muted" style="margin-top:8px">Jev 的 {jev_ok}/{jev_total} 包含总览页单列为对照组的网格变体 A（其中 {grid_wrong} 个回合不是最优步），'
                 f'所以与总览页 {overview_pass}/{overview_total} 的口径不同；这里统一按标签是否与预设一致计，不计复核状态。</p>')

    casc_rows = []
    for k, run in c.runs.items():
        cs = c.cascade('terse', k)
        casc_rows.append(f'<tr><td>Jev → {e(run.label)} · 只答案</td><td class="num">{cs["escalated"]}</td><td class="num">{usd(cs["cost"], 4)}</td>'
                         f'<td class="num">{cs["cost"] / c.jev_cost:.1f}×</td><td class="num">{cs["correct"]}/{cs["total"]}</td></tr>')
    casc_table = ('<div class="table-wrap"><table><thead><tr><th>组合（估算）</th><th>转交 LLM 的请求</th><th>费用</th><th>相对纯 Jev</th><th>答对</th></tr></thead>'
                  f'<tbody>{"".join(casc_rows)}</tbody></table></div><p class="small muted" style="margin-top:8px">先全部交给 Jev，只把含 needs_review 决策的请求再交给 LLM。'
                  '这是用两组真实回执拼算的反事实结果，没有实际运行这条流程；被过滤的请求按答错计。</p>')

    think_rows = ''.join(
        f'<tr><td>{e(vname(run, s))}</td><td class="num">{x["thinking"]}/{x["n"]}</td>'
        f'<td class="num">{(sum(x["out_think"]) / len(x["out_think"])) if x["out_think"] else 0:.0f}</td>'
        f'<td class="num">{(sum(x["out_plain"]) / len(x["out_plain"])) if x["out_plain"] else 0:.0f}</td>'
        f'<td class="num">{x["reasoning_tokens"]:,}</td></tr>' if x['reasoning_tokens'] else
        f'<tr><td>{e(vname(run, s))}</td><td class="num">{x["thinking"]}/{x["n"]}</td>'
        f'<td class="num">{(sum(x["out_think"]) / len(x["out_think"])) if x["out_think"] else 0:.0f}</td>'
        f'<td class="num">{(sum(x["out_plain"]) / len(x["out_plain"])) if x["out_plain"] else 0:.0f}</td>'
        f'<td class="num muted">—（回执未单列，已含在输出 tokens 中）</td></tr>'
        for k, s, run, x in V)
    think_table = ('<div class="table-wrap"><table><thead><tr><th>方案</th><th>出现思考/推理的调用</th><th>有思考时平均输出</th><th>无思考时平均输出</th>'
                   f'<th>推理 tokens 合计</th></tr></thead><tbody>{think_rows}</tbody></table></div>'
                   '<p class="small muted" style="margin-top:8px">三个模型都使用默认配置，没有显式设置思考或 effort。Claude（Converse）在回复中返回思考块，'
                   'GPT-6 Luna（Responses API）在 usage.output_tokens_details 里单独报告推理 tokens。两者都计入输出 tokens 并按输出单价计费，已包含在上面的费用中。</p>')
    design = f'''<div class="grid g2">
  <div class="card"><h3>测试方法</h3><ul class="clean small">
    <li><b>同样的用例：</b>{n} 个请求、{c.n_judg} 个判断，与 Jev 运行时看到的完全一致；60 个闭环回合按 Jev 的历史回执回放，在同样的状态下重建请求。</li>
    <li><b>同样的提示：</b>三个模型使用同一份系统提示和同一份 JSON 输入（state、问题、候选），要求返回 JSON 答案。</li>
    <li><b>接口：</b>Claude 两个模型用 Bedrock Runtime Converse；GPT-6 Luna 用 Bedrock Runtime 上的 OpenAI Responses API
        （<code>/openai/v1/responses</code>，实例角色 SigV4 签名，<code>store: false</code>，不在 Bedrock 保留数据）。区域 {e(c.manifest["region"])}，全部用 global 推理配置文件。</li>
    <li><b>两种输出风格：</b>“答案+一句理由”接近 Agent 自己判断的常见写法；“只输出答案”是 LLM 的成本下限。</li>
    <li><b>边界：</b>每个模型 {c.runs["opus"].summary["calls"]} 次调用，并发 4，不重试；三个模型均无调用错误。</li>
    <li><b>耗时口径：</b>所有方案都取客户端实测的单次往返时间（Jev 取 CLI 回执的 elapsed_seconds，LLM 取调用前后的墙钟时间），
        各方案中位数与 Bedrock 服务端记录的耗时最多相差 {max(abs(x["lat"] - x["lat_server"]) for _, _, _, x in V):.2f} 秒。</li>
  </ul></div>
  <div class="card"><h3>计价与 token 口径</h3><ul class="clean small">
    <li><b>单价（你给定）：</b>Opus 5.5 $4 / $20，Haiku 5.5 与 GPT-6 Luna 均为 $0.10 / $0.50（每百万输入 / 输出 tokens）；Jev $0.042 / 百万输入，输出免费。本报告没有另行核实牌价。</li>
    <li><b>token 取实测：</b>全部来自服务端回执。分词器不同：同样的输入，Claude 计得 Jev 的 {c.runs["haiku"].t["terse"]["in"] / c.jev_in:.2f} 倍，
        GPT-6 Luna 计得 {c.runs["gpt6luna"].t["terse"]["in"] / c.jev_in:.2f} 倍。</li>
    <li><b>差距来源：</b>Haiku 与 GPT-6 Luna 的输入单价是 Jev 的 {Decimal("0.10") / Decimal("0.042"):.1f} 倍，此外还要为输出（含思考）付费；Opus 的输入单价是 Jev 的
        {Decimal(4) / Decimal("0.042"):.0f} 倍。</li>
  </ul></div></div>'''

    caveats = '''<ul class="clean small">
  <li>价格采用你给定的数字；Bedrock 实际牌价、批量与缓存折扣都没有考虑。系统提示很短，没有使用提示缓存。</li>
  <li>每个请求每种风格只跑了一次，没有测量随机波动；GPT-6 Luna 在两种风格下错的题并不完全相同，说明单次结果有波动。</li>
  <li>准确率基于同一作者编写的小样本，只说明这些用例上的表现，不代表普遍结论。</li>
  <li>LLM 的“理由”与 Jev 的概率分布用途不同：前者可以给人看，后者可以直接设门槛做自动复核，纯成本对比没有计入这部分差异。</li>
  <li>原始回执：<code>validation/v2/llm-baseline-20261012.jsonl</code>（Opus）、<code>llm-baseline-haiku-20261012.jsonl</code>、<code>llm-baseline-gpt6luna-20261012.jsonl</code>；
      重建的请求 <code>llm-requests.json</code>；脚本 <code>llm_baseline.py</code>。</li>
</ul>'''

    g = c.runs['gpt6luna'].t
    h = c.runs['haiku'].t
    o = c.runs['opus'].t

    def by_skill(wrong):
        counts = {}
        for cid, _ in wrong:
            sk = SKILL_LABEL.get(c.items[cid]['skill'], c.items[cid]['skill'])
            counts[sk] = counts.get(sk, 0) + 1
        return '、'.join(f'{k} {v} 个' for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
    g_wrong = sorted(set(g['terse']['wrong']) | set(g['reasoned']['wrong']))
    h_wrong = sorted(set(h['terse']['wrong']) | set(h['reasoned']['wrong']))
    o_filtered = sorted(set(o['terse']['filtered']) | set(o['reasoned']['filtered']))
    jev_other = [w for w in jev_wrong if not w[0].startswith('grid:')]
    ui_done = [r for r in c.runs['gpt6luna'].llm if r['id'] == 'ui_settings:turn2' and r['answers'] and r['answers'].get('next') == 'done']
    findings = f'''<div class="grid g2">
  <div class="callout ok"><b>最便宜的 LLM 仍是 Jev 的 {min(xr.values()):.1f} 倍以上。</b>GPT-6 Luna 只答案 {usd(g["terse"]["cost"], 4)}、Haiku 5.5 只答案 {usd(h["terse"]["cost"], 4)}，
    Jev {usd(c.jev_cost, 4)}。在同样单价下，GPT-6 Luna 比 Haiku 便宜约 {1 - g["terse"]["cost"] / h["terse"]["cost"]:.0%}：输入 tokens 少约
    {1 - g["terse"]["in"] / h["terse"]["in"]:.0%}，输出 tokens 也更少。</div>
  <div class="callout ok"><b>Haiku 5.5 的准确率最高。</b>两种风格分别答对 {h["terse"]["correct"]}/{h["terse"]["answered"]} 和 {h["reasoned"]["correct"]}/{h["reasoned"]["answered"]}，
    没有请求被过滤，答错的是 {e("、".join(judgment_name(d, *w) for w in h_wrong)) or "无"}。Opus 5.5 能作答的判断全部答对，但有 {len(o_filtered)} 个请求
    （{e("、".join(o_filtered))}）被内容过滤。</div>
  <div class="callout warn"><b>GPT-6 Luna 最快、最便宜，但错得最多。</b>两种风格分别答对 {g["terse"]["correct"]}/{jev_total} 和 {g["reasoned"]["correct"]}/{jev_total}；
    两种风格合计答错的判断分布在 {by_skill(g_wrong)}。{"其中 UI 第 2 步只勾选了复选框、还没点保存，就判定任务已完成（done）。" if ui_done else ""}
    两种风格错的题并不完全相同。</div>
  <div class="callout note"><b>Jev 的错题与 LLM 不同。</b>Jev 主要错在网格独自规划（{grid_wrong} 个回合），其余 {len(jev_other)} 个是
    {e("、".join(judgment_name(d, *w) for w in jev_other))}；这些题 LLM 基本都答对了。组合方案（见下文）先 Jev、再把需复核的请求交给 Haiku，
    费用约为纯 Jev 的 {c.cascade("terse", "haiku")["cost"] / c.jev_cost:.1f} 倍。</div>
  <div class="callout warn"><b>自托管的 Strands Decider 2B 最快，但这批用例上明显不准。</b>串行中位 {c.decider.lat:.2f} 秒，按 {c.decider.instance["type"]} 机时折算
    {usd(c.decider.cost, 4)}（Jev 的 {c.decider.cost / c.jev_cost:.1f} 倍）；答对 {c.decider.correct}/{c.decider.answered}（不含网格误用对照组
    {c.decider.correct_norm}/{c.runs["opus"].t["terse"]["total_norm"]}）。在有复核状态的 choice / noul 题里，它答错的
    {c.decider.review["wrong_rev"] + len(c.decider.review["wrong_sel"])} 个中有 {c.decider.review["wrong_rev"]} 个已被自身送去复核，直接选定却答错的只有
    {len(c.decider.review["wrong_sel"])} 个；另有 {sum(not ok for *_, ok in c.decider.score_q)} 个评分题超出预设区间。服务端并发不安全，只能串行。</div>
</div>'''

    return (f'''<div class="hero"><div class="wrap">
  <div class="crumb"><a href="index.html">总览</a> / 成本对比</div>
  <div class="eyebrow">Cost Comparison</div>
  <h1>💰 成本对比：Jev vs 直接用 LLM 判断</h1>
  <p class="lead">把本报告中 Jev 处理过的 {n} 个请求（{c.n_judg} 个判断）原样交给 Bedrock Runtime 上的三个模型直接判断：
  Claude Opus 5.5、Claude Haiku 5.5（Converse）和 GPT-6 Luna（Responses API），并加入同 VPC 自托管的决策模型 Strands Decider 2B。
  实测输入、输出 tokens 与耗时，按给定单价（自托管按机时）折算费用，并用同一套预设答案打分。</p>
  <div class="meta">{"".join(f"<span>{e(run.label)} <b>{e(run.manifest['model_id'])}</b></span>" for run in c.runs.values())}
  <span>{e(DECIDER_NAME)} <b>{e(c.decider.manifest["model_id"])}</b></span>
  <span>运行日期 <b>2026-10-12</b></span></div>
</div></div>
<main class="wrap">
<section><div class="grid g3">{kpi_html}</div></section>
''' + sec('结论', findings, '摘要') +
            sec('测试设计与计价口径', design, '方法') +
            sec('总费用对比', f'<div class="card"><h3>全部方案（线性刻度）</h3>{all_bars}</div><div style="height:16px"></div>'
                f'<div class="card"><h3>去掉 Opus 后放大看</h3>{zoom}</div><div style="height:16px"></div>{table}', '结果') +
            sec('token 对比', f'<div class="card"><h3>输入 tokens</h3>{tok_in}<p class="small muted">同样的内容，不同分词器计得的数量不同。</p></div>'
                f'<div style="height:16px"></div><div class="card"><h3>输出 tokens（含思考/推理）</h3>{tok_out}'
                '<p class="small muted">Jev 的输出 tokens 不计费，只作参考。</p></div>', '分析') +
            sec('费用构成', f'<div class="card">{comp}</div>', '分析') +
            sec('思考与推理 tokens', think_table, '分析') +
            sec('准确率', acc_table, '质量') +
            sec(f'自托管决策模型：{DECIDER_NAME}', decider_section(c, d), '自托管') +
            sec('组合方案：先 Jev，再把需复核的请求交给 LLM', casc_table, '估算') +
            sec('按场景拆分', skill_table, '明细') +
            sec('规模化后的差距', scale_table, '外推') +
            sec('局限', f'<div class="card">{caveats}</div>', '说明') + footer + '</main>')

