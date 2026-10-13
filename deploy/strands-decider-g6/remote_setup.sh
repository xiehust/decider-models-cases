#!/usr/bin/env bash
# 在 GPU 实例上执行（由 deploy.sh 通过 ssh -R 隧道调用）。
# 需要 https_proxy 指向隧道里的 CONNECT 代理；安装完成后服务以 HF_HUB_OFFLINE=1 离线运行。
set -euo pipefail
APP_DIR=/opt/strands-decider
CHECKPOINT=${DECIDER_CHECKPOINT:-StrandsAgents/strands-decider-2B-qwen3.5-v1-2610}
PKG=${DECIDER_PKG:-strands-decider==0.1.0}
MODEL_NAME=${DECIDER_MODEL_NAME:-${CHECKPOINT##*/}}
PORT=${DECIDER_PORT:-8000}
MAX_BATCH=${DECIDER_MAX_BATCH:-}
MAX_BATCH_TOKENS=${DECIDER_MAX_BATCH_TOKENS:-}
: "${https_proxy:?https_proxy must point at the tunnelled proxy, e.g. http://127.0.0.1:3128}"
export HTTPS_PROXY=$https_proxy HF_HOME=$APP_DIR/hf

nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
sudo mkdir -p "$APP_DIR" && sudo chown "$(id -u):$(id -g)" "$APP_DIR"
install -m 0644 /tmp/strands-decider-src/openai_server.py "$APP_DIR/openai_server.py"

# 隔离 venv（不用 --system-site-packages：会混入系统 Python 3.12 的 dist-packages 导致崩溃）。
# DLAMI 的系统 python3(3.12) 缺 ensurepip；选第一个带 ensurepip 的解释器（该 AMI 上是 python3.13）。
if ! "$APP_DIR/venv/bin/python" -m pip --version >/dev/null 2>&1 || \
   grep -q 'include-system-site-packages = true' "$APP_DIR/venv/pyvenv.cfg" 2>/dev/null; then
  BASE_PY=""
  for p in ${BASE_PY_CANDIDATES:-python3 python3.13 python3.12 python3.11}; do
    if command -v "$p" >/dev/null && "$p" -c 'import ensurepip' 2>/dev/null; then BASE_PY=$p; break; fi
  done
  [ -n "$BASE_PY" ] || { echo "no python with ensurepip found"; exit 1; }
  rm -rf "$APP_DIR/venv"
  "$BASE_PY" -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q torch "$PKG"
"$APP_DIR/venv/bin/python" - <<'PY'
import torch, transformers, peft
print("torch", torch.__version__, "cuda", torch.version.cuda, "available", torch.cuda.is_available())
print("transformers", transformers.__version__, "peft", peft.__version__)
assert torch.cuda.is_available(), "CUDA not available"
# 新架构（如 Blackwell）上 wheel 缺少对应 kernel 时，只有真正跑一个算子才会报错
x = torch.ones(256, 256, device="cuda", dtype=torch.bfloat16)
assert float((x @ x)[0, 0]) == 256.0
print("gpu", torch.cuda.get_device_name(0), "capability", torch.cuda.get_device_capability(0), "kernel ok")
PY

# 预下载 checkpoint + 基座（加载器按 provenance.json 固定基座 revision），之后离线运行
"$APP_DIR/venv/bin/python" -c "
from strands_decider.modeling import StrandsDeciderModel
StrandsDeciderModel.load('$CHECKPOINT'); print('weights cached')"
df -h "$APP_DIR" | tail -1

# 每次部署都按本次参数重写 env 文件，只保留已有的 DECIDER_API_KEY
KEY_LINE=$(sudo grep -E '^DECIDER_API_KEY=' /etc/strands-decider.env 2>/dev/null || true)
{
  printf 'DECIDER_CHECKPOINT=%s\nDECIDER_MODEL_NAME=%s\nDECIDER_PORT=%s\n' "$CHECKPOINT" "$MODEL_NAME" "$PORT"
  [ -z "$MAX_BATCH" ] || printf 'DECIDER_MAX_BATCH=%s\n' "$MAX_BATCH"
  [ -z "$MAX_BATCH_TOKENS" ] || printf 'DECIDER_MAX_BATCH_TOKENS=%s\n' "$MAX_BATCH_TOKENS"
  if [ -n "$KEY_LINE" ]; then printf '%s\n' "$KEY_LINE"; else echo '# DECIDER_API_KEY=可选的 Bearer key'; fi
} | sudo tee /etc/strands-decider.env >/dev/null
sudo chmod 0600 /etc/strands-decider.env
sudo install -m 0644 /tmp/strands-decider-src/strands-decider.service /etc/systemd/system/strands-decider.service
sudo systemctl daemon-reload
sudo systemctl enable strands-decider >/dev/null 2>&1
sudo systemctl restart strands-decider
echo "service restarted"
