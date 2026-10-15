# Laya：东京 g5.2xlarge 部署与同题对比

2026-10-15 已完成部署和真实对比。东京 g5.xlarge 的按需及 Spot 都返回容量不足后，
用户确认改用 **g5.2xlarge**，在 `ap-northeast-1a` 成功启动实例 `i-0b93cd55e444dca0f`。
公网管理地址 `54.248.147.234`，服务仅监听 `127.0.0.1:8000`，systemd 服务名 `laya`。
安全组只允许管理机 `54.189.180.95/32` 的 SSH，不开放公网推理端口。

实际环境为 NVIDIA A10G、8 vCPU、32 GiB 内存，Python 3.13、Laya 0.4.7；
完整依赖和 CUDA/PyTorch 版本见 `environment.json`、`requirements.lock.txt`。
模型实际参数量 321,908,995，CUDA 加载及 76 次调用均无 CPU fallback。

## 本次结果

| 指标 | 实测 |
|---|---:|
| 正式请求 / 判断 | 76 / 147 |
| 答对（含网格误用对照组） | 71/147（48.3%） |
| 答对（不含对照组） | 52/117（44.4%） |
| HTTP 往返中位 / P90 | 22.694 / 39.733 ms |
| 正式批次串行墙钟时间 | 2.260264248 秒 |
| 按需计算价 / 本批机时折算 | $1.75776/小时 / $0.001103612 |
| score 题通过 | 6/17 |
| choice / noul 答错且直接选定 | 24 |
| 最高概率 ≥0.95 的判断 / 其中答错 | 28 / 18 |
| state / 问题 / 选项截断 | 0 / 0 / 0 |

独立中文冒烟预热 3 次均答对，正式测试只跑一次、串行、无错误、无重试。
输入 token 合计 57,966，输出 token 为 0。最长实际序列 1,538 tokens；
默认 1,024 上下文不足以容纳最长输入，正式测试固定 `max_len=8192, head_max_len=256`。

Jev 同口径为 126/147、114/117，Strands Decider 为 99/147、93/117。
Laya 的批次机时费用较低，但零样本准确率和置信度校准明显不足，不能据此直接替换 Jev。
本次只测多语言检查点，没有测试英文版、typed-decisions 微调版、自动路由或再训练。
耗时在东京 GPU 主机本地 HTTP 测得，不能和其他模型原有网络往返时间视为严格同条件。
闭环题只是回放 Jev 历史状态，没有让 Laya 驱动新的闭环。

## 研究结论

- [Laya 0.4.7 源码](https://github.com/NandhaKishorM/laya/tree/432312b36714d8889eba405507b37eda25257d9c)
  使用编码器与决策头直接返回类型化判断，不生成解释；代码为 Apache-2.0。
- 三个检查点分别面向英文（ModernBERT-large，421M）、多语言（mmBERT-base，322M）、
  typed-decisions 四类合成工作流微调（ModernBERT-large，421M）。其中多语言版已在 GPU 加载核验。
- 本批有中文，事先选定 `convaiinnovations/laya-multilingual`，revision
  `1720e3e3357cfe1e281542e223f8273b0890ca34`。三个模型的实际配置已保存在 `*-metadata.json`。
  多语言版默认 `max_len=1024`、`head_max_len=256`，温度均为 1.0，无按选项数拟合的温度。
- `laya/router.py` 的默认模型来源其实是 `convaiinnovations/laya` 的子目录。
  部署配置通过 `LAYA_EXTRA_MODELS` 显式把 `multilingual` 指向独立模型仓库，
  再用 `LAYA_REVISION` 固定该仓库 revision，避免混用 revision。
- `laya/common.py::build_sequence` 按实际 head 长度分配 state 空间；
  `build_head` 将每个选项先截到 48 tokens，再按 head 预算分配。
  提高 `max_len` 不能避免 head 内部截断，已准备单独输入审计。
- 上游 README 自己说明：基础版零样本 typed-decisions 弱、`score` 有位置偏差、
  `noul` 对标签措辞敏感，多语言版概率未拟合。上游 33 ms（T4）与 0.766（微调基准）
  都不等于当前测试成绩；本次不会据此作替代 Jev 的结论。

## 文件与证据

| 文件 | 用途 |
|---|---|
| `PLAN.md` | 实测前的固定方案、验收与清理说明 |
| `launch_tokyo.py` | 东京专用实例启动脚本，安全组仅开放管理机 /32 的 SSH |
| `launch-attempts.jsonl` | 已归档的容量失败、UTC 时间、AWS Request ID |
| `tokyo-pricing.json` | Pricing API 回执：Linux 按需计算价 $1.459/小时 |
| `tokyo-g5-2xlarge-pricing.json` | 实际规格的价格回执：$1.75776/小时 |
| `tokyo-instance.json`、`deployment.json` | 实例启动及实际部署元数据 |
| `tokyo-resource-status-final.json` | 实测结束后的 running 状态与 CUDA 健康检查；不带 final 的文件是早先容量阻塞快照 |
| `environment.json`、`requirements.lock.txt` | 运行环境与完整依赖版本 |
| `input-audit.json` | 147 题实际 token 构造审计 |
| `../../validation/v2/llm-baseline-laya-20261015.jsonl` | 76 次正式原始响应、逐题验收、耗时和健康检查 |
| `../../validation/v2/laya-smoke-20261015.jsonl` | 单独保存的 3 次预热 |
| `remote_setup.sh` | 独立 Python 环境、固定源码/权重、systemd、loopback 服务 |
| `audit_inputs.py` | 逐题检查 state、问题和选项的实际 token 截断 |
| `../../validation/v2/laya_benchmark.py` | 串行、无重试、原始响应先落盘的评测运行器 |
| `../../validation/v2/llm-requests-laya-20261015.json` | 合并已存 UI 修正的 76 个请求，保留本地标准答案 |
| `instance.json`（仅本地草稿） | 本任务开始前已存在的美西配置；未纳入本次提交，不用于东京部署 |

请求整体 SHA-256（按运行器 canonical JSON 规则）：
`13a36c9fca0eb467b6a1eee2d1ac7f676828bb0b04c73e69ac1b2e86b75cc927`。

## 复现与访问

在项目根目录运行。仅在前次明确返回容量不足后更换 `--attempt`，避免不明结果下重复创建。

```bash
python3 deploy/laya-g5/launch_tokyo.py --instance-type g5.2xlarge --attempt next-confirmed-capacity-retry
```

启动回执写到 `tokyo-instance.json`；从 EC2 读取该实例公网地址后，用 `~/.ssh/id_ed25519` 管理。
推理端口不对公网开放：

```bash
scp deploy/laya-g5/remote_setup.sh ubuntu@<public-ip>:/tmp/laya-setup.sh
ssh ubuntu@<public-ip> 'bash /tmp/laya-setup.sh'
ssh -L 18000:127.0.0.1:8000 ubuntu@<public-ip>
curl http://127.0.0.1:18000/health
```

将仓库的 `validation/`、`.agents/skills/jev/` 和部署证据复制到 GPU 主机。
新环境需生成 `deployment.json`，其中 `instance` 包含 `type/id/usd_per_hour/market/source`，
`environment` 使用 GPU 主机 `/opt/laya/environment.json`。记录实际 EC2 状态、GPU、价格、
依赖锁与源码/权重 revision。先运行 `audit_inputs.py`，在看到模型答案前确认输入预算。

```bash
HF_HOME=/opt/laya/hf /opt/laya/venv/bin/python deploy/laya-g5/audit_inputs.py \
  validation/v2/llm-requests-laya-20261015.json deploy/laya-g5/input-audit-new.json
python3 validation/v2/laya_benchmark.py smoke --deployment deploy/laya-g5/deployment.json \
  --output validation/v2/laya-smoke-new.jsonl
python3 validation/v2/laya_benchmark.py run --deployment deploy/laya-g5/deployment.json \
  --output validation/v2/laya-new.jsonl
```

正式结果必须是 GPU 主机 loopback 的 HTTP 时延；不使用跨太平洋 SSH 隧道计时。
3 次冒烟预热独立记录；正式 76 次逐一执行、不重试。每个请求只发送 state/questions 和模型控制参数，
不发送 grade/expected。健康检查验证 CUDA 实际设备及是否发生 CPU fallback。
运行 `python3 validation/v2/build_report.py` 可从本次固定回执重新生成报告，
生成器会复算标签、分数、指纹和指标。若要改用另一轮结果，应修改
`report_laya.py` 的 `LAYA_FILE` 及对应的部署、审计资料，不覆盖本次原始记录。

## 费用与清理

实际 g5.2xlarge 东京按需计算费 $1.75776/小时、$42.18624/天。
报告中的 $0.001103612 仅按正式批次机时折算，不含安装、下载、预热、空闲、EBS 和公网 IPv4，
不是本次完整账单。实例和服务保留运行，供后续使用。
key pair 为 `decider-cases-laya-tokyo`，安全组为 `sg-06e1e236e14e106f7`。

按需实例可按需要停止；停止仍有 EBS 费用。本次实际没有使用 Spot。
彻底清理时，先核实实例 ID 再终止，最后删除专用安全组和 key pair；
不要动美西旧部署。

```bash
# 建立访问隧道，另一个终端访问 http://127.0.0.1:18000/health
ssh -N -L 18000:127.0.0.1:8000 ubuntu@54.248.147.234
# 按需停止计算计费（模型与依赖保留在 EBS）
aws ec2 stop-instances --region ap-northeast-1 --instance-ids i-0b93cd55e444dca0f
```
