# Jev 应用场景验证

这个仓库记录了 2026 年 10 月 12 日对 Jev 做的一轮场景验证。Jev 是一个类型化判断模型，
给它候选项、是非题或评分等级，它返回带概率的答案，本身不写文字。仓库为
[jev-skill](https://github.com/wuyoscar/jev-skill) v0.2.0 的 11 个技能各编写了一组接近真实业务、埋有陷阱的场景，
经 OpenRouter 真实调用后，再用测试套件、浏览器 DOM、规则引擎和原文比对逐一核对结果。
之后又把同一批请求交给 Bedrock 上的 Claude Opus 5.5、Claude Haiku 5.5、GPT-6 Luna，
以及同 VPC 自托管的 Strands Decider 2B，比较成本、耗时和准确率。

所有测试材料都是专门编写的合成内容，不涉及真实账户或业务数据。

## 目录结构

```
.agents/                     Jev 技能（jev-skill v0.2.0 原样副本）、安装记录与上游许可
report/                      生成好的静态 HTML 报告，离线可看（index.html 为总览）
validation/
  run.py, cases.py           v1 冒烟测试：12 个请求，结果见 validation/README.md
  test_validation.py         离线单元测试（mock 响应，不联网）
  live-20261012.jsonl        v1 的原始调用记录
  v2/
    cases_v2.py              v2 静态场景与标准答案（调用前写定，不随请求发出）
    loops_v2.py              闭环场景：NPC 对话、网格寻路、真实浏览器 UI
    run_v2.py                v2 有界运行器（Jev / OpenRouter）
    llm_baseline.py          同一批请求交给其他模型的对比运行器
    build_report.py          从调用记录生成 report/，report_*.py 是它的数据、图表与文案模块
    fixtures/                合成测试材料：PR、迷你电商仓库、合同、测试网页
    artifacts/               浏览器截图与无障碍快照
    live-*.jsonl, llm-*.json(l)  原始调用记录与重建的请求
deploy/strands-decider-g6/   Strands Decider 2B 的 VPC 内网部署脚本，说明见其 README
```

`report/` 是生成产物。要改报告，改 `validation/v2/` 下的生成器后重新生成，不要直接编辑 HTML。

## 主要结果

v2 一共调用 Jev 76 次（模型 `typesafe/jev-1.13-20260917`），API 返回的费用合计 $0.0025，单次调用中位耗时 0.19 秒。
不含网格误用对照组时，117 个判断中有 114 个符合标准答案，另有 9 个进入 needs_review。

同一批 76 个请求（147 个判断）交给其他模型的结果如下。LLM 的单价是测试时给定的假设值，
自托管模型按 g5.xlarge 按需价 $1.006/小时乘以本批次的串行用时折算。

| 方案 | 费用 | 中位耗时 | 答对（147 题 / 不含对照组 117 题） |
|---|---:|---:|---:|
| Jev | $0.0025 | 0.19 秒 | 126 / 114 |
| Strands Decider 2B（自托管，按机时） | $0.0030 | 0.11 秒 | 98 / 92 |
| GPT-6 Luna（$0.10/$0.50 每百万 tokens） | $0.0079 | 1.13 秒 | 140 / 110 |
| Claude Haiku 5.5（$0.10/$0.50） | $0.0140 | 1.81 秒 | 146 / 116 |
| Claude Opus 5.5（$4/$20） | $0.40 | 3.38 秒 | 145 / 115，另有 2 个被内容过滤 |

LLM 和 Jev 一样只输出答案，不附理由。几点值得先看：

- 在选项明确、证据齐全的问题上，Jev 很可靠，最高概率不低于 0.95 的判断全部答对。缺少依据时它会给出 none 或 unknown，
  不会硬猜。
- Jev 不适合多步规划。让它独自在网格里找路，30 个回合都没送到。改由规划器给出路线、Jev 只选下一步后，20 个回合按最短路线送达。
- 最便宜的 LLM 也要花 Jev 的 3.1 倍。Haiku 5.5 最准，GPT-6 Luna 在 UI 任务里把“只勾选、未保存”判成了完成。
- Strands Decider 2B 最快，但在这批用例上明显不准。它的服务端在并发请求下会出错，最终结果是串行测得的。

完整的数据、图表和分析见报告。

## 查看报告

直接用浏览器打开 `report/index.html` 即可。页面是纯静态 HTML 和内联 SVG，不加载外部资源，也不含脚本。
总览页之外有 11 个场景页（`report/scenarios/`）和一个成本对比页（`report/cost.html`）。

## 复现

**依赖。** Python 3.10 以上，只用标准库。生成报告时如果装了 Pillow，会顺带裁剪截图。
Jev 技能已经随仓库提交在 `.agents/skills/`，是 jev-skill v0.2.0（commit `82c0105`）的原样副本，安装记录见
`.agents/jev-installation.md`。脚本从这里读取 `jev/scripts/jev.py` 和 `jev-redteam/scripts/prepare.py`，
路径集中定义在 `validation/cases.py` 的 `SKILLS`。运行器还会调用 `jev-decide` CLI，它不在仓库里，
需要用 `uv tool install` 从同一版本另行安装。

**离线检查，不联网、不花钱：**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s validation   # 运行器的单元测试
python3 validation/run.py                                              # v1 用例 + CLI dry-run
python3 validation/v2/run_v2.py                                        # v2 用例 + CLI dry-run
python3 validation/v2/build_report.py                                  # 从已有调用记录重新生成 report/
```

**真实调用 Jev（会产生费用，需要 `OPENROUTER_API_KEY`）。** UI 场景要一个只绑定本机的 HTTP 服务来提供测试页，
浏览器用 `validation/v2/browser.chromium.json` 里配置的 Snap 版 Chromium，沙箱保持开启。
在开启了 `kernel.apparmor_restrict_unprivileged_userns` 的 Ubuntu 上，Playwright 自带的 Chromium 开着沙箱启动不了，Snap 版可以。

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory validation &
python3 validation/v2/run_v2.py --live --output validation/v2/live-new.jsonl
python3 validation/v2/run_v2.py --live --followup --output validation/v2/live-new-grid.jsonl   # 网格变体 B
```

输出文件必须是新文件，脚本不会覆盖已有的调用记录。运行器上限 80 次调用，并发 4，不重试，
按 API 返回的费用累计到 0.02 美元即停止。

**与其他模型对比。** 需要有 Bedrock 权限的 AWS 凭证（脚本用默认凭证链和 SigV4 签名）。
`llm-requests.json` 已经提交，就是 Jev 当时看到的 76 个请求，可以直接复用。

```bash
python3 validation/v2/llm_baseline.py run --backend opus     --styles terse --output validation/v2/opus-new.jsonl
python3 validation/v2/llm_baseline.py run --backend haiku    --styles terse --output validation/v2/haiku-new.jsonl
python3 validation/v2/llm_baseline.py run --backend gpt6luna --styles terse --output validation/v2/luna-new.jsonl
python3 validation/v2/llm_baseline.py run --backend decider --styles native --concurrency 1 \
    --output validation/v2/decider-new.jsonl
```

脚本默认会把每个请求再按“答案加一句理由”跑一遍，报告只用 `terse`（只输出答案），所以上面加了 `--styles terse`。

Strands Decider 2B 的地址写在 `llm_baseline.py` 的 `BACKENDS` 里，是本次测试所在 VPC 的内网 IP，换环境时要改。
它的服务端在并发请求下不安全，必须用 `--concurrency 1`。部署方法见 `deploy/strands-decider-g6/README.md`。
那份说明按 g6.2xlarge（L4）编写，本次实际测到的是一台 g5.xlarge（A10G），成本按后者计算。

## 测试原则与局限

- 标准答案在调用之前写定，记在每份调用记录开头的 manifest 里，不会随请求发出。
- 结果靠调用方的确定性手段独立核对，包括实际运行测试和探针、读取浏览器 DOM、用规则引擎校验状态转换、按 ID 复制原文。
- 未达标的结果原样保留，没有事后放宽区间。网格变体 B 和“不含网格误用对照组的 117 题”这个口径，都是看到变体 A
  失败之后才加上的，不属于事先定好的评测方案，报告里也是这样标注的。
- LLM 的单价是测试时给定的假设值，没有核实 Bedrock 牌价，也没有计入批量和缓存折扣。
- 每个请求每种写法只跑了一次，样本量小，用例也出自同一个作者。这些结果说明场景跑得通、判断与标准答案一致，
  不能代表普遍的准确率。

## 许可

本仓库以 Apache License 2.0 发布，见 `LICENSE`。`.agents/skills/` 下的 Jev 技能来自上游 jev-skill，使用 MIT 许可，
许可文本见 `.agents/jev-LICENSE`。
