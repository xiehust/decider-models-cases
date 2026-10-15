# Decider 决策模型评测

对比 **Jev、Strands Decider 2B、Laya Multilingual** 在 Agent 决策任务中的表现，
并以 Claude Opus 5.5、Claude Haiku 5.5、GPT-6 Luna 作为 LLM 参照。
这里的 Decider 指类型化决策模型类别；Strands Decider 是其中一个参评模型。

评测于 2026-10-12 至 15 日进行，共用 76 个请求、147 个判断，覆盖 10 个场景。
报告关注具体场景的正确率、概率与复核、耗时和成本。主选型口径为排除 30 个自主规划误用对照判断后的 117 题；
总览的“什么时候用 Decider 模型”按实际场景给出三种决策模型的排名，同分并列。
选型表同时列出三个 LLM 的正确率；仅为本场景准确率严格超过 90% 的具体决策模型标注“可考虑使用”，
恰好 90% 不标注，LLM 高分不作为决策模型达标的依据。

测试集最初按 [jev-skill](https://github.com/wuyoscar/jev-skill) v0.2.0 构建，随后用于各模型的同题比较。
真实闭环由 Jev 驱动采集，其他模型重放相同状态；逐步答对率不能当作其他模型的任务完成率。
所有材料都是专门编写的合成内容，不涉及真实账户或业务数据。

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
deploy/laya-g5/             东京 Laya 部署、输入审计、环境及价格回执
```

`report/` 是生成产物。要改报告，改 `validation/v2/` 下的生成器后重新生成，不要直接编辑 HTML。

## 主要结果

三种决策模型在 117 个常规判断上的结果是：Jev **114/117（97.4%）**、
Strands Decider **93/117（79.5%）**、Laya Multilingual **52/117（44.4%）**。
这是本批合成数据的按题汇总，具体场景存在并列和次序变化，不代表通用能力排名。

同一批 76 个请求（147 个判断）的六模型结果如下。LLM 的单价是测试时给定的假设值，
Strands Decider 按美西 g5.xlarge 的 $1.006/小时折算，
Laya 按东京 g5.2xlarge 的 $1.75776/小时折算；两者均仅计算正式批次的串行机时。

| 方案（前三种为决策模型） | 费用 | 中位耗时 | 答对（147 题 / 不含对照组 117 题） |
|---|---:|---:|---:|
| Jev | $0.0025 | 0.19 秒 | 126 / 114 |
| Strands Decider 2B（自托管，按机时） | $0.0030 | 0.11 秒 | 99 / 93 |
| Laya Multilingual（东京自托管） | $0.0011 | 0.0227 秒（本机 HTTP） | 71 / 52 |
| GPT-6 Luna（$0.10/$0.50 每百万 tokens） | $0.0078 | 1.07 秒 | 141 / 111 |
| Claude Haiku 5.5（$0.10/$0.50） | $0.0137 | 1.80 秒 | 146 / 116 |
| Claude Opus 5.5（$4/$20） | $0.40 | 3.31 秒 | 145 / 115，另有 2 题因过滤未作答 |

Laya 的时延在东京 GPU 主机本地测量，其他模型沿用原报告的客户端往返记录，网络条件不同。
它的 76 个请求采用已有的两个 UI 输入修正；147 题均无 state、问题或选项截断，未发生 CPU fallback。

决策模型输出类型化答案及概率；LLM 参照只输出答案，不附理由。几个主要观察：

- 场景排名有差异：文档定位和代码定位中，Jev 与 Strands 并列第一；自主规划对照组中，Laya 的逐步答对数最高。
  仿真分成 NPC、按规划路线行动和自主规划对照分别展示，避免总分掩盖不同能力。
- 概率必须单独核验。Laya 最高概率不低于 0.95 的 28 个判断里有 18 个答错，不能把高概率直接当作可靠性保证。
- Laya 的本批机时费用最低；实际成本还包括部署、空闲等开销，且各模型网络与硬件条件不同。
- 三个 LLM 参照中，Haiku 5.5 的正确数最高，GPT-6 Luna 的费用和中位耗时最低。
  它们用于衡量质量与费用差距，不参加决策模型排名。
- Strands 的本次服务在并发下出现错误，正式比较采用串行回执。原始 Jev 规划闭环的失败、UI 核验和历史技能说明保留在各页补充证据中。

完整的数据、图表和分析见报告。

[Laya 的源码研究、部署与复现说明](deploy/laya-g5/README.md)包含固定的代码/权重 revision、
输入审计及原始回执。东京 g5.xlarge 无容量后，经确认使用单张 A10G 的 g5.2xlarge；
实际结果已加入总览图表与成本页。

## 查看报告

直接用浏览器打开 `report/index.html` 即可。页面是纯静态 HTML 和内联 SVG，不加载外部资源，也不含脚本。
总览页之外有 10 个场景页（`report/scenarios/`）和一个成本对比页（`report/cost.html`）。
每个场景页均包含六个模型的准确率、未作答数、复核数、中位耗时和费用，
以及可展开的逐题标准答案、实际返回值和对错对照。仿真页单列误用对照组，
UI 使用修正后的请求结果；自托管场景费用按请求耗时占比分摊原批次机时。

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
共用请求已保存在 `llm-requests-laya-20261015.json`，包含两个 UI 请求的输入修正；
历史 `llm-requests.json` 保留用于追溯。重新比较时通过 `--requests` 指定修正版。

```bash
python3 validation/v2/llm_baseline.py run --backend opus     --styles terse --requests validation/v2/llm-requests-laya-20261015.json --output validation/v2/opus-new.jsonl
python3 validation/v2/llm_baseline.py run --backend haiku    --styles terse --requests validation/v2/llm-requests-laya-20261015.json --output validation/v2/haiku-new.jsonl
python3 validation/v2/llm_baseline.py run --backend gpt6luna --styles terse --requests validation/v2/llm-requests-laya-20261015.json --output validation/v2/luna-new.jsonl
python3 validation/v2/llm_baseline.py run --backend decider --styles native --concurrency 1 --requests validation/v2/llm-requests-laya-20261015.json \
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
