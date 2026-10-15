"""Scenario-level comparisons from the same reconciled receipts as the cost page."""
from copy import deepcopy
from decimal import Decimal
from html import escape
import json
from pathlib import Path
import statistics

from llm_baseline import grade
from report_cost import CostData

V2 = Path(__file__).resolve().parent
LOOP_TITLES = {
    "npc": "NPC 规则决策",
    "grid": "自主规划 · 误用对照（网格变体 A）",
    "grid_planned": "按规划路线行动（网格变体 B）",
    "ui_settings": "浏览器设置页",
    "ui_checkout": "浏览器结算页",
}
DECISION_KEYS = ("jev", "decider", "laya")
DECISION_NAMES = {"jev": "Jev", "decider": "Strands Decider 2B", "laya": "Laya Multilingual"}


def e(value):
    return escape(str(value), quote=True)


def question_ids(item):
    g = item["grade"]
    return [g["question"]] if g["kind"] == "one_of" else list(g["expected"])


def group_anchor(key):
    """Shared by deep links and their visible, non-collapsible destination sections."""
    return "compare-" + key.replace(":", "-")


def allocated_costs(rows, total):
    """Attribute the recorded batch cost by request time; this is not new billing."""
    weights = {r["id"]: Decimal(str(r["wall_seconds"])) for r in rows}
    assert len(weights) == len(rows) and all(w > 0 for w in weights.values())
    weight_sum = sum(weights.values(), Decimal(0))
    amounts = {cid: total * weight / weight_sum for cid, weight in weights.items()}
    # Absorb Decimal rounding in the final item, so scenario totals reconcile.
    amounts[next(reversed(amounts))] += total - sum(amounts.values(), Decimal(0))
    return amounts


class ScenarioModels:
    def __init__(self, d):
        self.cost = c = CostData(d)
        self.items = deepcopy(c.items)
        fixes = json.loads((V2 / "llm-requests-ui-fix-20261013.json").read_text())
        for item in fixes:
            self.items[item["id"]] = item
        self.models = {}

        jev = {}
        for cid, row in c.jev.items():
            rep = row["report"]
            jev[cid] = {
                "answers": {q: a["value"] for q, a in rep["decisions"].items()},
                "decisions": rep["decisions"],
                "wall_seconds": rep["elapsed_seconds"],
                "cost": Decimal(str(rep["response"]["usage"]["cost"])),
                "stop_reason": "end_turn", "parse_error": None,
            }
        self.models["jev"] = {"label": "Jev", "short": "Jev", "calls": jev, "native": True}
        native = [("decider", "Strands Decider 2B", "Decider 2B", c.decider)]
        if c.laya:
            native.append(("laya", "Laya Multilingual", "Laya", c.laya))
        for key, label, short, run in native:
            amounts = allocated_costs(run.llm, run.cost)
            self.models[key] = {
                "label": label, "short": short, "native": True,
                "calls": {r["id"]: {**r, "cost": amounts[r["id"]]} for r in run.llm},
            }
        for key, run in c.runs.items():
            self.models[key] = {
                "label": run.label, "short": run.label, "native": False,
                "calls": {r["id"]: {**r, "cost": Decimal(r["cost_usd"])} for r in run.llm},
            }
        for key, model in self.models.items():
            assert set(model["calls"]) == set(self.items)
            for cid, call in model["calls"].items():
                answers = call["answers"] or {}
                judged = grade(self.items[cid], answers)
                if key != "jev":
                    # Filtered/parse-failed responses have no answers and no original grades.
                    assert call["graded"] == (judged if answers else {})
                call["checks"] = {
                    q: {"answered": q in answers, "correct": q in answers and judged[q]}
                    for q in question_ids(self.items[cid])
                }

    def ids_for(self, skill):
        return [cid for cid, item in self.items.items() if item["skill"] == skill]

    def groups(self, skill, d):
        groups = {}
        for cid in self.ids_for(skill):
            key = cid.split(":turn")[0] if ":turn" in cid else cid
            title = LOOP_TITLES.get(key, d.cases.get(cid, {}).get("title", cid))
            groups.setdefault(key, {"title": title, "ids": []})["ids"].append(cid)
        return groups

    def summary(self, ids):
        total = sum(len(question_ids(self.items[cid])) for cid in ids)
        normal_ids = [cid for cid in ids if not cid.startswith("grid:")]
        normal_total = sum(len(question_ids(self.items[cid])) for cid in normal_ids)
        result = {}
        for key, model in self.models.items():
            calls = [model["calls"][cid] for cid in ids]
            checks = [check for call in calls for check in call["checks"].values()]
            result[key] = {
                "total": total,
                "correct": sum(check["correct"] for check in checks),
                "unanswered": sum(not check["answered"] for check in checks),
                "review": sum(
                    a["status"] == "needs_review"
                    for call in calls for a in call.get("decisions", {}).values()
                ) if model["native"] else None,
                "normal_total": normal_total,
                "normal_correct": sum(
                    check["correct"] for cid in normal_ids
                    for check in model["calls"][cid]["checks"].values()
                ),
                "latency": statistics.median(call["wall_seconds"] for call in calls),
                "cost": sum((call["cost"] for call in calls), Decimal(0)),
            }
        return result

    def ranking(self, ids):
        """Correct-answer ranking among decision models only; ties share competition rank."""
        summary = self.summary(ids)
        keys = [k for k in DECISION_KEYS if k in self.models]
        return [
            {"key": key, "label": DECISION_NAMES[key], **summary[key],
             "rank": 1 + sum(summary[other]["correct"] > summary[key]["correct"] for other in keys)}
            for key in sorted(keys, key=lambda k: -summary[k]["correct"])
        ]

    def cascade(self, decision_key, llm_key):
        """Receipt-based estimate: escalate a whole request if any decision needs review."""
        assert decision_key in DECISION_KEYS and llm_key not in DECISION_KEYS
        native = self.models[decision_key]["calls"]
        llm = self.models[llm_key]["calls"]
        escalated = [cid for cid, call in native.items()
                     if any(x["status"] == "needs_review" for x in call["decisions"].values())]
        selected = set(escalated)
        calls = [llm[cid] if cid in selected else native[cid] for cid in self.items]
        return {
            "escalated": len(escalated),
            "cost": sum((r["cost"] for r in native.values()), Decimal(0))
                    + sum((llm[cid]["cost"] for cid in escalated), Decimal(0)),
            "correct": sum(x["correct"] for r in calls for x in r["checks"].values()),
            "total": sum(len(r["checks"]) for r in calls),
        }


def ranking_text(ranking):
    parts = []
    for rank in sorted({r["rank"] for r in ranking}):
        names = [r["label"] for r in ranking if r["rank"] == rank]
        parts.append(f'{"并列" if len(names) > 1 else ""}第 {rank}：{"、".join(names)}')
    return "；".join(parts)


def value_text(value):
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def expected_text(item, qid):
    g = item["grade"]
    if g["kind"] == "one_of":
        return " / ".join(value_text(v) for v in g["accept"])
    expected = g["expected"][qid]
    if "range" in expected:
        return f'[{expected["range"][0]}, {expected["range"][1]}]'
    return value_text(expected["value"])


def result_cell(model, cid, qid, question):
    call = model["calls"][cid]
    check = call["checks"][qid]
    if not check["answered"]:
        reason = "内容过滤" if call["stop_reason"] == "content_filtered" else (
            "解析失败" if call.get("parse_error") else "未返回答案")
        return (f'<td class="model-answer answer-missing"><span class="warn-text">— 未作答</span>'
                f'<div class="small">{e(reason)}</div></td>')
    value = call["answers"][qid]
    cls, mark = ("answer-correct", "✓ 符合标准") if check["correct"] else ("answer-wrong", "✗ 未达标")
    status = call.get("decisions", {}).get(qid)
    extra = ""
    if status:
        labels = {"selected": "直接选定", "needs_review": "需复核", "scored": "加权评分"}
        extra = f'<div class="small {"warn-text" if status["status"] == "needs_review" else "muted"}">{labels[status["status"]]}</div>'
        p = status.get("probability")
        if p is not None:
            label = "P(true)" if question["type"] == "noul" else "所选概率"
            extra += f'<div class="small muted">{label} {p:.4f}</div>'
    # UI ref labels are otherwise unreadable; expose the actual control description.
    if cid.startswith("ui_") and question["type"] == "choice":
        description = question["criteria"].get(value, "") if isinstance(value, str) else ""
        extra += f'<div class="small">{e(description)}</div>'
    return (f'<td class="model-answer {cls}"><div class="answer-mark">{mark}</div>'
            f'<code>{e(value_text(value))}</code>{extra}</td>')


def question_rows(comparison, ids, loop):
    rows = []
    for cid in ids:
        item = comparison.items[cid]
        for qid in question_ids(item):
            question = item["request"]["questions"][qid]
            label = f'{cid.split(":")[-1]} · {qid}' if loop else qid
            instruction = "" if loop else f'<div class="small">{e(question["instructions"])}</div>'
            gold = expected_text(item, qid)
            context = (f'<code>{e(label)}</code> <span class="tag">{question["type"]}</span>{instruction}'
                       f'<div class="comparison-gold">标准：<code>{e(gold)}</code></div>')
            cells = "".join(result_cell(model, cid, qid, question) for model in comparison.models.values())
            rows.append(f'<tr data-request-id="{e(cid)}" data-question-id="{e(qid)}">'
                        f'<th scope="row" class="comparison-question">{context}</th>{cells}</tr>')
    return "".join(rows)


def scenario_comparison(comparison, d, scenario):
    skill = scenario["skill"]
    ids = comparison.ids_for(skill)
    summary = comparison.summary(ids)
    total = summary["jev"]["total"]
    control = total != summary["jev"]["normal_total"]
    rank_ids = [cid for cid in ids if not cid.startswith("grid:")]
    ranks = comparison.ranking(rank_ids)
    rank_basis = "不含网格误用对照组的 26 题" if control else f"本场景 {total} 题"
    headers = "".join(f'<th scope="col" title="{e(m["label"])}">{e(m["short"])}</th>'
                      for m in comparison.models.values())
    table_rows = []
    for key, model in comparison.models.items():
        row = summary[key]
        normal = (f'<td class="num">{row["normal_correct"]}/{row["normal_total"]}'
                  f'<br><span class="muted small">{row["normal_correct"]/row["normal_total"]:.1%}</span></td>') if control else ""
        review = "—" if row["review"] is None else str(row["review"])
        latency_note = '<br><span class="small muted">东京本机 HTTP</span>' if key == "laya" else ""
        cost_note = "机时分摊" if key in ("decider", "laya") else ("API 回报" if key == "jev" else "给定单价")
        table_rows.append(
            f'<tr data-model="{key}"><th scope="row">{e(model["label"])}'
            f'<div class="small muted">{"决策模型" if key in DECISION_KEYS else "LLM 参照"}</div></th>'
            f'<td class="num"><b>{row["correct"]}/{total}</b><br><span class="muted small">{row["correct"]/total:.1%}</span></td>'
            f'{normal}<td class="num">{row["unanswered"]}</td><td class="num">{review}</td>'
            f'<td class="num">{row["latency"]:.3f}s{latency_note}</td>'
            f'<td class="num">${row["cost"]:.6f}<br><span class="muted small">{cost_note}</span></td></tr>')
    summary_table = (
        '<div class="table-wrap"><table class="scenario-model-summary"><thead><tr>'
        f'<th>模型</th><th>{"全部题目" if control else "答对 / 总题数"}</th>'
        + ('<th>不含误用对照组</th>' if control else '')
        + '<th>未作答</th><th>需复核</th><th>中位耗时</th><th>本场景费用</th></tr></thead>'
        f'<tbody>{"".join(table_rows)}</tbody></table></div>')

    groups = comparison.groups(skill, d)
    group_table = ""
    if len(groups) > 1:
        rows = []
        for key, group in groups.items():
            counts = comparison.summary(group["ids"])
            rows.append(f'<tr><th scope="row"><a href="#{e(group_anchor(key))}">{e(group["title"])}</a></th>' + "".join(
                f'<td class="num">{counts[key]["correct"]}/{counts[key]["total"]}</td>' for key in comparison.models) + '</tr>')
        group_table = ('<h3 style="margin-top:24px">各用例 / 子场景答对数</h3><div class="table-wrap"><table class="model-group-summary">'
                       f'<thead><tr><th>用例 / 子场景</th>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')

    details = []
    for index, (key, group) in enumerate(groups.items()):
        n = sum(len(question_ids(comparison.items[cid])) for cid in group["ids"])
        loop = key in LOOP_TITLES
        group_id = group_anchor(key)
        group_ranks = comparison.ranking(group["ids"])
        group_scores = "；".join(f'{r["label"]} {r["correct"]}/{r["total"]}' for r in group_ranks)
        control_note = ('<p class="callout note small">这是自主规划的误用对照，仅比较历史状态上的单步判断，'
                        '不代表各模型独立完成规划的成功率。</p>') if key == "grid" else ""
        q_intro = ""
        if loop:
            first = comparison.items[group["ids"][0]]["request"]["questions"]
            q_intro = '<p class="small muted">回合问题：' + '；'.join(
                f'<code>{e(q)}</code> {e(spec["instructions"])}' for q, spec in first.items()) + '。</p>'
        details.append(
            f'<section class="model-case-group" id="{e(group_id)}" data-group-key="{e(key)}">'
            f'<h3>{e(group["title"])}</h3>'
            f'<p class="small group-score-summary">{len(group["ids"])} 个请求 / {n} 个判断 · {e(group_scores)}</p>'
            f'<p class="small muted group-ranking">本组排名：{e(ranking_text(group_ranks))}。</p>{control_note}'
            f'<details class="model-case-details"{" open" if index == 0 else ""}>'
            f'<summary><b>逐题返回值与标准答案</b> · {n} 个判断'
            f'<span class="small muted"> · 点击展开 / 收起</span></summary>{q_intro}'
            '<div class="table-wrap"><table class="model-answer-matrix"><thead><tr>'
            f'<th scope="col">问题与标准答案</th>{headers}</tr></thead><tbody>'
            f'{question_rows(comparison, group["ids"], loop)}</tbody></table></div></details></section>')

    caveats = ""
    if control:
        caveats += ('<p class="callout note small">本页包含 NPC 6 题、网格误用对照组 30 题、规划器给路线的网格 20 题。'
                    '汇总同时列出全部 56 题与不含误用对照组的 26 题；各模型使用同一套预定可接受动作集合。</p>')
    if skill in ("jev-simulation", "jev-ui"):
        caveats += ('<p class="callout note small">其他模型判断的是 Jev 历史轨迹中的同一批状态。'
                    '这里衡量逐步答案是否符合标准，没有运行由其他模型动作驱动的新闭环，因此不是它们的任务完成率。</p>')
    if skill == "jev-ui":
        caveats += ('<p class="small muted">设置页 turn1 / turn2 使用修正后的输入：三个 LLM 与 Decider 取已保存的重跑结果，'
                    'Laya 直接使用修正版。Jev 的原始真实请求不受回放缺陷影响。</p>')

    return f'''<section id="model-comparison" class="scenario-model-comparison">
<div class="section-head"><div><div class="eyebrow">同题评测</div><h2>本场景的模型对比</h2></div>
<a class="small" href="../cost.html">完整对比与计价说明 →</a></div>
<p>本场景 {len(ids)} 个请求、{total} 个判断，对比三种 Decider 决策模型，并以三个 LLM 作为参照。
准确率按返回值或预定评分区间核对；未作答计入总题数，复核状态单列。
原始实验的状态验收与调用方核验保存在本页补充证据中。</p>
<div class="callout note decision-ranking"><b>决策模型排名：</b>{e(ranking_text(ranks))}
<div class="small muted">依据{rank_basis}的答案正确率，同分并列；成本和耗时分别比较，LLM 不参与此排名。</div></div>
{summary_table}{caveats}
<p class="small muted">耗时取已有回执的客户端往返时间；Laya 为东京主机本机 HTTP，网络路径和硬件与其他方案不同。
Jev 费用来自 API 回报，LLM 按原报告给定单价折算。自托管费用按请求耗时占比分摊原批次机时，
各场景合计与总览一致，不含部署和空闲时间。LLM 未提供概率复核状态，表中以“—”表示。</p>
{group_table}
<h3 style="margin-top:24px">逐题返回值与验收</h3>
<p class="small muted">✓ 表示答案符合标准，✗ 表示未达标；“需复核”与对错分别展示。
choice 显示所选标签的概率，noul 显示 P(true)，score 显示返回分数。宽表可横向滚动。</p>
{"".join(details)}
<p class="small muted" style="margin-top:12px">数据复用现有真实回执：Jev 的 live-v2 系列、三个 LLM 与 Decider 的
llm-baseline 系列及 UI 修正回执、Laya 的 llm-baseline-laya-20261015.jsonl。
LLM 使用与成本页一致的 terse（只给答案）结果，未混入 reasoned 记录。</p>
</section>'''
