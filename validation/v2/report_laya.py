"""Laya study and receipt-derived metrics for the existing static report."""
from decimal import Decimal
from html import escape as e
import json
from pathlib import Path
import statistics

from llm_baseline import grade
from laya_benchmark import fingerprint
from run import JEV

V2 = Path(__file__).resolve().parent
LAYA_NAME = "Laya Multilingual"
LAYA_COLOR = "#b45b20"
LAYA_FILE = V2 / "llm-baseline-laya-20261015.jsonl"


def pending_section():
    """Visible research result while AWS has not allocated the requested hardware."""
    base = V2.parent.parent / "deploy/laya-g5"
    metadata = json.loads((base / "laya-multilingual-metadata.json").read_text())
    attempts_path = base / "launch-attempts.jsonl"
    attempts = [json.loads(line) for line in attempts_path.read_text().splitlines()] if attempts_path.exists() else []
    errors = "".join(f"<tr><td>{e(row['at_utc'])}</td><td>{e(row['az'])}</td>"
                     f"<td>{e(row['market'])}</td><td><code>{e(row['error']['Code'])}</code></td>"
                     f"<td><code>{e(row['request_id'])}</code></td></tr>" for row in attempts)
    return f"""<div id="laya-study" class="card" style="scroll-margin-top:88px">
<h3>Laya：源码研究与东京部署进展（2026-10-15）</h3>
<div class="callout warn"><b>尚未取得东京 g5.xlarge，因此没有 Laya 实测成绩。</b>
两个提供该规格的可用区 ap-northeast-1a、ap-northeast-1c 均返回容量不足，按需和 Spot 都已尝试。
下面是源码研究与预定实验方法；Laya 未加入准确率、时延或成本排名，也未用上游数字代替实测。</div>
<p>Laya 是非自回归的类型化决策模型，使用编码器和决策头对 choice、noul、score 问题打分，
输出标签、数值和概率，不生成文本。代码采用 Apache-2.0 许可，本次固定
<a href="https://github.com/NandhaKishorM/laya/tree/432312b36714d8889eba405507b37eda25257d9c">0.4.7 / 432312b</a>。</p>
<div class="table-wrap"><table><thead><tr><th>检查点</th><th>编码器 / 上游标注参数量</th><th>默认上下文</th><th>定位</th></tr></thead>
<tbody><tr><td>laya</td><td>ModernBERT-large / 421M</td><td>512</td><td>英文</td></tr>
<tr><td>laya-multilingual</td><td>mmBERT-base / 322M</td><td>1024，可设为 8192</td><td>多语言，含中文</td></tr>
<tr><td>laya-typed-decisions</td><td>ModernBERT-large / 421M</td><td>1024</td><td>四类合成工作流上的微调版</td></tr></tbody></table></div>
<p>当前用例含大量中文，预定固定多语言版
<a href="https://huggingface.co/convaiinnovations/laya-multilingual/tree/{e(metadata['sha'])}">{e(metadata['sha'])}</a>。
上游的 33 ms 来自自己的 T4 测量，0.766 准确率来自另一个 typed-decisions 微调基准，
均不是本报告的测试结果。README 还明确记录了基础检查点零样本决策偏弱、
score 位置偏差，以及多语言版没有拟合温度、概率过度自信的问题。</p>
<p>源码显示，max_len 限制整个序列，head_max_len 另行限制问题与选项；每个选项还有 48-token 上限。
仅把上下文调到 8192 不足以证明输入完整。已准备逐题 token 审计，检查 state、问题描述和选项是否被截断。</p>
<p>预定复用已修正 UI 输入的 76 个请求、147 个判断及原标准答案；额外列出排除网格误用对照组的 117 题。
3 次独立预热后正式串行运行一次，不重试，不微调，不把标准答案送入模型。
将在东京 GPU 主机本地 HTTP 计时，明确与旧模型客户端网络路径不同。</p>
<p>AWS Pricing API 查询到东京 Linux / Shared / On-Demand 的 g5.xlarge 计算价
<b>$1.459/小时</b>（2026-10-01 生效），持续 24 小时为 $35.016；不含 EBS 与公网 IPv4。
批次成本需等实际调用时长取得后才能计算。</p>
<details><summary>已保存的 EC2 容量失败回执</summary><div class="table-wrap"><table>
<thead><tr><th>UTC</th><th>可用区</th><th>购买方式</th><th>AWS 错误</th><th>Request ID</th></tr></thead>
<tbody>{errors}</tbody></table></div></details>
<p class="small muted">复现脚本、模型配置、价格回执与部署计划在 <code>deploy/laya-g5/</code>；
正式请求在 <code>validation/v2/llm-requests-laya-20261015.json</code>。部署脚本尚未经 GPU 实机验证。</p></div>"""


class LayaRun:
    def __init__(self, items):
        rows = [json.loads(line) for line in LAYA_FILE.read_text().splitlines() if line.strip()]
        self.manifest = rows[0]
        assert self.manifest["smoke"] is False
        requests = json.loads((V2 / self.manifest["requests_file"]).read_text())
        assert fingerprint(requests) == self.manifest["requests_sha256"]
        corrected = {i["id"]: i for i in json.loads((V2 / "llm-requests-ui-fix-20261013.json").read_text())}
        self.items = {i["id"]: i for i in requests}
        assert self.items == {cid: corrected.get(cid, it) for cid, it in items.items()}
        assert self.manifest["concurrency"] == 1 and self.manifest["retries"] == 0
        self.llm = [r for r in rows if r["kind"] == "llm_result"]
        self.raw = {r["id"]: r for r in rows if r["kind"] == "raw_response"}
        assert not [r for r in rows if r["kind"] in ("error", "skipped")]
        assert len(self.llm) == len(self.raw) == len(self.items) == 76
        assert {r["id"] for r in self.llm} == set(self.items)
        for r in self.llm:
            item = self.items[r["id"]]
            raw = self.raw[r["id"]]
            expected_body = {**self.manifest["controls"],
                             "state": item["request"]["state"], "questions": item["request"]["questions"]}
            assert fingerprint(expected_body) == raw["wire_sha256"]
            decisions = JEV.build_report(item["request"], raw["response"])["decisions"]
            assert r["decisions"] == decisions
            assert r["answers"] == {qid: a["value"] for qid, a in decisions.items()}
            assert r["graded"] == grade(item, r["answers"])
            assert r["raw_answers"] == raw["response"]["answers"]
            assert r["wall_seconds"] == raw["wall_seconds"]
            assert r["usage"] == {"inputTokens": raw["response"]["usage"]["input_tokens"],
                                  "outputTokens": raw["response"]["usage"]["output_tokens"]}
        summary = next(r for r in rows if r["kind"] == "summary")
        assert summary["calls"] == 76 and summary["stop_reason"] is None
        health_after = next(r["health"] for r in rows if r["kind"] == "health_after")
        assert health_after["device"] == "cuda" and not health_after["device_is_preference"]
        assert not any(v["count"] for v in health_after["cpu_fallbacks"].values())
        self.instance = self.manifest["instance"]
        self.wall = Decimal(str(next(r["wall_seconds"] for r in rows if r["kind"] == "style_wall")))
        self.rate = Decimal(self.instance["usd_per_hour"]).normalize()
        self.cost = self.rate * self.wall / 3600
        self.lat = statistics.median(r["wall_seconds"] for r in self.llm)
        self.p90 = sorted(r["wall_seconds"] for r in self.llm)[int(.9 * (len(self.llm) - 1))]
        self.correct = sum(v for r in self.llm for v in r["graded"].values())
        self.answered = sum(len(r["graded"]) for r in self.llm)
        assert self.answered == 147
        self.correct_norm = sum(v for r in self.llm if not r["id"].startswith("grid:") for v in r["graded"].values())
        self.inp = sum(r["usage"]["inputTokens"] for r in self.llm)
        self.out = sum(r["usage"]["outputTokens"] for r in self.llm)
        self.wrong = [(r["id"], qid) for r in self.llm for qid, ok in r["graded"].items() if not ok]
        self.truncated = [cid for cid, r in self.raw.items() if r["response"]["usage"].get("truncated")]
        self.review = {"right_sel": 0, "right_rev": 0, "wrong_sel": [], "wrong_rev": 0}
        self.high_conf = []
        self.score_q = []
        for r in self.llm:
            for qid, ok in r["graded"].items():
                decision = r["decisions"][qid]
                if decision["status"] == "scored":
                    self.score_q.append((r["id"], qid, ok))
                    continue
                selected = decision["status"] == "selected"
                if ok:
                    self.review["right_sel" if selected else "right_rev"] += 1
                elif selected:
                    self.review["wrong_sel"].append((r["id"], qid))
                else:
                    self.review["wrong_rev"] += 1
                probability = decision["probability"]
                if isinstance(decision["value"], bool):
                    probability = max(probability, 1 - probability)
                if probability >= .95:
                    self.high_conf.append(ok)


def laya_section(c):
    l = c.laya
    env = l.manifest["deployment"]["environment"]
    audit = json.loads((V2.parent.parent / "deploy/laya-g5/input-audit.json").read_text())
    budget_audit = audit["summary"][str(l.manifest["controls"]["head_max_len"])]
    by_skill = {}
    for r in l.llm:
        group = by_skill.setdefault(r["skill"], [0, 0, 0, 0, 0])
        group[0] += sum(r["graded"].values())
        group[1] += len(r["graded"])
        group[2] += sum(d["status"] == "needs_review" for d in r["decisions"].values())
        jev_answers = {qid: d["value"] for qid, d in c.jev[r["id"]]["report"]["decisions"].items()}
        group[3] += sum(grade(l.items[r["id"]], jev_answers).values())
        group[4] += sum(c.decider.by_id[r["id"]]["graded"].values())
    table = "".join(f"<tr><td>{e(skill)}</td><td>{j}/{total}</td><td>{dec}/{total}</td><td>{ok}/{total}</td><td>{review}</td></tr>"
                    for skill, (ok, total, review, j, dec) in sorted(by_skill.items()))
    wrong = "".join(f"<tr><td><code>{e(cid)}</code></td><td><code>{e(qid)}</code></td>"
                    f"<td>{e(str(l.items[cid]['grade'].get('expected', {}).get(qid, l.items[cid]['grade'].get('accept'))))}</td>"
                    f"<td>{e(str(next(r for r in l.llm if r['id'] == cid)['answers'][qid]))}</td></tr>"
                    for cid, qid in l.wrong)
    return f"""<div id="laya-study" class="grid g2" style="scroll-margin-top:88px">
<div class="card"><h3>Laya 是什么</h3>
<p>这是一个开源的类型化决策模型，接收 state 和 choice / noul / score 问题，
通过编码器和决策头返回概率与数值，不生成解释。Python 包采用 Apache-2.0 许可。
本次固定上游代码 <code>432312b36714d8889eba405507b37eda25257d9c</code>（0.4.7）。</p>
<p>上游提供 ModernBERT-large 英文版、mmBERT-base 多语言版和 typed-decisions 微调版。
本测试含大量中文，因此事先固定多语言版，未训练、未根据结果切换模型。
权重 revision 为 <code>{e(env["revision"])}</code>，实测参数量 {env["parameters"]:,}。</p>
<p>上游的 33 ms 是它自己的 T4 测量；typed-decisions 的 0.766 也来自另一个微调基准，
不能当成本报告的结果。上游明确记录了零样本决策偏弱、评分位置偏差和概率校准不足。</p>
<p class="small"><a href="https://github.com/NandhaKishorM/laya/tree/432312b36714d8889eba405507b37eda25257d9c">代码与 README</a> ·
<a href="https://huggingface.co/convaiinnovations/laya-multilingual/tree/{e(env['revision'])}">本次权重</a></p></div>
<div class="card"><h3>东京实测条件</h3><ul class="clean small">
<li>区域 <code>ap-northeast-1</code>，{e(l.instance["type"])}，{e(env["gpu"])}。
实例 <code>{e(l.instance["id"])}</code>，购买方式 {e(l.instance.get("market", "on-demand"))}。</li>
<li>东京 g5.xlarge 按需与 Spot 均无容量后，经用户确认改用 g5.2xlarge。
仍为单张 A10G，CPU / 内存增至 8 vCPU / 32 GiB，与原 Decider 的实例规格不同。</li>
<li>PyTorch {e(env["torch"])}、Transformers {e(env["transformers"])}、CUDA {e(env["cuda"])}；
实际设备 {e(env["device"])}，自动混合精度 {e(env["amp_dtype"])}。</li>
<li>固定 <code>max_len={l.manifest["controls"]["max_len"]}</code>、
<code>head_max_len={l.manifest["controls"]["head_max_len"]}</code>，不使用自动路由或自定义校准。
服务回执标记 state 截断的请求数：{len(l.truncated)}。正式测试前审计 {budget_audit["questions"]} 个问题，
state / 问题描述 / 选项发生截断的题数分别为 {budget_audit["state_truncated"]} /
{budget_audit["instruction_truncated"]} / {budget_audit["options_truncated"]}，
最长实际序列为 {budget_audit["max_sequence_tokens"]} tokens。</li>
<li>3 次独立中文冒烟预热后，76 个正式请求串行运行一次，无重试；
两个 UI 修正请求已纳入。原始响应、完整概率和请求 SHA-256 均保留。</li>
<li>时延是东京 GPU 主机的本机 HTTP 往返，中位 {l.lat:.4f} 秒，P90 {l.p90:.4f} 秒。
其他模型使用旧报告的客户端往返时间，网络路径不同，不能据此宣称严格同条件的速度倍数。</li>
</ul></div></div>
<div class="callout warn" style="margin-top:16px"><b>本批次答对 {l.correct}/{l.answered}（{l.correct/l.answered:.1%}）；
去掉误用对照组后 {l.correct_norm}/117（{l.correct_norm/117:.1%}）。</b>
评分题答对 {sum(ok for _, _, ok in l.score_q)}/{len(l.score_q)}。
choice / noul 题答错却直接选定 {len(l.review["wrong_sel"])} 个，答错且送复核 {l.review["wrong_rev"]} 个。
最高概率不低于 0.95 的 {len(l.high_conf)} 个判断中，答错 {len(l.high_conf)-sum(l.high_conf)} 个；
高概率不等于可靠。这个未微调检查点在本批任务中的准确率较低，需要按具体业务重新验证和校准。</div>
<div class="card" style="margin-top:16px"><h3>成本口径</h3>
<p>AWS Pricing API 查得东京 Linux / Shared / On-Demand 的 {e(l.instance["type"])} 计算价为 ${l.rate}/小时，
生效日期 2026-10-01。按正式批次 {l.wall:.4f} 秒折算为 ${l.cost:.6f}，不含下载、安装、预热、空闲、
EBS 和公网 IPv4；这不是实际账单。按此单价持续运行 24 小时的计算费为 ${l.rate*24:.3f}。
与美西 Decider 的 $1.006/小时存在地区和实例规格差异。</p></div>
<div class="table-wrap" style="margin-top:16px"><table><thead><tr><th>场景（含对照组）</th><th>Jev</th><th>Decider 2B</th><th>Laya</th><th>Laya 送复核</th></tr></thead>
<tbody>{table}</tbody></table></div>
<details style="margin-top:16px"><summary>全部 {len(l.wrong)} 个未达标判断</summary>
<div class="table-wrap"><table><thead><tr><th>请求</th><th>问题</th><th>原定标准</th><th>返回值</th></tr></thead>
<tbody>{wrong}</tbody></table></div></details>
<p class="small muted">原始记录：<code>validation/v2/{LAYA_FILE.name}</code>；
请求：<code>{e(l.manifest["requests_file"])}</code>；部署及输入审计：<code>deploy/laya-g5/</code>。
只重放了 Jev 的历史状态，没有运行由 Laya 动作驱动的新闭环；准确率不能当作 Laya 的任务完成率。
本次只覆盖一个检查点，不能代表英文版、微调版或整个 Laya 项目。</p>"""
