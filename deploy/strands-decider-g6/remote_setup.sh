#!/usr/bin/env bash
# 在 GPU 实例上执行（由 deploy.sh 通过 ssh -R 隧道调用）。
# 需要 https_proxy 指向隧道里的 CONNECT 代理；安装完成后服务以 HF_HUB_OFFLINE=1 离线运行。
set -euo pipefail
APP_DIR=/opt/strands-decider
CHECKPOINT=${DECIDER_CHECKPOINT:-StrandsAgents/strands-decider-2B-qwen3.5-v1-2610}
PKG=${DECIDER_PKG:-strands-decider==0.1.0}
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
PY

# 预下载 checkpoint + 基座（加载器按 provenance.json 固定基座 revision），之后离线运行
"$APP_DIR/venv/bin/python" -c "
from strands_decider.modeling import StrandsDeciderModel
StrandsDeciderModel.load('$CHECKPOINT'); print('weights cached')"

[ -f /etc/strands-decider.env ] || {
  printf 'DECIDER_CHECKPOINT=%s\n# DECIDER_API_KEY=可选的 Bearer key\n' "$CHECKPOINT" | sudo tee /etc/strands-decider.env >/dev/null
}
sudo install -m 0644 /tmp/strands-decider-src/strands-decider.service /etc/systemd/system/strands-decider.service
sudo systemctl daemon-reload
sudo systemctl enable strands-decider >/dev/null 2>&1
sudo systemctl restart strands-decider
echo "service restarted"
