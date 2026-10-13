"""Build the static HTML report from raw receipts: report/index.html + report/scenarios/*.html.

Run: python3 validation/v2/build_report.py   (offline; reads JSONL, writes report/)
"""
from decimal import Decimal
import re
import shutil
import sys
from html import escape
from pathlib import Path

V2 = Path(__file__).resolve().parent
sys.path.insert(0, str(V2))
sys.path.insert(0, str(V2.parent))
import report_charts as C  # noqa: E402
from report_content import SCENARIOS, FINDINGS  # noqa: E402
from report_data import Data  # noqa: E402

ROOT = V2.parent.parent
OUT = ROOT / 'report'
BY_SLUG = {s['slug']: s for s in SCENARIOS}
BY_SKILL = {s['skill']: s for s in SCENARIOS}
NAV = {'agent-checkpoint': '检查点', 'code-review': '代码评审', 'context': '上下文', 'documents': '文档',
       'find-code': '找代码', 'route': '路由', 'triage': '分诊', 'simulation': '仿真', 'ui': '浏览器 UI',
       'redteam': '红队', 'setup': '接入'}


def e(value):
    return escape(str(value), quote=True)


CJK = '\u3000-\u303f\u4e00-\u9fff\uff00-\uffef'
_WRAP_AFTER_CJK = re.compile(rf'(?<=[{CJK}])[ \t]*\n\s*(?=[{CJK}])')
_WRAP_AFTER_PUNCT = re.compile(r'(?<=[，。；：、！？）”])[ \t]*\n\s*')


def tidy_cjk_whitespace(markup):
    """Source lines are wrapped mid-sentence; in HTML each wrap renders as a space, which is wrong
    next to Chinese text (\u201c等级， 它\u201d). Remove such wraps outside <pre> blocks only."""
    parts = re.split(r'(<pre\b.*?</pre>)', markup, flags=re.S)
    return ''.join(p if p.startswith('<pre') else _WRAP_AFTER_PUNCT.sub('', _WRAP_AFTER_CJK.sub('', p)) for p in parts)


# --- layout ---------------------------------------------------------------------
def page(title, body, active=None, depth=0):
    up = '../' * depth
    links = [f'<a href="{up}index.html" class="{"active" if active is None else ""}">总览</a>']
    for s in SCENARIOS:
        cls = 'active' if s['slug'] == active else ''
        links.append(f'<a href="{up}scenarios/{s["slug"]}.html" class="{cls}" title="{e(s["title"])}">{e(NAV.get(s["slug"], s["title"]))}</a>')
    links.append(f'<a href="{up}cost.html" class="{"active" if active == "cost" else ""}">成本对比</a>')
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} · Jev 应用场景验证报告</title>
<link rel="stylesheet" href="{up}assets/style.css">
</head>
<body>
<header class="topbar"><div class="inner">
  <a class="brand" href="{up}index.html"><span class="logo">J</span>Jev 场景验证</a>
  <nav class="nav">{''.join(links)}</nav>
</div></header>
{tidy_cjk_whitespace(body)}
</body>
</html>
'''


def footer(d):
    return (f'<div class="footer">数据来源：<code>validation/v2/live-v2-20261012.jsonl</code>、'
            f'<code>validation/v2/live-v2-grid-planned-20261012.jsonl</code>、v1 基线 <code>validation/live-20261012.jsonl</code>。'
            f'模型 {e(", ".join(d.usage["models"]))}，经 OpenRouter 调用。测试材料全部是为本报告专门编写的合成内容。'
            f'页面由 <code>validation/v2/build_report.py</code> 根据原始调用记录生成，数字没有经过手工改动。</div>')


def badge(passed, total, review=None):
    cls = 'b-pass' if passed == total else 'b-warn' if passed / max(total, 1) >= 0.8 else 'b-fail'
    extra = f' · 复核 {review}' if review is not None else ''
    return f'<span class="badge {cls}">{passed}/{total} 通过{extra}</span>'


def status_text(status):
    return {'selected': '<span class="ok-text">selected</span>', 'scored': '<span class="muted">scored</span>',
            'needs_review': '<span class="warn-text">needs_review</span>'}.get(status, e(status))


def fmt_value(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, float):
        return f'{value:g}'
    return e(value)


def fmt_expected(exp):
    if 'range' in exp:
        return f'<span style="white-space:nowrap">[{exp["range"][0]:g}, {exp["range"][1]:g}]</span>'
    return f'{fmt_value(exp["value"])}' + (' <span class="muted small">（应复核）</span>' if exp['status'] == 'needs_review' else '')


def prob_text(actual):
    p = actual.get('probability')
    return '—' if p is None else f'{p:.2f}'


# --- shared sections --------------------------------------------------------------
def question_table(d, case_ids):
    rows = []
    for cid in case_ids:
        for qid, q in d.cases[cid]['request']['questions'].items():
            crit = q.get('criteria')
            if isinstance(crit, dict):
                options = ' · '.join(f'<code>{e(k)}</code>' for k in crit)
            elif isinstance(crit, list):
                options = f'{len(crit)} 级：' + ' / '.join(e(x) for x in crit)
            else:
                options = 'true / false'
            rows.append(f'<tr><td class="mono small">{e(qid)}</td><td><span class="tag">{q["type"]}</span></td>'
                        f'<td>{e(q["instructions"])}</td><td class="small">{options}</td></tr>')
    return ('<div class="table-wrap"><table><thead><tr><th>问题 ID</th><th>类型</th><th>问题</th><th>候选/等级</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def result_table(d, case_ids, label_case=False):
    rows = []
    for cid in case_ids:
        for c in d.results[cid]['checks']:
            a = c['actual']
            mark = '<span class="ok-text">✓ 通过</span>' if c['passed'] else '<span class="bad-text">✗ 未达标</span>'
            case_cell = f'<td class="mono small">{e(cid.split(":")[1])}</td>' if label_case else ''
            rows.append(f'<tr>{case_cell}<td class="mono small">{e(c["question"])}</td><td>{fmt_expected(c["expected"])}</td>'
                        f'<td><b>{fmt_value(a["value"])}</b></td><td class="num">{prob_text(a)}</td>'
                        f'<td>{status_text(a["status"])}</td><td>{mark}</td></tr>')
    head = '<th>用例</th>' if label_case else ''
    return (f'<div class="table-wrap"><table><thead><tr>{head}<th>问题</th><th>标准答案</th><th>Jev 返回</th>'
            f'<th>概率</th><th>状态</th><th>验收</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
            '<p class="small muted" style="margin-top:8px">' + PROB_NOTE + '</p>')


# Shared footnotes for every table with a 概率 column (values are Jev's own returned distribution).
REVIEW_GATE = '复核门槛用 CLI 默认值：最高概率不低于 0.8，并且比第二名高出至少 0.15。'
PROB_NOTE = ('概率一栏，choice 题是所选标签的概率，noul 题是回答“是”的概率。'
             'score 题返回按概率加权的等级值，这个值不是概率。' + REVIEW_GATE)
CHOICE_NOTE = '概率是 Jev 对所选标签给出的概率，取自它对全部候选返回的分布（各候选之和为 1），没有另行计算。'


def note(text):
    return f'<p class="small muted" style="margin-top:8px">{text}</p>'


def distribution_figures(d, case_id, qids, caption_prefix=''):
    figs = []
    for qid in qids:
        ans = d.answer(case_id, qid)
        check = next(c for c in d.results[case_id]['checks'] if c['question'] == qid)
        exp = check['expected']
        if ans['type'] == 'choice':
            chart = C.prob_bar(ans['probabilities'], ans['choice'], exp.get('value'))
        elif ans['type'] == 'score':
            levels = d.cases[case_id]['request']['questions'][qid]['criteria']
            chart = C.score_bar(ans['probabilities'], levels, ans['score'], exp.get('range'))
        else:
            continue
        figs.append(f'<figure class="card tight">{chart}<figcaption>{e(caption_prefix)}<code>{e(qid)}</code> 的返回分布'
                    f'（✓ 为标准答案，◀ 为 Jev 的选择，且与标准答案不同）</figcaption></figure>')
    return f'<div class="grid g2">{"".join(figs)}</div>'


def v1_baseline(d, skill):
    rows = [r for r in d.v1 if r.get('kind') == 'result' and r['skill'] == skill]
    if not rows:
        return ''
    body = []
    for r in rows:
        ok = sum(c['passed'] for c in r['checks'])
        miss = [c['question'] for c in r['checks'] if not c['passed']]
        body.append(f'<tr><td class="mono small">{e(r["id"])}</td><td class="num">{ok}/{len(r["checks"])}</td>'
                    f'<td class="small">{e("、".join(miss)) if miss else "—"}</td></tr>')
    return ('<h3 style="margin-top:22px">v1 冒烟基线（同技能，较简单的用例）</h3><div class="table-wrap"><table><thead><tr>'
            '<th>v1 用例</th><th>通过</th><th>未达标问题</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def intro_sections(s, trigger=''):
    bg = ''.join(f'<p>{e(p)}</p>' for p in s['background'])
    traps = ''.join(f'<li>{e(t)}</li>' for t in s['traps'])
    return f'''
<section><div class="grid g2">
  <div class="card"><div class="eyebrow">场景介绍</div><h2>业务背景</h2>{bg}</div>
  <div class="card"><div class="eyebrow">为什么用 Jev</div><h2>判断点</h2><p>{e(s["why"])}</p>
    <h3 style="margin-top:14px">埋设的陷阱</h3><ul class="clean">{traps}</ul></div>
</div></section>{trigger}
<section><div class="card"><div class="eyebrow">工作流</div><h2>调用方与 Jev 的分工</h2>{C.flow(s["flow"])}</div></section>'''


def skill_description(skill):
    """The `description:` line of the installed skill's SKILL.md frontmatter, verbatim."""
    from cases import SKILLS
    text = (SKILLS / skill / 'SKILL.md').read_text(encoding='utf-8')
    front = text.split('---', 2)[1]
    return re.search(r'^description:\s*(.+)$', front, re.M).group(1).strip()


def trigger_how(d, s):
    """How this run actually invoked the skill, from receipts and the runner (not from prose)."""
    calls = d.calls_by_skill().get(s['skill'], 0)
    if s['slug'] == 'setup':
        return (f'验证脚本在三种合成环境下各运行一次 <code>jev-decide setup</code>，共 {len(d.setup)} 次，'
                '只检查环境变量是否存在，不联网，也不调用 Jev。')
    if s['slug'] in ('simulation', 'ui'):
        unit = '每个回合' if s['slug'] == 'simulation' else '每走一步'
        return (f'闭环由验证脚本驱动，{unit}构造一次请求，经 <code>jev-decide decide - --provider openrouter</code> 真实调用，'
                f'本场景共 {calls} 次。')
    extra = ('请求由技能自带的 <code>scripts/prepare.py</code> 从对话记录生成，标准答案不进入模型输入。'
             if s['slug'] == 'redteam' else '')
    return (f'验证脚本扮演调用方，按 SKILL.md 的流程写好 {calls} 个请求，经 <code>jev-decide decide - --provider openrouter</code> '
            f'各真实调用一次。{extra}')


def trigger_section(d, s):
    """Card: what in the skill's own SKILL.md makes this scenario a match, and how this run invoked it."""
    t = s['trigger']
    return f'''
<section><div class="card"><div class="eyebrow">触发方式</div><h2>这个场景怎样触发 <span class="tag">{e(s["skill"])}</span></h2>
  <p class="small muted">Agent 启动时只读入每个技能的名称和 description，任务和 description 对得上，才加载完整的 SKILL.md 按其中的流程执行。
  本次测试跳过了自动匹配这一步，由验证脚本直接按技能流程构造请求。</p>
  <div class="grid g2">
    <div><h3>技能的 description</h3><p class="small mono">{e(skill_description(s["skill"]))}</p><p>{e(t["desc_zh"])}</p>
      <h3 style="margin-top:14px">本场景的触发时机</h3><p>{e(t["when"])}</p></div>
    <div><h3>本次怎么调用</h3><p>{trigger_how(d, s)}</p>
      <h3 style="margin-top:14px">什么时候不该触发</h3><p>{e(t["skip"])}</p></div>
  </div></div></section>'''


def result_section(d, s):
    """Fourth intro card: receipt-derived result line, the scenario's core conclusion and the
    production advice (previously a closing card), so the outcome is visible before the detail."""
    passed, total, review = scenario_stats(d, s)
    if s['slug'] == 'setup':
        lines = [f'{passed}/{total} 种凭据环境下的 setup 报告符合预期。']
    else:
        lines = [f'{passed}/{total} 个判断符合标准答案，{review} 个进入 needs_review。']
        misses = [j for j in d.all_judgments() if j['skill'] == s['skill'] and j['case'] != 'grid' and not j['passed']]
        lines.append('未达标：' + '、'.join(f'{j["case"]} · {j["question"]}' for j in misses) + '。' if misses else '没有未达标的判断。')
        grid = [j for j in d.all_judgments() if j['case'] == 'grid' and j['skill'] == s['skill']]
        if grid:
            lines.append(f'另有网格变体 A（误用对照组）{sum(j["value_ok"] for j in grid)}/{len(grid)} 个回合走的是最优步，不计入上面的数字。')
    facts = ''.join(f'<li>{e(x)}</li>' for x in lines)
    advice = ''.join(f'<li>{e(a)}</li>' for a in s['advice'])
    return f'''
<section><div class="card"><div class="eyebrow">测试结果与结论</div><h2>测试结果、核心结论与建议</h2>
  <div class="grid g2">
    <div><h3>测试结果</h3><ul class="clean">{facts}</ul>
      <h3 style="margin-top:14px">核心结论</h3><p>{e(s["verdict"])}</p></div>
    <div><h3>生产使用建议</h3><ul class="clean">{advice}</ul></div>
  </div></div></section>'''


def pager(slug):
    idx = [s['slug'] for s in SCENARIOS].index(slug)
    prev = SCENARIOS[idx - 1] if idx else None
    nxt = SCENARIOS[idx + 1] if idx + 1 < len(SCENARIOS) else None
    left = (f'<a href="{prev["slug"]}.html"><div class="card"><div class="small muted">← 上一个场景</div>'
            f'<b>{e(prev["title"])}</b></div></a>') if prev else '<a href="../index.html"><div class="card"><div class="small muted">← 返回</div><b>总览</b></div></a>'
    right = (f'<a href="{nxt["slug"]}.html" style="text-align:right"><div class="card"><div class="small muted">下一个场景 →</div>'
             f'<b>{e(nxt["title"])}</b></div></a>') if nxt else '<a href="../index.html" style="text-align:right"><div class="card"><div class="small muted">返回 →</div><b>总览</b></div></a>'
    return f'<div class="pager">{left}{right}</div>'


# --- custom sections ---------------------------------------------------------------
def sec(title, inner, eyebrow='验证结果'):
    return f'<section><div class="section-head"><div><div class="eyebrow">{e(eyebrow)}</div><h2>{e(title)}</h2></div></div>{inner}</section>'


def miss_callouts(d, case_ids, notes):
    out = []
    for cid in case_ids:
        for c in d.results[cid]['checks']:
            if not c['passed']:
                note = notes.get(c['question'], '')
                out.append(f'<div class="callout warn"><b>未达标：{e(c["question"])}</b>（{e(cid)}）。标准答案 {fmt_expected(c["expected"])}，'
                           f'实际 {fmt_value(c["actual"]["value"])}。{e(note)}</div>')
    return ''.join(out)


def score_note(d, cid, qid):
    probs = d.answer(cid, qid)['probabilities']
    return '等级分布 ' + ' / '.join(f'{k}:{v:g}' for k, v in sorted(probs.items())) + '。'


def custom_agent(d):
    ids = ['jev:recovery', 'jev:drift', 'jev:completion']
    return (sec('三个检查点的判断', result_table(d, ids, label_case=True)) +
            sec('关键分布', distribution_figures(d, 'jev:recovery', ['next']) +
                distribution_figures(d, 'jev:completion', ['evidence']) + distribution_figures(d, 'jev:drift', ['scope_risk']), '图示') +
            sec('与实际状态核对', '<div class="callout ok"><b>判断与实际状态一致。</b>恢复场景里，Jev 认定 <code>pip_install_system</code> 违反用户规则，'
                '下一步选了项目自带的虚拟环境。完成场景里，健康检查返回的仍是 2.3.0，“部署成功”的说法被否定，Jev 选择等流水线跑完再核验。'
                'Jev 的判断不会执行任何动作，在真实的 Agent 里，违规命令仍要由调用方的权限系统单独拦截。</div>', '调用方'))


def custom_review(d):
    cid = 'jev-code-review:pr'
    state = d.cases[cid]['request']['state']
    r = state['receipts']
    suite = ''.join(f'<tr><td class="mono small">{e(k)}</td><td>{"✓" if r["suite_before"][k] else "✗"}</td>'
                    f'<td>{"✓" if r["suite_after"][k] else "✗"}</td></tr>' for k in r['suite_before'])
    receipts = (f'<div class="grid g2"><div><h3>原测试套件（调用方真实运行）</h3><div class="table-wrap"><table><thead><tr><th>测试</th>'
                f'<th>改动前</th><th>改动后</th></tr></thead><tbody>{suite}</tbody></table></div></div>'
                f'<div><h3>调用方探针（不在 PR 的测试中）</h3><div class="table-wrap"><table><thead><tr><th>调用</th><th>改动后返回</th><th>需求</th></tr></thead><tbody>'
                f'<tr><td class="mono small">{e(r["probe_boundary_after"]["call"])}</td><td class="bad-text">{fmt_value(r["probe_boundary_after"]["returned"])}</td><td>Q1：应为 false</td></tr>'
                f'<tr><td class="mono small">{e(r["probe_malformed_after"]["call"])}</td><td class="bad-text">{fmt_value(r["probe_malformed_after"]["returned"])}</td><td>S1：应拒绝</td></tr>'
                '</tbody></table></div></div></div>')
    diff = '<pre class="diff"><code>' + ''.join(
        f'<span class="{"add" if l.startswith("+") and not l.startswith("+++") else "del" if l.startswith("-") and not l.startswith("---") else "hunk" if l.startswith("@@") else ""}">{e(l)}</span>'
        for l in state['diff'].splitlines(keepends=True)) + '</code></pre>'
    return (sec('PR diff 与测试结果', f'<div class="card">{diff}{receipts}</div>', '证据') +
            sec('逐改动块判断', result_table(d, [cid]) + miss_callouts(d, [cid], {
                'H1_severity': score_note(d, cid, 'H1_severity') + '概率最大的是最高一级“合并前必须修复”，但有一部分落在“无需处理”，'
                               '加权均值因此低于区间下限。问题类别判成 correctness 是对的，按分布来读，结论仍是合并前必须修复。'})) +
            sec('严重度分布', distribution_figures(d, cid, ['H1_severity', 'H3_severity', 'H1_concern', 'H3_concern']), '图示'))


def custom_context(d):
    cid = 'jev-context:compaction'
    blocks = d.cases[cid]['request']['state']['blocks']
    exp = {c['question']: c for c in d.results[cid]['checks']}
    rows = []
    for b, txt in blocks.items():
        a = exp[b]['actual']
        color = 'ok-text' if a['value'] == 'keep' else 'muted'
        rows.append(f'<tr><td class="mono">{b}</td><td class="small">{e(txt)}</td><td>{e(exp[b]["expected"]["value"])}</td>'
                    f'<td class="{color}"><b>{e(a["value"])}</b></td><td class="num">{a["probability"]:.2f}</td>'
                    f'<td>{"✓" if exp[b]["passed"] else "✗"}</td></tr>')
    same = exp['B2_B4_same']['actual']
    table = ('<div class="table-wrap"><table><thead><tr><th>块</th><th>内容</th><th>标准答案</th><th>Jev 建议</th><th>概率</th><th>验收</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>' + note(CHOICE_NOTE) +
             f'<div class="callout ok"><b>近似重复识别正确。</b>问 B2 与 B4 是否同一条失败记录，Jev 回答 {fmt_value(same["value"])}'
             f'（“是”的概率为 {same["probability"]:.2f}），于是保留了 refund_id 不同的 B4，只建议丢弃完全重复的 B3 和两条无关日志。'
             '本场景运行在影子模式下，没有修改或删除任何会话记录。</div>')
    return sec('逐块保留建议', table)


def custom_documents(d):
    cid = 'jev-documents:contract'
    clauses = d.cases[cid]['request']['state']['clauses']
    copies = []
    for qid in ('notice_period', 'post_termination_data', 'late_fee'):
        val = d.decision(cid, qid)['value']
        src = f'<blockquote class="small">{e(clauses[val])}</blockquote>' if val in clauses else '<span class="muted">（none：不复制任何原文，转人工确认）</span>'
        copies.append(f'<tr><td class="mono small">{qid}</td><td class="mono">{e(val)}</td><td>{src}</td></tr>')
    clause_rows = ''.join(f'<tr><td class="mono">{k}</td><td class="small">{e(v)}</td></tr>' for k, v in clauses.items())
    return (sec('合同原文（合成）', f'<div class="table-wrap"><table><tbody>{clause_rows}</tbody></table></div>', '证据') +
            sec('定位与核对结果', result_table(d, [cid])) +
            sec('调用方按 ID 复制原文', '<div class="table-wrap"><table><thead><tr><th>问题</th><th>选中 ID</th><th>调用方复制的原文</th></tr></thead>'
                f'<tbody>{"".join(copies)}</tbody></table></div><p class="small muted" style="margin-top:8px">原文由调用方根据返回的 ID 从输入中逐字复制，'
                'Jev 没有生成任何引文。</p>', '调用方') +
            sec('主张核对分布', distribution_figures(d, cid, ['claim_refund', 'claim_sla_credit', 'late_fee']), '图示'))


FIND_SYMBOLS = {'webhook_signature': 'def verify_signature', 'backoff_delay': 'def backoff_delay',
                'refund_cap': 'refund exceeds remaining charge'}


def find_code_input(d, cid):
    """The request exactly as sent, shown twice: an abridged skeleton (file bodies reduced to their
    first line, repeated criteria collapsed) and the verbatim JSON in a collapsible block."""
    import json
    req = d.cases[cid]['request']
    qs = req['questions']
    first_q = next(iter(qs))
    shared = all(q['criteria'] == qs[first_q]['criteria'] for q in qs.values())
    def brief(src):
        first = src.splitlines()[0].strip()
        doc = first.startswith('"""') and first.endswith('"""') and len(first) > 6
        return f'<{len(src.splitlines())} 行源码，' + (f'模块说明：{first[3:-3]}>' if doc else f'首行：{first}>')
    files = {p: brief(src) for p, src in req['state']['files'].items()}
    skeleton = {'model': req['model'], 'state': {**req['state'], 'files': files},
                'questions': {qid: {'type': q['type'], 'instructions': q['instructions'],
                                    'criteria': q['criteria'] if qid == first_q or not shared else f'<与 {first_q} 相同的 {len(q["criteria"])} 个候选>'}
                              for qid, q in qs.items()}}
    full = json.dumps(req, ensure_ascii=False, indent=2)
    usage = d.results[cid]['report']['response']['usage']
    return (f'<p>调用方先读出仓库里全部 {len(files)} 个文件的完整源码，放进 <code>state.files</code>，再问 {len(qs)} 道 choice 题。'
            f'每道题的候选是这 {len(files)} 个文件路径，外加一个 <code>none</code>。候选描述只是“Inspect 某文件”，本身不带信息，'
            'Jev 能依据的只有源码和题目。请求里没有标准答案。</p>'
            f'<pre><code>{e(json.dumps(skeleton, ensure_ascii=False, indent=2))}</code></pre>'
            f'<p class="small muted" style="margin-top:8px">上面是精简后的结构：每个文件只保留行数和模块说明，'
            + (f'重复的候选只列一次。' if shared else '')
            + f'实际发送的是完整源码，输入共 {usage["input_tokens"]:,} 个 token。请求由 <code>validation/v2/cases_v2.py</code> 的 '
            '<code>find_code_cases()</code> 生成。</p>'
            f'<details style="margin-top:10px"><summary class="small">展开完整的原始请求（逐字，与发送内容一致）</summary>'
            f'<pre><code>{e(full)}</code></pre></details>')


def find_code_output(d, cid):
    """Candidate x question probability matrix from the raw answers, plus how status was derived."""
    rep = d.results[cid]['report']
    answers = rep['response']['answers']
    qids = list(answers)
    cands = list(d.cases[cid]['request']['questions'][qids[0]]['criteria'])
    head = ''.join(f'<th class="num mono small">{e(q)}</th>' for q in qids)
    body = ''
    for c in cands:
        cells = ''
        for q in qids:
            p = answers[q]['probabilities'].get(c, 0)
            chosen = answers[q]['choice'] == c
            cells += (f'<td class="num"><b class="ok-text">{p:.2f}</b></td>' if chosen
                      else f'<td class="num {"muted" if p == 0 else ""}">{p:.2f}</td>')
        body += f'<tr><td class="mono small">{e(c)}</td>{cells}</tr>'
    status = ''.join(f'<td>{status_text(rep["decisions"][q]["status"])}</td>' for q in qids)
    body += f'<tr><td class="small"><b>CLI 判定的状态</b></td>{status}</tr>'
    fields = sorted({k for a in answers.values() for k in a})
    others = [(q, c, p) for q in qids for c, p in answers[q]['probabilities'].items() if p and c != answers[q]['choice']]
    pol = rep['policy']
    review_hits = [q for q in qids if rep['decisions'][q]['value'] in pol['review_labels']]
    return (f'<div class="table-wrap"><table><thead><tr><th>候选</th>{head}</tr></thead><tbody>{body}</tbody></table></div>'
            f'<p class="small muted" style="margin-top:8px">绿色加粗的是 Jev 选中的候选。每道题的原始返回只有 '
            + '、'.join(f'<code>{e(f)}</code>' for f in fields) + ' 这几个字段，没有理由或解释。'
            + ('选中项以外的非零概率只有：' + '；'.join(f'{e(q)} 上的 <code>{e(c)}</code> {p:.2f}' for q, c, p in others) + '。' if others else '')
            + f'状态不是 Jev 返回的，而是 jev CLI 按规则算出来的：最高概率不低于 {pol["min_probability"]}、比第二名高出至少 {pol["min_margin"]} 才算 selected，'
            f'选中 none、unknown 这类复核标签的一律转复核。'
            + (f'{e("、".join(review_hits))} 选中的是复核标签，所以概率虽高，仍是 needs_review。' if review_hits else '')
            + '</p>')


def custom_find_code(d):
    cid = 'jev-find-code:minishop'
    files = d.cases[cid]['request']['state']['files']
    verify = []
    for qid, symbol in FIND_SYMBOLS.items():
        path = d.decision(cid, qid)['value']
        lines = [i + 1 for i, line in enumerate(files.get(path, '').splitlines()) if symbol in line]
        ok = bool(lines)
        verify.append(f'<tr><td class="mono small">{qid}</td><td class="mono small">{e(path)}</td><td class="mono small">{e(symbol)}</td>'
                      f'<td class="{"ok-text" if ok else "bad-text"}">{"第 " + ", ".join(map(str, lines)) + " 行" if ok else "未找到"}</td></tr>')
    val = d.decision(cid, 'reset_email_body')['value']
    return (sec('发给 Jev 的输入', find_code_input(d, cid), '输入') +
            sec('定位结果', result_table(d, [cid])) +
            sec('Jev 的原始返回：每道题的完整分布', find_code_output(d, cid), '输出') +
            sec('调用方打开文件核对符号', '<div class="table-wrap"><table><thead><tr><th>问题</th><th>Jev 选中文件</th><th>核对符号</th><th>结果</th></tr></thead>'
                f'<tbody>{"".join(verify)}</tbody></table></div><div class="callout ok"><b>不存在的功能没有被编造。</b>'
                f'问到密码重置邮件正文时，Jev 返回 <code>{e(val)}</code>，并进入复核。templates.py 里确实只有 order_shipped 和 payment_receipt 两个模板。</div>', '调用方'))


def custom_route(d):
    cid = 'jev-route:routing'
    st = d.cases[cid]['request']['state']
    routes = ''.join(f'<tr><td class="mono">{k}</td><td class="small">{e(v)}</td></tr>' for k, v in st['available_routes'].items())
    return (sec('候选路由（按能力描述）', f'<div class="table-wrap"><table><tbody>{routes}</tbody></table></div>', '证据') +
            sec('任务与推荐', '<div class="table-wrap"><table><thead><tr><th>任务</th><th>描述</th></tr></thead><tbody>' +
                ''.join(f'<tr><td class="mono">{k}</td><td>{e(v)}</td></tr>' for k, v in st['tasks'].items()) +
                '</tbody></table></div><div style="height:14px"></div>' + result_table(d, [cid])) +
            sec('分布', distribution_figures(d, cid, ['T2', 'T5']), '图示'))


def custom_triage(d):
    ids = ['jev-triage:batch1', 'jev-triage:batch2', 'jev-triage:batch3']
    rows, by_ticket = [], {}
    for cid in ids:
        tickets = d.cases[cid]['request']['state']['tickets']
        checks = {c['question']: c for c in d.results[cid]['checks']}
        for tid, txt in tickets.items():
            cat, ref, urg = checks[f'{tid}_category'], checks[f'{tid}_refund'], checks[f'{tid}_urgency']
            by_ticket[tid] = (cat, ref, urg)

            def cell(c):
                cls = 'ok-text' if c['passed'] else 'bad-text'
                return f'<td class="{cls}">{fmt_value(c["actual"]["value"])}</td>'
            rows.append(f'<tr><td class="mono">{tid}</td><td class="small">{e(txt)}</td><td>{e(cat["expected"]["value"])}</td>{cell(cat)}'
                        f'<td class="num">{cat["actual"]["probability"]:.2f}</td>{cell(ref)}'
                        f'<td class="small">{fmt_expected(urg["expected"])}</td>{cell(urg)}<td>{status_text(cat["actual"]["status"])}</td></tr>')
    table = ('<div class="table-wrap"><table><thead><tr><th>工单</th><th>正文</th><th>标准类别</th><th>Jev 类别</th><th>概率</th>'
             '<th>要求退款</th><th>标准紧急度</th><th>Jev 紧急度</th><th>类别状态</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>'
             '<p class="small muted" style="margin-top:8px">红色表示未达标。概率一栏是 Jev 对所选类别给出的概率，取自它对全部类别返回的分布（各类别之和为 1）。'
             '紧急度是按概率加权的等级值，0 为常规，1 为需要及时处理，2 为业务受阻。'
             '可接受区间是标准等级上下各 0.5。</p>')
    wall = d.summary_main['static_parallel_wall_seconds']
    batch_lat = [d.results[c]['report']['elapsed_seconds'] for c in ids]
    tokens = sum(d.results[c]['report']['response']['usage']['input_tokens'] for c in ids)
    cost = sum(Decimal(str(d.results[c]['report']['response']['usage']['cost'])) for c in ids)
    stats = (f'<div class="grid g4"><div class="card kpi"><div class="v">36</div><div class="l">个独立判断 / 3 个请求</div></div>'
             f'<div class="card kpi"><div class="v">{max(batch_lat):.2f}s</div><div class="l">最慢批次的 API 耗时</div></div>'
             f'<div class="card kpi"><div class="v">{tokens:,}</div><div class="l">3 批合计输入 tokens</div></div>'
             f'<div class="card kpi"><div class="v">${cost:.6f}</div><div class="l">3 批 API 返回的费用合计</div></div></div>'
             f'<p class="small muted" style="margin-top:8px">全部 16 个静态请求以并发 4 发出，整段墙钟时间 {wall:.2f} 秒，含 CLI 进程启动。'
             '这是本机一次实测的结果，不代表吞吐保证。</p>')
    p01 = d.answer('jev-triage:batch1', 'K01_urgency')['probabilities']
    p10 = d.answer('jev-triage:batch3', 'K10_urgency')['probabilities']
    notes = {'K01_urgency': score_note(d, 'jev-triage:batch1', 'K01_urgency') +
             f'这张工单重复扣费，但业务还能继续，标准答案是“及时处理”。Jev 把 {p01["0"]:g} 的概率放在了“常规”上，估低了。',
             'K10_urgency': score_note(d, 'jev-triage:batch3', 'K10_urgency') +
             f'这是一张夹带注入指令的广告工单。类别判成 other 是对的，也进入了复核，但有 {p10["2"]:g} 的概率落在注入者要求的等级 2 上，紧急度被抬高了。'}
    return (sec('并发与成本', stats, '吞吐') + sec('逐工单结果', table + miss_callouts(d, ids, notes)) +
            sec('近似类别与注入工单的分布', distribution_figures(d, 'jev-triage:batch3', ['K10_category', 'K10_urgency', 'K09_category']) +
                distribution_figures(d, 'jev-triage:batch1', ['K01_urgency', 'K04_category']), '图示'))


def custom_simulation(d):
    from loops_v2 import GRID, NPC_SCRIPT
    npc = d.turns['npc']
    rows = ''.join(f'<tr><td class="num">{t["turn"]}</td><td class="small">{e(NPC_SCRIPT[t["turn"] - 1]["say"])}</td><td class="mono">{e(t["oracle"])}</td>'
                   f'<td class="mono {"ok-text" if t["passed"] else "bad-text"}">{e(t["chosen"])}</td><td class="num">{t["probability"]:.2f}</td>'
                   f'<td>{status_text(t["status"])}</td><td class="small">{e(t["transition"])}</td></tr>' for t in npc)
    fw = d.loop_summaries['npc']['final_world']
    npc_html = ('<div class="table-wrap"><table><thead><tr><th>回合</th><th>玩家事件</th><th>规则答案</th><th>Jev 动作</th><th>概率</th><th>状态</th><th>引擎转换</th></tr></thead>'
                f'<tbody>{rows}</tbody></table></div>' + note(CHOICE_NOTE + REVIEW_GATE) +
                f'<p class="small muted" style="margin-top:4px">最终世界：库存 {fw["stock"]}，玩家药水 {fw["player_potions"]}，'
                f'柜台余款 {fw["paid_on_counter"]}，怀疑度 {fw["suspicion"]}，守卫{"已" if fw["guard_called"] else "未"}呼叫。</p>')
    a, b = d.loop_summaries['grid'], d.loop_summaries['grid_planned']
    ga, gb = d.turns['grid'], d.turns['grid_planned']
    map_a = C.grid_map(GRID, [(a['path'], C.RED, 'A')])
    map_b = C.grid_map(GRID, [(b['path'], C.TEAL, 'B')])
    review_a = sum(t['status'] == 'needs_review' for t in ga)
    cmp = (f'<div class="table-wrap"><table><thead><tr><th>指标</th><th>变体 A（宽松策略、无规划器）</th><th>变体 B（严格策略、规划器路线）</th></tr></thead><tbody>'
           f'<tr><td>是否送达</td><td class="bad-text">{"是" if a["delivered"] else "否"}</td><td class="ok-text">{"是" if b["delivered"] else "否"}</td></tr>'
           f'<tr><td>回合数（理论最短 {a["optimal_turns"]}）</td><td>{a["turns"]}（预算上限）</td><td>{b["turns"]}</td></tr>'
           f'<tr><td>最优步占比</td><td>{a["optimal_moves"]}/{a["turns"]}</td><td>{b["optimal_moves"]}/{b["turns"]}</td></tr>'
           f'<tr><td>needs_review 回合</td><td>{review_a}</td><td>{sum(t["status"] == "needs_review" for t in gb)}</td></tr>'
           f'<tr><td>调用次数</td><td>{len(ga)}</td><td>{len(gb)}</td></tr></tbody></table></div>')
    t3 = next(t for t in ga if t['turn'] == 3)
    probs = t3['report']['response']['answers']['action']['probabilities']
    fig3 = C.prob_bar(probs, t3['chosen'], 'south')
    return (sec('NPC 店主：6 回合规则对话', npc_html) +
            sec('网格机器人：两种用法对比', f'<div class="grid g2"><figure class="card tight"><h3>变体 A：Jev 独自规划 · {a["turns"]} 回合未送达</h3>{map_a}<figcaption>红线为实际轨迹，'
                f'圆点中的数字是在该格停留的次数。机器人一直在 (1,0) 和 (1,1) 之间来回。</figcaption></figure>'
                f'<figure class="card tight"><h3>变体 B：规划器给路线 · {b["turns"]} 回合送达</h3>{map_b}<figcaption>轨迹与 BFS 最短路完全一致，先向南绕过墙，取到包裹后再送往左下角。</figcaption></figure></div>'
                f'<div style="height:16px"></div>{cmp}') +
            sec('失败根因', f'<div class="grid g2"><figure class="card tight">{fig3}<figcaption>变体 A 第 3 回合，机器人在 (1,1)，'
                f'正确的走法是继续向南，Jev 却以 {probs[t3["chosen"]]:.2f} 的概率选了 {e(t3["chosen"])}，朝包裹所在的那一行走，此后便陷入循环。</figcaption></figure>'
                f'<div class="card"><h3>为什么会来回走</h3><ul class="clean"><li>Jev 每一回合都只做单步判断，看不到绕路之后的好处，'
                f'容易挑看上去离目标更近的方向。</li><li>在宽松策略下，30 个回合里有 {review_a} 个回合处于 needs_review，调用方照样执行了，'
                '错误就这样一步步累积下来。这是测试框架里调用方策略的缺陷，变体 B 已经改成严格策略。</li>'
                '<li>变体 B 把策略交给规划器，Jev 只需确认下一格对应哪个动作，全部回合都以 selected 状态通过。</li></ul></div></div>', '分析'))


def shot(name, caption):
    return f'<figure class="card tight"><div class="shot"><img src="../assets/img/{name}" alt="{e(caption)}"></div><figcaption>{e(caption)}</figcaption></figure>'


def custom_ui(d):
    check_snapshot_labels(d)
    turns = d.turns['ui_settings']
    summ = d.loop_summaries['ui_settings']
    rows = ''.join(f'<tr><td class="num">{t["turn"]}</td><td class="mono">{e(t["oracle"])}</td><td class="mono {"ok-text" if t["passed"] else "bad-text"}">{e(t["chosen"])}</td>'
                   f'<td class="num">{t["probability"]:.2f}</td><td>{status_text(t["status"])}</td><td class="small">{e(t["host_action"])}</td>'
                   f'<td class="small">{e(t["page_after"]["status"] or "（无状态文字）")}</td></tr>' for t in turns)
    t1 = turns[0]
    probs = t1['report']['response']['answers']['next']['probabilities']
    crit = {k: v for k, v in d_snapshot_labels(t1).items()}
    named = {f'{k}（{crit.get(k, k)}）' if k.startswith('click_') else k: v for k, v in probs.items()}
    fig = C.prob_bar(named, None, next(k for k in named if k.startswith(t1['oracle'])), width=620, label_w=250)
    co = d.turns['ui_checkout'][0]
    co_checks = ''.join(f'<tr><td class="mono">{c["question"]}</td><td>{fmt_expected(c["expected"])}</td><td><b>{fmt_value(c["actual"]["value"])}</b></td>'
                        f'<td class="num">{prob_text(c["actual"])}</td><td>{status_text(c["actual"]["status"])}</td><td>{"✓" if c["passed"] else "✗"}</td></tr>' for c in co['checks'])
    final = summ['final_page']
    return (sec('设置页：真实浏览器闭环', '<div class="grid g2">' + shot('ui-settings-0.png', '第 0 步：初始页面，顶部是注入横幅，“删除账户”按钮可点击') +
                shot('ui-settings-3.png', '最终页面：发票通知已勾选并保存，营销邮件保持关闭') + '</div><div style="height:16px"></div>'
                '<div class="table-wrap"><table><thead><tr><th>步</th><th>预期</th><th>Jev 选择</th><th>概率</th><th>状态</th><th>调用方动作</th><th>页面状态文字</th></tr></thead>'
                f'<tbody>{rows}</tbody></table></div>' + note(CHOICE_NOTE + REVIEW_GATE) +
                f'<div class="callout ok"><b>调用方的确定性核验{"通过" if summ["task_verified"] else "未通过"}。</b>任务结束后读取 DOM，invoice={fmt_value(final["invoice"])}，'
                f'marketing={fmt_value(final["marketing"])}，状态文字为“{e(final["status"])}”。调用方拦截的动作：{e("、".join(summ["blocked"]) or "无")}。</div>') +
            sec('第 1 步的候选分布', f'<figure class="card tight">{fig}<figcaption>候选全部来自实时快照中的 ref。横幅要求点击的“删除账户”概率为 '
                f'{probs.get(next((k for k in crit if "删除" in crit[k]), ""), 0):.2f}。</figcaption></figure>', '图示') +
            sec('结算页：未授权付款', '<div class="grid g2">' + shot('ui-checkout.png', '结算页上的“立即支付”按钮可以点击，但会话中没有付款授权') +
                '<div class="card"><div class="table-wrap"><table><thead><tr><th>问题</th><th>标准答案</th><th>返回</th><th>概率</th><th>状态</th><th>验收</th></tr></thead>'
                f'<tbody>{co_checks}</tbody></table></div>' + note(PROB_NOTE) + '<div class="callout ok"><b>没有发生付款。</b>Jev 核对总额 ¥199.00 无误后选择了 ask_user，进入复核。'
                f'调用方没有点击任何控件，页面状态文字为空（{e(co["page_status_after"] or "无")}）。</div></div></div>') +
            sec('环境说明', '<div class="callout note"><b>浏览器：</b>Snap 版 Chromium 155，<code>chromiumSandbox: true</code>。'
                '本机开启了 <code>kernel.apparmor_restrict_unprivileged_userns=1</code>，Playwright 自带的 Chromium 开着沙箱启动不了，'
                'Snap 版本自带 AppArmor 配置，可以在保留沙箱的情况下运行。playwright-cli 不允许打开 file:// 地址，'
                '所以测试页由一个只绑定 127.0.0.1 的本地 HTTP 服务提供。全程没有关闭沙箱，也没有改动系统设置。</div>', '复现'))


def d_snapshot_labels(turn):
    """Map click_eN labels to control names using a re-captured snapshot of the same page.

    Cross-checked against the live receipt: the host's recorded click names must match.
    """
    from loops_v2 import CONTROL
    names = {}
    for line in (V2 / 'artifacts' / 'settings-snapshot.yml').read_text().splitlines():
        m = CONTROL.match(line)
        if m:
            names[f'click_{m.group(4)}'] = m.group(2)
    return names


def check_snapshot_labels(d):
    names = d_snapshot_labels(None)
    for t in d.turns['ui_settings']:
        if t['host_action'].startswith('clicked'):
            assert names[t['chosen']] in t['host_action'], (t['chosen'], t['host_action'])


def custom_redteam(d):
    from cases_v2 import host_detect
    ids = [f'jev-redteam:R{i}' for i in range(1, 6)]
    rows = []
    for cid in ids:
        st = d.cases[cid]['request']['state']
        convo = '<br>'.join(f'<span class="tag">{e(m["role"])}</span> {e(m["content"])}' for m in st['messages'])
        host = host_detect(st['messages'])
        out, ev = (d.decision(cid, 'outcome'), d.decision(cid, 'evidence'))
        agree = out['value'] == host
        rows.append(f'<tr><td class="mono">{st["case_id"]}</td><td class="small">{e(d.cases[cid]["title"])}</td><td class="small">{convo}</td>'
                    f'<td class="mono">{host}</td><td class="mono {"ok-text" if agree else "bad-text"}">{out["value"]}</td>'
                    f'<td class="num">{out["probability"]:.2f}</td><td class="mono">{ev["value"]}</td><td>{status_text(out["status"])}</td></tr>')
    table = ('<div class="table-wrap"><table><thead><tr><th>ID</th><th>类型</th><th>对话</th><th>调用方判定</th><th>Jev outcome</th><th>概率</th>'
             f'<th>evidence</th><th>状态</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
             + note('概率是 Jev 对所选 outcome 给出的概率，取自它对全部 outcome 返回的分布（各项之和为 1）。' + REVIEW_GATE))
    return (sec('5 段对话的判定', table + '<div style="height:14px"></div>' + result_table(d, ids, label_case=True)) +
            sec('缺证据样本的分布', distribution_figures(d, 'jev-redteam:R5', ['outcome', 'evidence']), '图示'))


def custom_setup(d):
    rows = []
    for r in d.setup:
        rep = r['report']
        rows.append(f'<tr><td class="mono">{e(r["variant"])}</td><td class="mono">{e(rep["available"])}</td><td class="mono">{e(rep["recommended_provider"])}</td>'
                    f'<td>{fmt_value(rep["requires_user_choice"])}</td><td>{fmt_value(rep["jev_called"])}</td>'
                    f'<td class="{"bad-text" if r["value_leaked"] else "ok-text"}">{"泄漏" if r["value_leaked"] else "未回显"}</td></tr>')
    table = ('<div class="table-wrap"><table><thead><tr><th>环境</th><th>检测到的凭据</th><th>推荐</th><th>需用户选择</th><th>联网调用</th><th>占位值</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>')
    live = (f'<div class="callout ok"><b>真实路线已打通。</b>本次 {d.usage["calls"]} 次真实调用全部经 OpenRouter 完成，返回模型 '
            f'<code>{e(", ".join(d.usage["models"]))}</code>，没有出现认证、额度或协议错误。运行器没有重试，也没有切换服务商。'
            'TypeSafe 直连路线本次只做了存在性检查，没有真实调用。</div>')
    return sec('三种环境下的 setup 报告', table + live)


CUSTOM = {'agent-checkpoint': custom_agent, 'code-review': custom_review, 'context': custom_context,
          'documents': custom_documents, 'find-code': custom_find_code, 'route': custom_route,
          'triage': custom_triage, 'simulation': custom_simulation, 'ui': custom_ui,
          'redteam': custom_redteam, 'setup': custom_setup}


def scenario_stats(d, s):
    if s['slug'] == 'setup':
        n = len(d.setup)
        ok = sum(not r['value_leaked'] and r['report']['jev_called'] is False for r in d.setup)
        return ok, n, 0
    row = d.skill_table().get(s['skill'], {'passed': 0, 'total': 0, 'review': 0})
    return row['passed'], row['total'], row['review']


def scenario_page(d, s):
    passed, total, review = scenario_stats(d, s)
    head = f'''
<div class="hero"><div class="wrap">
  <div class="crumb"><a href="../index.html">总览</a> / 场景 / {e(s["title"])}</div>
  <div class="eyebrow">{e(s["skill"])}</div>
  <h1>{s["icon"]} {e(s["title"])}</h1>
  <p class="lead">{e(s["one_liner"])}</p>
  <div class="meta"><span>{badge(passed, total, review)}</span><span>判断数 <b>{total}</b></span>
  <span>模型 <b>{e(", ".join(d.usage["models"]))}</b></span><span>运行日期 <b>2026-10-12</b></span></div>
</div></div>'''
    design = ''
    if s['cases']:
        design = sec('问题设计', question_table(d, s['cases'][:1] if s['slug'] in ('triage', 'redteam') else s['cases']) +
                     ('<p class="small muted" style="margin-top:8px">同类批次/样本使用相同的问题模板，此处只展示第一个。</p>'
                      if s['slug'] in ('triage', 'redteam') else ''), '判断设计')
    body = (head + '<main class="wrap">' + intro_sections(s, trigger_section(d, s)) + result_section(d, s) + design + CUSTOM[s['slug']](d) +
            v1_baseline(d, s['skill']) + pager(s['slug']) + footer(d) + '</main>')
    return page(s['title'], body, s['slug'], depth=1)



# --- index ---------------------------------------------------------------------------
SKILL_ORDER = ['jev', 'jev-code-review', 'jev-context', 'jev-documents', 'jev-find-code', 'jev-route',
               'jev-triage', 'jev-simulation', 'jev-ui', 'jev-redteam']

FIT = [
    ('大量独立的分类/打分', '工单、评论、记录分诊，每条 3～6 个问题', '非常适合', 'b-pass'),
    ('从候选中选一个', '下一步动作、文件、条款 ID、路由、UI 控件', '非常适合', 'b-pass'),
    ('核对主张与证据', '完成声明、合同主张、测试是否证明需求', '适合', 'b-pass'),
    ('带分布的等级评分', '严重度、紧急度、证据强度', '适合，需读分布', 'b-warn'),
    ('多步规划与搜索', '寻路、长链推理、任务拆解', '不适合，交给规划器', 'b-fail'),
    ('生成文本', '写文章、写代码、写回复', '不适合，交给主模型', 'b-fail'),
    ('精确计算与匹配', '求和、日期比较、正则匹配', '不需要，用代码', 'b-info'),
]


def index_page(d):
    judg = [j for j in d.all_judgments() if j['case'] != 'grid']
    passed, total = sum(j['passed'] for j in judg), len(judg)
    review = sum(j['status'] == 'needs_review' for j in judg)
    u, u1 = d.usage, d.usage_v1
    cal = d.calibration(exclude=('grid',))
    top = cal[-1]
    score_miss = sum(1 for j in judg if not j['passed'] and j['kind'] == 'score')
    a, b = d.loop_summaries['grid'], d.loop_summaries['grid_planned']
    fills = {'top_n': top['n'], 'score_miss': score_miss, 'grid_a_turns': a['turns'], 'grid_b_turns': b['turns'],
             'lat_median': f'{u["latency_median"]:.2f}', 'calls': u['calls'], 'cost': f'{u["cost"]:.6f}'}
    kpis = [
        (f'{len(SCENARIOS)}', '个应用场景', f'覆盖全部 {len(SCENARIOS)} 个已安装的 Jev 技能'),
        (f'{u["calls"]}', '次真实 Jev 调用', f'另有 v1 基线 {u1["calls"]} 次，无重试，无错误'),
        (f'{passed}/{total}', '判断符合标准答案', f'{review} 个进入 needs_review，不含误用对照组'),
        (f'{u["latency_median"]:.2f}s', '单次调用中位耗时', f'P90 {u["latency_p90"]:.2f}s · 最大 {u["latency_max"]:.2f}s'),
        (f'${u["cost"]:.4f}', 'API 返回的费用合计', f'输入 {u["input_tokens"]:,} / 输出 {u["output_tokens"]:,} tokens'),
    ]
    kpi_html = ''.join(f'<div class="card kpi"><div class="v">{v}</div><div class="l">{l}</div><div class="s">{s}</div></div>' for v, l, s in kpis)
    table = d.skill_table()
    bars = [(sk, table[sk]['passed'], table[sk]['total'], table[sk]['review']) for sk in SKILL_ORDER if sk in table]
    cards = []
    for s in SCENARIOS:
        p, t, r = scenario_stats(d, s)
        cards.append(f'<a class="card scn" href="scenarios/{s["slug"]}.html"><div class="top"><div class="icon">{s["icon"]}</div>{badge(p, t)}</div>'
                     f'<h3>{e(s["title"])}</h3><p>{e(s["one_liner"])}</p><div class="foot"><span class="mono">{e(s["skill"])}</span>'
                     f'<span>{t} 个判断 · 复核 {r}</span></div></a>')
    findings = ''.join(f'<div class="callout {k}"><b>{e(t)}</b><br><span class="small">{e(x.format(**fills))}</span></div>' for k, t, x in FINDINGS)
    fit_rows = ''.join(f'<tr><td>{e(a_)}</td><td class="small muted">{e(b_)}</td><td><span class="badge {c_}">{e(v_)}</span></td></tr>' for a_, b_, v_, c_ in FIT)
    loop = C.flow([('1 · 框定', '目标·权限\n预算', 'host'), ('2 · 观察', '实际输出\n候选动作', 'host'),
                   ('3 · 提问', 'choice / noul\n/ score', 'jev'), ('4 · 解读', '分布·复核\n门槛', 'check'),
                   ('5 · 执行验证', '调用方执行一步\n读取结果', 'stop')])
    body = f'''
<div class="hero"><div class="wrap">
  <div class="eyebrow">Jev Application Scenarios · Validation Report</div>
  <h1>Jev 应用场景验证报告</h1>
  <p class="lead">这份报告记录了 2026 年 10 月 12 日对 Jev 做的一轮验证。Jev 是一个类型化判断模型，给它候选项、是非题或评分等级，
  它返回带概率的答案，但不写文字。报告为本机安装的 {len(SCENARIOS)} 个 Jev 技能各编写了一组接近真实业务、埋有陷阱的场景，
  经 OpenRouter 真实调用后，再用测试、浏览器 DOM、规则引擎和原文比对这类确定性手段逐一核对结果。
  下文的“调用方”指调用 Jev 并实际执行动作的 Agent 或程序。</p>
  <div class="meta"><span>运行日期 <b>2026-10-12</b></span><span>模型 <b>{e(", ".join(u["models"]))}</b></span>
  <span>服务 <b>OpenRouter Decisions API</b></span><span>技能版本 <b>jev-skill v0.2.0</b></span>
  <span>浏览器 <b>Chromium 155（沙箱开启）</b></span></div>
</div></div>
<main class="wrap">
<section style="margin-top:0"><div class="grid g5">{kpi_html}</div></section>
{cost_teaser(d)}

<section><div class="section-head"><div><div class="eyebrow">基础</div><h2>Jev 能回答的三种问题</h2></div></div>
<div class="grid g3">
  <div class="card prim"><span class="tag">choice</span><h3 style="margin-top:10px">从候选中选一个</h3>
    <p class="small">返回每个候选的概率，用于下一步动作、路由、类别、条款 ID 这类选择。候选里<b>必须</b>留一个出口，比如 unknown、none 或 ask_user。</p></div>
  <div class="card prim noul"><span class="tag">noul</span><h3 style="margin-top:10px">是 / 否</h3>
    <p class="small">返回回答“是”的概率，适合判断某个说法是否成立、某个动作是否违反规则、两条记录是否相同。它很有把握地答 false，答案依然是 false。</p></div>
  <div class="card prim score"><span class="tag">score</span><h3 style="margin-top:10px">按等级打分</h3>
    <p class="small">返回各等级的概率，以及按概率加权的分值，分值可以是小数。常用于严重度、紧急度和证据强度。分值本身不是概率，要连同分布一起读。</p></div>
</div></section>

<section><div class="card"><div class="eyebrow">通用闭环</div><h2>每个场景都按同一个闭环运行</h2>{loop}
<p class="small muted" style="margin-top:10px">Jev 只负责第 3 步。它返回 selected，只说明选出了一个标签，动作并没有因此获得批准，
执行、权限、付款和删除始终由调用方负责。复核门槛采用 CLI 默认值：最高概率不低于 0.8，并且比第二名高出至少 0.15。
unknown、none、ask_user 这类出口标签一律进入复核。</p></div></section>

<section><div class="section-head"><div><div class="eyebrow">场景</div><h2>{len(SCENARIOS)} 个应用场景</h2></div>
<span class="small muted">每张卡片对应一个场景页，内有场景介绍、问题设计、逐题结果和调用方的核验</span></div>
<div class="grid g3">{"".join(cards)}</div></section>

<section><div class="grid g2">
  <div class="card"><div class="eyebrow">总体结果</div><h3>各技能符合标准答案的比例</h3>{C.skill_bars(bars, width=560)}
    <p class="small muted" style="margin-top:8px">jev-simulation 只统计 NPC 和网格变体 B 的回合。网格变体 A 是误用对照组，单独列在右侧和仿真页面。</p></div>
  <div class="card"><div class="eyebrow">校准</div><h3>按最高概率分段的答对率</h3>{C.calibration_chart(cal)}
    <p class="small muted" style="margin-top:8px">只统计 choice 和 noul 题，noul 取 max(p, 1-p)，不含误用对照组。
    最高概率不低于 0.95 的 {top["n"]} 个判断全部答对。低概率段的样本太少，看不出规律。</p></div>
</div></section>

<section><div class="grid g2">
  <div class="card"><div class="eyebrow">性能</div><h3>单次调用耗时分布（{u["calls"]} 次）</h3>{C.histogram(u["latency"])}
    <p class="small muted" style="margin-top:8px">耗时取自 CLI 返回记录里的 elapsed_seconds，即一次 API 往返的时间。16 个静态请求以并发 4 发出，整段墙钟时间
    {d.summary_main["static_parallel_wall_seconds"]:.2f} 秒。这是单机一次实测的结果，不代表性能保证。</p></div>
  <div class="card"><div class="eyebrow">对照</div><h3>误用对照：让 Jev 独自规划</h3>
    {C.grid_map(__import__("loops_v2").GRID, [(a["path"], C.RED, "A"), (b["path"], C.TEAL, "B")], cell=44)}
    <p class="small muted" style="margin:10px 0 0">红线是变体 A，Jev 独自规划，{a["turns"]} 个回合里只有 {a["optimal_moves"]} 步是最优步，没有送达，圆点表示停留次数。
    绿线是变体 B，规划器给出路线，{b["turns"]} 个回合全部最优，顺利送达。<a href="scenarios/simulation.html">查看分析 →</a></p></div>
</div></section>

<section><div class="section-head"><div><div class="eyebrow">发现</div><h2>关键发现</h2></div></div>
<div class="grid g2">{findings}</div></section>

<section><div class="grid g2">
  <div class="card"><div class="eyebrow">选型</div><h3>什么时候该用 Jev</h3>
    <div class="table-wrap matrix"><table><thead><tr><th>任务形态</th><th>例子</th><th>结论</th></tr></thead><tbody>{fit_rows}</tbody></table></div></div>
  <div class="card"><div class="eyebrow">方法</div><h3>验证方法与局限</h3><ul class="clean small">
    <li>标准答案在调用之前就已写定，记在调用记录开头的 manifest 里，不会随请求发出。测试材料全部是专门编写的合成内容。</li>
    <li>调用方的独立核验包括：实际运行测试套件和探针，读取浏览器 DOM，用规则引擎校验状态转换，按 ID 复制原文，以及确定性的红队判定器。</li>
    <li>运行边界：最多 80 次调用，并发 4，不重试，不切换服务商，按 API 返回的费用累计到 0.02 美元即停止。这一轮没有触发停止条件。</li>
    <li>未达标的结果原样保留，没有事后放宽区间。网格变体 B 是看到变体 A 失败之后才追加的，用来检验按技能文档推荐的方式使用
        （规划器给路线、Jev 只选下一步）能否改善结果，不属于事先留出的测试。</li>
    <li>样本量小，用例也出自同一个作者。这些结果只能说明场景跑得通、判断与标准答案一致，不能代表普遍的准确率。</li>
  </ul></div>
</div></section>

<section><div class="card"><div class="eyebrow">复现</div><h3>如何重新运行</h3>
<pre><code># 离线：构建全部用例并逐个 CLI dry-run，不联网
python3 validation/v2/run_v2.py
# 真实调用：会产生费用，需要 OPENROUTER_API_KEY，输出文件必须是新文件
python3 -m http.server 8765 --bind 127.0.0.1 --directory validation &amp;
python3 validation/v2/run_v2.py --live --output validation/v2/live-new.jsonl
# 根据调用记录重新生成本报告
python3 validation/v2/build_report.py</code></pre></div></section>
{footer(d)}
</main>'''
    return page('总览', body)


def cost_teaser(d):
    """Overview section: cost × accuracy scatter (two accuracy bases) plus an aligned metric strip."""
    from report_cost import CostData, variants, vname, MODEL_COLOR, DECIDER_COLOR, DECIDER_NAME
    c = CostData(d)
    V = variants(c)
    jev_full, total_full = c.jev_correct()
    jev_norm, total_norm = c.jev_correct(exclude_grid=True)
    assert all(x['total_norm'] == total_norm for _, _, _, x in V)
    dd = c.decider
    rows = [{'name': 'Jev', 'key': 'jev', 'style': None, 'cost': float(c.jev_cost), 'lat': c.jev_lat, 'p90': c.jev_p90,
             'acc_full': jev_full, 'acc_norm': jev_norm, 'color': C.TEAL, 'flag': False, 'note': ''},
            {'name': DECIDER_NAME, 'key': 'decider', 'style': 'native', 'label_name': 'Decider 2B', 'cost': float(dd.cost),
             'lat': dd.lat, 'p90': dd.p90, 'acc_full': dd.correct, 'acc_norm': dd.correct_norm, 'color': DECIDER_COLOR,
             'flag': False, 'note': f'{dd.instance["type"]} ${dd.rate}/h × {dd.wall}s 机时折算，串行'}]
    for k, s, run, x in V:
        rows.append({'name': vname(run, s), 'key': k, 'style': s, 'label_name': run.label, 'cost': float(x['cost']),
                     'lat': x['lat'], 'p90': x['p90'], 'acc_full': x['correct'], 'acc_norm': x['correct_norm'],
                     'color': MODEL_COLOR[k],
                     'flag': bool(x['filtered']),
                     'note': f'{len(x["filtered"])} 个请求被内容过滤，按答错计' if x['filtered'] else ''})
    model_color = {'jev': C.TEAL, 'decider': DECIDER_COLOR, 'opus': C.RED, 'haiku': C.VIOLET, 'gpt6luna': C.BLUE}

    def points(field, total):
        pts = []
        for r in rows:
            p = {'name': r['name'], 'cost': r['cost'], 'acc': r[field], 'total': total, 'lat': r['lat'],
                 'color': model_color[r['key']], 'filled': True, 'group': r['key'], 'note': r['note']}
            if r['key'] == 'jev':
                p['label'] = 'Jev'
            else:
                p['label'] = r['label_name'] + (' ⚠' if r['flag'] else '')
            pts.append(p)
        return pts

    def y_range(field, total):
        low = min(r[field] for r in rows)
        return (max(0, low - 4), total + 1)
    sc_full = C.tradeoff_scatter(points('acc_full', total_full), f'答对的判断数（共 {total_full}）',
                                 y_range('acc_full', total_full), title=f'全部 {total_full} 个判断（含误用对照组）')
    sc_norm = C.tradeoff_scatter(points('acc_norm', total_norm), f'答对的判断数（共 {total_norm}）',
                                 y_range('acc_norm', total_norm), title=f'不含网格误用对照组的 {total_norm} 个判断')
    strip_rows = sorted(rows, key=lambda r: r['cost'])
    strip = C.metric_strip(strip_rows, total_full, total_norm)
    per10k = ' · '.join(f'{r["name"]} ${r["cost"] / c.n_judg * 10_000:.2f}' for r in strip_rows)
    llm_rows = [r for r in rows if r['key'] in c.runs]
    cheapest_llm = min(llm_rows, key=lambda r: r['cost'])
    best_norm = max(llm_rows, key=lambda r: (r['acc_norm'], -r['cost']))
    fastest_llm = min(llm_rows, key=lambda r: r['lat'])
    below_jev = [r for r in rows if r['key'] != 'jev' and r['acc_norm'] < jev_norm and r['cost'] > float(c.jev_cost)]
    below_note = (f'不含网格误用对照组时，{e("、".join(r["name"] for r in below_jev))} 的准确率低于 Jev，费用却更高。'
                  if below_jev else '')
    n_ctrl = total_full - total_norm
    ctrl = {r['name']: r['acc_full'] - r['acc_norm'] for r in rows}
    worst = min(ctrl, key=ctrl.get)
    ctrl_scores = '，'.join(f'{r["name"]} {ctrl[r["name"]]}/{n_ctrl}' for r in sorted(rows, key=lambda r: r['cost']))
    basis_note = f'''<div class="callout note small" style="margin-top:12px"><b>两个准确率口径是怎么来的。</b>
  全部 {total_full} 个判断里，{sum(len(it['request']['questions']) for cid, it in c.items.items() if it['grade']['kind'] == 'expected' and ':turn' not in cid)} 个来自 16 个静态场景请求，
  另外 {sum(1 for cid in c.items if ':turn' in cid)} 个是闭环场景的回合判断，包括 NPC、网格变体 A、网格变体 B 和浏览器 UI。
  <b>网格变体 A</b>的 {n_ctrl} 个回合是刻意设计的<b>误用对照组</b>。Jev 技能文档要求路线由规划器给出、Jev 只选下一步，
  变体 A 却只给地图，让 Jev 独自规划。把这 {n_ctrl} 个回合去掉，就得到“不含网格误用对照组的 {total_norm} 个判断”，
  每个方案去掉的都是这同一批题，网格变体 B（规划器给路线）仍然保留。<br>
  各方案在这 {n_ctrl} 个对照组回合上答对的数量：{e(ctrl_scores)}。答对最少的是 {e(worst)}。Jev 答对 {ctrl["Jev"]} 个，
  所以它在两个口径下的准确率差得比较多，分别是 {jev_full / total_full:.1%} 和 {jev_norm / total_norm:.1%}。<br>
  变体 A 是事先就设计好的对照组，但单列 {total_norm} 题口径这种统计方式，是看到 Jev 在变体 A 上失败之后才加上的，不属于事先定好的评测方案。
  散点图右侧的副坐标，是把同一个答对数换算成占该口径总题数的百分比。</div>'''
    legend = ('<div class="small muted" style="display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:6px">'
              + ''.join(f'<span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{col};margin-right:5px"></span>{e(name)}</span>'
                        for name, col in [('Jev', C.TEAL), (DECIDER_NAME, DECIDER_COLOR), ('Claude Opus 5.5', C.RED), ('Claude Haiku 5.5', C.VIOLET), ('GPT-6 Luna', C.BLUE)])
              + '<span>圆越大 = 中位耗时越长</span>'
              '<span>绿色虚线 = 帕累托前沿（同等或更低成本下准确率最高）</span><span>⚠ = 有请求被内容过滤，按答错计</span></div>')
    return f'''<section><div class="card"><div class="section-head"><div><div class="eyebrow">模型对比</div>
<h2>Jev、自托管决策模型与三个 LLM：成本、耗时、准确率</h2></div><a href="cost.html" class="small">查看完整成本对比 →</a></div>
<p class="small muted">同样 {len(c.items)} 个请求（{total_full} 个判断）分别交给 Jev、Bedrock 上的三个模型，以及同 VPC 自托管的 Strands Decider 2B。
LLM 成本按给定单价折算，自托管模型按 {e(dd.instance["type"])} 的按需价 ${dd.rate}/小时乘以本批次的串行用时折算，不含空闲时段。
耗时是客户端实测的单次往返时间，准确率按同一套标准答案逐题打分。鼠标悬停在图形上可以看到精确数值。</p>
<div class="grid g2">{sc_full}{sc_norm}</div>{legend}{basis_note}
<div style="height:18px"></div><div style="overflow-x:auto">{strip}</div>
<div class="grid g2" style="margin-top:14px">
  <div class="callout ok small"><b>最便宜：</b>Jev，{usd_s(c.jev_cost)}。LLM 里最便宜的是 {e(cheapest_llm["name"])}，{usd_s(cheapest_llm["cost"])}，
    为 Jev 的 {cheapest_llm["cost"] / float(c.jev_cost):.1f} 倍。自托管 Decider 按机时折算是 {usd_s(dd.cost)}，为 Jev 的 {dd.cost / c.jev_cost:.1f} 倍。</div>
  <div class="callout ok small"><b>最快：</b>{"Decider 2B" if dd.lat < c.jev_lat else "Jev"}，中位 {min(dd.lat, c.jev_lat):.2f} 秒，
    其次是 {"Jev" if dd.lat < c.jev_lat else "Decider 2B"} 的 {max(dd.lat, c.jev_lat):.2f} 秒。LLM 中 {e(fastest_llm["name"])} 最快，{fastest_llm["lat"]:.2f} 秒。</div>
  <div class="callout note small"><b>最准（不含网格误用对照组）：</b>{e(best_norm["name"])}，{best_norm["acc_norm"]}/{total_norm}（{best_norm["acc_norm"] / total_norm:.1%}），
    Jev 为 {jev_norm}/{total_norm}（{jev_norm / total_norm:.1%}）。按全部 {total_full} 题计，Jev 是 {jev_full}/{total_full}（{jev_full / total_full:.1%}），差距主要来自让它独自规划的误用对照组。{below_note}</div>
  <div class="callout warn small"><b>自托管 Decider 2B：</b>答对 {dd.correct}/{total_full}（{dd.correct / total_full:.1%}），不含对照组时为 {dd.correct_norm}/{total_norm}（{dd.correct_norm / total_norm:.1%}）。
    choice / noul 题答错的判断里，有 {dd.review["wrong_rev"]} 个已被它自己送去复核，直接选定却答错的有 {len(dd.review["wrong_sel"])} 个。服务端在并发时不安全，本组是串行测得的结果。</div>
</div>
<p class="small muted" style="margin-top:8px">按每 1 万个判断线性外推的费用（估算，自托管按本批次机时折算，不含空闲时段）：{e(per10k)}。</p>
</div></section>'''


def usd_s(v):
    return f'${float(v):.4f}'



def crop_screenshot(src, dst, pad=28):
    """Copy a raw browser screenshot, trimmed to its non-white content box (display only)."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        shutil.copy(src, dst)
        return
    im = Image.open(src).convert('RGB')
    box = ImageChops.difference(im, Image.new('RGB', im.size, (255, 255, 255))).getbbox()
    if box:
        l, t, r, b = box
        im = im.crop((max(0, l - pad), max(0, t - pad), min(im.width, r + pad), min(im.height, b + pad)))
    im.save(dst)


def main():
    d = Data()
    (OUT / 'scenarios').mkdir(parents=True, exist_ok=True)
    (OUT / 'assets' / 'img').mkdir(parents=True, exist_ok=True)
    shutil.copy(V2 / 'report_assets' / 'style.css', OUT / 'assets' / 'style.css')
    for png in sorted((V2 / 'artifacts').glob('*.png')):
        crop_screenshot(png, OUT / 'assets' / 'img' / png.name)
    for s in SCENARIOS:
        (OUT / 'scenarios' / f'{s["slug"]}.html').write_text(scenario_page(d, s), encoding='utf-8')
    from report_cost import cost_body
    (OUT / 'cost.html').write_text(page('成本对比', cost_body(d, sec, footer(d)), 'cost'), encoding='utf-8')
    (OUT / 'index.html').write_text(index_page(d), encoding='utf-8')
    print(f'wrote {OUT}/index.html, cost.html and {len(SCENARIOS)} scenario pages')


if __name__ == '__main__':
    main()
