"""Model-neutral selection guidance; ranking numbers come only from recorded judgments."""
from html import escape

from report_scenario_models import DECISION_KEYS, DECISION_NAMES, group_anchor

CONSIDER_ABOVE_PERCENT = 90

USE_WHEN = {
    "agent-checkpoint": "反复失败、计划偏航、准备报告完成时，核对下一步与完成证据。",
    "code-review": "围绕给定 diff 和测试证据分类、分级；保留测试与人工评审。",
    "context": "为已分块的上下文给出保留建议；先保存原文，压缩由宿主完成。",
    "documents": "在给定条款中选编号、核对主张；原文由调用方复制。",
    "find-code": "先检索候选文件，再按功能语义选择；选后仍核验符号。",
    "route": "按候选的能力、权限和数据去向选择执行方。",
    "triage": "对工单批量分类、退款识别和紧急度评分；低置信度转复核。",
    "ui": "从当前文本快照选择控件；完成状态和敏感操作由宿主核验。",
    "redteam": "对已有对话分类并核对证据完整性；精确匹配规则仍由代码执行。",
    "npc": "规则与合法动作已知时，选择当前回合的局部动作。",
    "grid_planned": "规划器已给路线时，只判断下一格对应的动作。",
    "grid": "误用对照：仅给地图要求自主规划。此排名不作为规划能力推荐。",
}


def e(value):
    return escape(str(value), quote=True)


def eligible_decision_models(results, control=False):
    """Use exact counts: LLM scores and rounded display percentages cannot qualify a model."""
    if control:
        return []
    return [
        key for key in DECISION_KEYS if key in results and results[key]["total"] > 0
        and results[key]["correct"] * 100 > results[key]["total"] * CONSIDER_ABOVE_PERCENT
    ]


def selection_rows(comparison, scenarios):
    rows = []
    for scenario in scenarios:
        if scenario["slug"] == "simulation":
            groups = [("npc", "NPC 规则决策"), ("grid_planned", "按规划路线行动"), ("grid", "自主规划 · 误用对照")]
            for key, title in groups:
                ids = [cid for cid in comparison.ids_for(scenario["skill"]) if cid.startswith(key + ":")]
                rows.append({"key": key, "title": title, "slug": scenario["slug"], "anchor": group_anchor(key), "ids": ids,
                             "when": USE_WHEN[key], "control": key == "grid", "ranking": comparison.ranking(ids)})
        else:
            ids = comparison.ids_for(scenario["skill"])
            rows.append({"key": scenario["slug"], "title": scenario["title"], "slug": scenario["slug"],
                         "anchor": "model-comparison", "ids": ids,
                         "when": USE_WHEN[scenario["slug"]], "control": False, "ranking": comparison.ranking(ids)})
    for row in rows:
        row["results"] = comparison.summary(row["ids"])
        row["eligible_models"] = eligible_decision_models(row["results"], row["control"])
    return rows


def selection_section(comparison, scenarios):
    rows = []
    decision_keys = [key for key in DECISION_KEYS if key in comparison.models]
    llm_keys = [key for key in comparison.models if key not in DECISION_KEYS]
    for row in selection_rows(comparison, scenarios):
        by_key = {r["key"]: r for r in row["ranking"]}
        scores = []
        for key in decision_keys + llm_keys:
            result = row["results"][key]
            rank = ""
            if key in by_key:
                place = by_key[key]["rank"]
                tied = sum(r["rank"] == place for r in row["ranking"]) > 1
                rank = f'<br><span class="small muted">{"并列" if tied else ""}第 {place}</span>'
            unanswered = (f'<br><span class="small warn-text">未作答 {result["unanswered"]}</span>'
                          if result["unanswered"] else "")
            scores.append(
                f'<td class="num" data-selection-model="{key}"><b>{result["correct"]}/{result["total"]}</b>'
                f'<br><span class="muted small">{result["correct"]/result["total"]:.1%}</span>{rank}{unanswered}</td>')
        eligible = row["eligible_models"]
        if eligible:
            names = "、".join(DECISION_NAMES[key] for key in eligible)
            recommendation = (f'<span class="badge b-pass">可考虑使用</span>'
                              f'<div class="small selection-qualified">{e(names)}</div>')
        else:
            recommendation = '<span class="muted small">误用对照，不作采用推荐</span>' if row["control"] else (
                '<span class="muted small">本批未超过 90%</span>')
        rows.append(
            f'<tr data-selection-case="{row["key"]}" class="{"selection-control" if row["control"] else ""}">'
            f'<th scope="row"><a href="scenarios/{row["slug"]}.html#{e(row["anchor"])}">{e(row["title"])}</a>'
            f'<div class="small muted selection-use">{e(row["when"])}</div></th>'
            f'<td class="selection-recommendation" data-eligible-models="{",".join(eligible)}">{recommendation}</td>'
            f'{"".join(scores)}</tr>')
    headers = "".join(f'<th scope="col">{e(comparison.models[key]["label"])}</th>' for key in decision_keys + llm_keys)
    return f'''<section id="model-selection" style="scroll-margin-top:78px">
<div class="section-head"><div><div class="eyebrow">选型</div><h2>什么时候用 Decider 模型</h2></div></div>
<p>下表并列展示三种决策模型和三个 LLM 的同场景结果。
只有具体决策模型在本场景的准确率<b>严格超过 90%</b>，才标注“可考虑使用”，并列出达到门槛的模型。
LLM 的高分不作为决策模型达到门槛的依据；实际选择还需结合错题、复核行为、耗时与成本。</p>
<div class="table-wrap"><table class="selection-table"><thead><tr>
<th scope="col" rowspan="2">应用场景与使用边界</th><th scope="col" rowspan="2">是否考虑使用决策模型</th>
<th scope="colgroup" colspan="{len(decision_keys)}">决策模型 · 正确率 / 排名</th>
<th scope="colgroup" colspan="{len(llm_keys)}">LLM 参照 · 正确率</th></tr>
<tr>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<p class="small muted" style="margin-top:10px">门槛按原始答对数 / 总题数计算，恰好 90% 不标注；未作答计入分母。
“可考虑使用”仅表示通过本批数据的筛选，仍需业务验证；误用对照不作采用推荐。
决策模型的排名保留在各自分数下方，同分并列，LLM 不参与此排名。表格可横向滚动。
仿真拆成 NPC、按路线行动与自主规划对照，所有行合计仍为 147 个判断；
整体排名另以不含 30 个误用对照判断的 117 题为主。用例规模较小，排名仅代表本批结果。</p>
<div class="callout note small"><b>交给其他组件的工作：</b>长文生成交给生成模型，精确计算与已知符号查找交给代码或检索工具，
全局路线交给规划器。模型输出的标签和概率不代替权限检查、实际执行与结果核验。</div>
</section>'''


def confidence_section(comparison):
    rows = []
    for key in DECISION_KEYS:
        if key not in comparison.models:
            continue
        high, wrong_selected, reviewed = [], 0, 0
        for call in comparison.models[key]["calls"].values():
            for qid, decision in call["decisions"].items():
                if decision["status"] == "scored":
                    continue
                p = decision["probability"]
                if isinstance(decision["value"], bool):
                    p = max(p, 1 - p)
                correct = call["checks"][qid]["correct"]
                if p >= .95:
                    high.append(correct)
                wrong_selected += not correct and decision["status"] == "selected"
                reviewed += decision["status"] == "needs_review"
        rows.append(f'<tr><th scope="row">{e(DECISION_NAMES[key])}</th><td class="num">{len(high)}</td>'
                    f'<td class="num">{sum(high)}/{len(high)}</td><td class="num">{len(high)-sum(high)}</td>'
                    f'<td class="num">{wrong_selected}</td><td class="num">{reviewed}</td></tr>')
    return f'''<section><div class="section-head"><div><div class="eyebrow">可靠性</div><h2>概率与复核：三种决策模型分别核验</h2></div></div>
<div class="table-wrap"><table><thead><tr><th>决策模型</th><th>最高概率 ≥0.95</th><th>其中答对</th><th>其中答错</th>
<th>答错且直接选定</th><th>需复核</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<p class="small muted" style="margin-top:10px">覆盖本批所有 choice / noul 判断，包含误用对照；noul 使用 max(p, 1-p)，score 不计入。
“直接选定 / 需复核”来自记录中的调用方判定。高概率的含义依赖模型与数据，不能把某个模型的校准结果推广到其他模型。</p></section>'''
