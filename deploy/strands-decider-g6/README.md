# strands-decider 在 g6.2xlarge 上的 VPC 内网部署

把 `StrandsAgents/strands-decider-2B-qwen3.5-v1-2610` 部署到当前 VPC 内一台无公网 IP 的
g6.2xlarge（1× NVIDIA L4），提供 OpenAI 兼容的 `/v1/chat/completions`，只能通过内网 IP 访问。

## 先读：这是决策模型，不是生成模型

模型是 Qwen3.5-2B-Base 上的 LoRA 加一个读出头，只对类型化问题的选项打分
（`noul` 是非题、`choice` 单选、`score` 有序等级），不会生成自由文本。官方
`strands-decider serve` 只有 `POST /v1/systemone`。`openai_server.py` 原样复用官方
`create_app`（保留 `/health` 与 `/v1/systemone`），再加上：

- `GET /v1/models`
- `POST /v1/chat/completions`：把 messages 作为 state，问题从以下三处取一（按优先级）：
  1. 顶层 `questions`（OpenAI SDK 用 `extra_body={"questions": {...}}`），原生格式；
  2. `response_format: {"type": "json_schema"}`：`boolean` 属性→noul，字符串 `enum`→choice
     （可选 `"x-descriptions": {选项: 说明}`，缺省为空串，与官方 CLI 一致），
     `integer` 加 `"x-levels": [...]`→score；`description` 作为问题文本；
  3. 最后一条 user 消息内容是 JSON `{"state"?, "questions"}`。

  `choices[0].message.content` 是 JSON：用 json_schema 时是符合 schema 的对象
  （布尔、枚举值、等级下标），否则是完整类型化答案。完整概率与置信度总在额外字段 `decider`。
  `stream: true` 返回单块 SSE。不支持 `tools`、`n>1`、图片；没有问题的纯聊天请求返回 400。

可选鉴权：在 GPU 机 `/etc/strands-decider.env` 写 `DECIDER_API_KEY=...` 后重启服务，
之后 `/v1/*` 需要 `Authorization: Bearer <key>`（`/health` 不受限）。

## 网络设计

- 当前 VPC `vpc-0edf3a4e323c23b22`（172.31.0.0/16）没有 NAT 网关。私有子网
  `subnet-032b21959bdb16c4f`（us-west-2b，只有 local 路由）优先；该 AZ 无容量时退到默认子网，
  但始终 `AssociatePublicIpAddress=false`，没有公网 IP 就无法经 IGW 进出。
- 安全组 `strands-decider-g6`：8000 只放行 VPC CIDR，22 只放行管理机所在 SG。
- 无公网的机器下载不了 PyPI / Hugging Face，所以 `deploy.sh` 在管理机 127.0.0.1 启动
  `connect_proxy.py`（只允许 CONNECT 到 PyPI、HF、PyTorch 域名的 443），经 `ssh -R` 隧道
  一次性安装依赖并缓存权重。之后服务以 `HF_HUB_OFFLINE=1` 离线运行，隧道随 ssh 结束关闭。

## 使用

```bash
cd deploy/strands-decider-g6
./launch.sh                      # 有界重试抢容量；最后一行 LAUNCHED <id> <private-ip> <az>
./deploy.sh <private-ip>         # 安装、启动 systemd 服务、等待健康、跑冒烟测试
python3 smoke_test.py http://<private-ip>:8000 [api-key]   # 随时复测
```

`launch.sh` 的参数都可用环境变量覆盖：`REGION VPC_ID VPC_CIDR NAME INSTANCE_TYPE KEY_NAME
SSH_PUBKEY ADMIN_SG SUBNETS SG_ID AMI_ID AMI_NAME ROUNDS SLEEP_S VOLUME_GB`。它是幂等的：
已有同 `Name` 标签的 pending/running 实例时直接输出该实例，不会再建第二台。
AMI 默认取最新的 “Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.12 (Ubuntu 24.04)”，
只用它的 NVIDIA 驱动：`remote_setup.sh` 用第一个带 `ensurepip` 的系统解释器建隔离的
`/opt/strands-decider/venv`，装 torch 与 `strands-decider==0.1.0`（`DECIDER_PKG` 可改）。
该 AMI 的系统 python3(3.12) 没有 `ensurepip`，实际用的是 python3.13。不要用
`--system-site-packages`：`/opt/pytorch` 本身是 venv，继承得到的是系统 3.12 的 dist-packages，
会在 import boto3/cryptography 时崩溃。
`launch.sh` 会跳过所在 AZ 不提供该机型的子网（如 g5 在 us-west-2d 不提供）。

调用示例（VPC 内任意机器）：

```python
from openai import OpenAI
c = OpenAI(base_url="http://<private-ip>:8000/v1", api_key="unused")
r = c.chat.completions.create(
    model="strands-decider-2B-qwen3.5-v1-2610",
    messages=[{"role": "user", "content": "Help! My payouts have been failing for 3 days!"}],
    response_format={"type": "json_schema", "json_schema": {"name": "t", "schema": {
        "type": "object", "properties": {
            "team": {"type": "string", "enum": ["billing", "sales", "retail"],
                     "description": "Which team should handle this?"},
            "urgent": {"type": "boolean", "description": "Does this convey urgency?"}}}}})
print(r.choices[0].message.content)   # {"team": "billing", "urgent": true}
```

## 运维

```bash
ssh ubuntu@<private-ip> 'systemctl status strands-decider; journalctl -u strands-decider -n 50'
aws ec2 terminate-instances --instance-ids <id>   # 停止计费；SG 与 key pair 可保留复用
```

## 文件

| 文件 | 运行位置 | 作用 |
|---|---|---|
| `launch.sh` | 管理机 | 建 key pair / SG，找 AMI，无公网 IP 启动实例，容量不足时有界重试 |
| `deploy.sh` | 管理机 | 代理 + ssh 隧道，上传并执行 `remote_setup.sh`，健康检查，冒烟测试 |
| `connect_proxy.py` | 管理机 | 仅本机监听、域名白名单的 HTTPS CONNECT 代理 |
| `remote_setup.sh` | GPU 机 | venv、依赖、权重缓存、systemd 服务 |
| `strands-decider.service` | GPU 机 | uvicorn 单 worker，0.0.0.0:8000，离线模式 |
| `openai_server.py` | GPU 机 | OpenAI 兼容层（见上） |
| `smoke_test.py` | 任意 VPC 内机器 | 标准库冒烟测试 |
