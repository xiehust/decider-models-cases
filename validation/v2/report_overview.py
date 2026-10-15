"""Overview written around the decision-model category, with LLM reference baselines."""
from html import escape

import report_charts as charts
from report_selection import confidence_section, selection_section
from report_scenario_models import DECISION_KEYS, DECISION_NAMES


def e(value):
    return escape(str(value), quote=True)


def overview_body(d, comparison, scenarios, cost_teaser, footer):
    c = comparison.cost
    summary = comparison.summary(list(comparison.items))
    keys = [key for key in DECISION_KEYS if key in comparison.models]
    total = summary["jev"]["total"]
    normal_total = summary["jev"]["normal_total"]
    kpis = [
        (str(len(keys)), "种决策模型", "Jev · Strands Decider 2B · Laya Multilingual"),
        (str(len(c.runs)), "个 LLM 参照", "Opus 5.5 · Haiku 5.5 · GPT-6 Luna"),
        (str(len(scenarios)), "个应用场景", "检查点、评审、文档、路由、仿真、UI 等"),
        (str(len(comparison.items)), "个共用请求", "每个模型使用同一批 state / questions"),
        (str(total), "个判断", "包含 30 个自主规划误用对照判断"),
        (str(normal_total), "个常规判断", "主要选型口径，去掉同一批误用对照题"),
    ]
    kpi_html = "".join(
        f'<div class="card kpi"><div class="v">{v}</div><div class="l">{label}</div>'
        f'<div class="s">{note}</div></div>' for v, label, note in kpis)
    cards = []
    for scenario in scenarios:
        ids = [cid for cid in comparison.ids_for(scenario["skill"]) if not cid.startswith("grid:")]
        scores = comparison.summary(ids)
        short_names = {"jev": "Jev", "decider": "Strands", "laya": "Laya"}
        score_line = " · ".join(f'{short_names[key]} {scores[key]["correct"]}/{scores[key]["total"]}' for key in keys)
        control_note = " · 另列误用对照" if scenario["slug"] == "simulation" else ""
        cards.append(
            f'<a class="card scn" href="scenarios/{scenario["slug"]}.html">'
            f'<div class="top"><div class="icon">{scenario["icon"]}</div><span class="badge b-info">三种决策模型</span></div>'
            f'<h3>{e(scenario["title"])}</h3><p>{e(scenario["one_liner"])}</p>'
            f'<p class="scenario-card-scores">{e(score_line)}</p>'
            f'<div class="foot"><span>{scores["jev"]["total"]} 题{control_note}</span><span>查看逐题结果 →</span></div></a>')

    ranked = comparison.ranking([cid for cid in comparison.items if not cid.startswith("grid:")])
    quality = "；".join(f'{r["label"]} {r["correct"]}/{r["total"]}（{r["correct"]/r["total"]:.1%}）' for r in ranked)
    cheapest = min(keys, key=lambda key: summary[key]["cost"])
    best_llm = max(c.runs.values(), key=lambda r: r.t["terse"]["correct_norm"])
    best = best_llm.t["terse"]
    findings = f'''<div class="grid g2">
<div class="callout note"><b>同属决策模型，正确率仍有明显差异。</b><br>
<span class="small">按 {normal_total} 个常规判断汇总：{e(quality)}。分场景排名见选型表，不能仅按参数量判断效果。</span></div>
<div class="callout note"><b>整体排名不能替代场景排名。</b><br>
<span class="small">条款定位与代码定位中有并列结果；自主规划对照组的排序又与常规判断不同。
仿真拆成 NPC、按路线行动和自主规划分别报告，避免用一个总分概括不同能力。</span></div>
<div class="callout warn"><b>费用和时延需要连同质量一起看。</b><br>
<span class="small">本批费用最低的决策模型是 {e(DECISION_NAMES[cheapest])}，约 ${summary[cheapest]["cost"]:.6f}。
自托管费用只按测试机时折算，网络、实例规格和空闲成本均影响实际选型；不能把本机 HTTP 时延视为统一网络下的速度排名。</span></div>
<div class="callout note"><b>LLM 用来衡量质量差距。</b><br>
<span class="small">三个 LLM 参照中，{e(best_llm.label)} 的常规判断正确数最高，为 {best["correct_norm"]}/{normal_total}。
它们只输出答案，不参加决策模型的场景排名；过滤、费用与推理 token 仍在完整对比中披露。</span></div>
</div>'''
    workflow = charts.flow([
        ("1 · 框定", "目标·权限\n预算", "host"), ("2 · 观察", "证据·状态\n候选动作", "host"),
        ("3 · 决策模型", "choice / noul\n/ score", "decision"), ("4 · 解读", "概率·复核\n门槛", "check"),
        ("5 · 执行验证", "宿主执行一步\n核验真实结果", "stop"),
    ])
    return f'''<div class="hero"><div class="wrap">
<div class="eyebrow">Decider Models · Evaluation Report</div>
<h1>Decider 决策模型评测报告</h1>
<p class="lead">Agent 要做选择、判是非、给评分时，到底该调用大模型，还是专门的决策模型？
这份报告用 {len(scenarios)} 个贴近真实业务的合成应用场景、{len(comparison.items)} 个共用请求、{total} 个判断，
把 Jev、Strands Decider 2B、Laya Multilingual 三款决策模型，与 Claude Opus 5.5、Claude Haiku 5.5、GPT-6 Luna
放在相同的状态、问题和候选项下对比，覆盖准确率、复核行为、时延与成本四个维度。
所有结论都附逐题输出和测量条件，并按具体场景给出“是否可用、用哪款”的选型建议。</p>
<div class="meta"><span>运行日期 <b>2026-10-12—15</b></span><span>测试集 <b>合成场景 · 固定标准答案</b></span>
<span>接口 <b>原生决策 API / Bedrock</b></span></div>
<p class="small" style="margin-top:14px"><a href="#model-selection">什么时候用 Decider 模型 · 分场景排名 →</a></p>
</div></div><main class="wrap">
<section style="margin-top:0"><div class="grid g3">{kpi_html}</div></section>
{cost_teaser(d)}
{selection_section(comparison, scenarios)}
<section><div class="section-head"><div><div class="eyebrow">场景</div><h2>{len(scenarios)} 个应用场景的评测明细</h2></div></div>
<p class="small muted">卡片列出三种决策模型的答对数。进入子页面可对照六个模型的标准答案、实际输出、复核状态和费用；
仿真卡片使用不含误用对照的 26 题，完整 56 题在页内另列。</p>
<div class="grid g3">{"".join(cards)}</div></section>
<section><div class="section-head"><div><div class="eyebrow">发现</div><h2>评测结果对选型的启示</h2></div></div>{findings}</section>
{confidence_section(comparison)}
<section><div class="section-head"><div><div class="eyebrow">基础</div><h2>Decider 模型的三种输出</h2></div></div>
<div class="grid g3">
<div class="card prim"><span class="tag">choice</span><h3 style="margin-top:10px">从候选中选一个</h3>
<p class="small">输出候选标签及其概率，可用于类别、下一步动作、文件或条款 ID。需要设置 none、unknown 或 ask_user 等回退选项。</p></div>
<div class="card prim noul"><span class="tag">noul</span><h3 style="margin-top:10px">判断是否成立</h3>
<p class="small">输出 P(true)，用于主张、约束或同一性判断。读取“否”的置信程度时，需要同时考虑 1-p。</p></div>
<div class="card prim score"><span class="tag">score</span><h3 style="margin-top:10px">按等级评分</h3>
<p class="small">返回各等级概率及加权分数，可用于严重度、紧急度和证据强度。分数可以是小数，按预定区间验收。</p></div>
</div></section>
<section><div class="card"><div class="eyebrow">集成方式</div><h2>决策模型与调用方的分工</h2>{workflow}
<p class="small muted">这是建议的集成流程。模型负责判断，权限、执行与结果核验由调用方承担。
本报告保留回执中的复核规则：choice 最高概率至少 0.8、相对次高至少高 0.15，出口标签转复核；
noul 按二元确定程度处理。规则合适与否仍需用自己的数据验证。</p></div></section>
<section><div class="card"><div class="eyebrow">方法</div><h2>测试设计、证据范围与局限</h2><ul class="clean small">
<li>比较使用同一批 state / questions、候选及预定标准答案。标准答案不进入模型输入，未按结果修改评分区间。</li>
<li>用例最初按 jev-skill v0.2.0 构建，后作为共享测试集；原始标识与回执保留。
运行器的技能描述不是三种模型都具有对应能力的证明。</li>
<li>NPC、网格和 UI 的真实闭环由 Jev 驱动采集，其他模型重放相同状态判断。
只有 Jev 有该闭环的执行与 DOM 证据；其他模型的逐步正确率不等于任务完成率。</li>
<li>主要选型口径为 {normal_total} 题，完整口径为 {total} 题。网格变体 B 和排除误用对照的统计口径是在看到变体 A 失败后追加的，属于事后分析。</li>
<li>LLM 单价沿用给定假设；自托管按实际地区和机型的按需机时折算，不含部署、空闲、EBS 等费用。
Laya 使用东京本机 HTTP，其余记录的网络条件不同。</li>
<li>每个输入 / 配置只测一轮，样本量小、用例来自同一作者。没有测试不同随机种子、所有检查点或微调后的能力；
高置信度与场景排名都只能解释为本批证据。</li>
</ul></div></section>
<section><div class="card"><div class="eyebrow">复现</div><h3>从已有回执重建报告</h3>
<pre><code>python3 validation/v2/build_report.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s validation</code></pre>
<p class="small muted">以上检查不调用模型。各模型的在线运行方法、版本、实例和原始数据路径见仓库 README 与部署说明；
预热、UI 修正、失败尝试和旧基线单独保存。</p></div></section>
{footer(d)}</main>'''
