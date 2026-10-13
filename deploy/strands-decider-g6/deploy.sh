#!/usr/bin/env bash
# 在管理机上执行：deploy.sh <gpu-private-ip>
# 启动本地 CONNECT 代理（仅 127.0.0.1），经 ssh -R 隧道让无公网的 GPU 机一次性下载依赖与权重，
# 安装 systemd 服务，等待就绪后跑冒烟测试。隧道随 ssh 结束而关闭。
#
# 用法：deploy.sh <gpu-private-ip> [--选项 值 | --选项=值]...   （命令行优先于同名环境变量）
#   --decider-checkpoint C   HF checkpoint，默认 StrandsAgents/strands-decider-2B-qwen3.5-v1-2610
#   --decider-pkg P          pip 依赖说明，默认 strands-decider==0.1.0。git+ 地址或含 " @ git+" 的说明
#                            会先在管理机打成 wheel 再上传（GPU 机的代理不放行 GitHub）；也可直接给本地 .whl
#   --decider-model-name M   /v1/models 中的模型名，默认取 checkpoint 名最后一段
#   --api-port P             服务端口，默认 8000（须与 launch.sh 安全组放行的端口一致）
#   --max-batch N            每次前向编码的问题数，默认不传（服务端默认 32；需 strands-decider main）
#   --max-batch-tokens N     每次前向的 token 上限，默认不传（长窗口大模型建议设置；需 main）
#   --health-timeout-s S     等待 /health 的秒数，默认 300   --proxy-port P  本地代理端口，默认 3128
# 选项名即环境变量名的小写连字符形式（--decider-pkg 对应 DECIDER_PKG）。
set -euo pipefail
HOST=${1:?usage: deploy.sh <gpu-private-ip> [options] (see --help)}
case "$HOST" in -h|--help) sed -n '2,/^set /p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'; exit 0 ;; esac
shift
OPTS="DECIDER_CHECKPOINT DECIDER_PKG DECIDER_MODEL_NAME API_PORT MAX_BATCH MAX_BATCH_TOKENS HEALTH_TIMEOUT_S PROXY_PORT"
while [ $# -gt 0 ]; do
  case "$1" in
    --*=*) k=${1%%=*}; v=${1#*=}; shift ;;
    --*) [ $# -ge 2 ] || { echo "missing value for $1" >&2; exit 2; }; k=$1; v=$2; shift 2 ;;
    *) echo "unknown argument: $1 (see --help)" >&2; exit 2 ;;
  esac
  var=$(printf '%s' "${k#--}" | tr 'a-z-' 'A-Z_')
  case " $OPTS " in *" $var "*) printf -v "$var" '%s' "$v" ;; *) echo "unknown option: $k (see --help)" >&2; exit 2 ;; esac
done
HERE=$(cd "$(dirname "$0")" && pwd)
DECIDER_CHECKPOINT=${DECIDER_CHECKPOINT:-StrandsAgents/strands-decider-2B-qwen3.5-v1-2610}
DECIDER_PKG=${DECIDER_PKG:-strands-decider==0.1.0}
DECIDER_MODEL_NAME=${DECIDER_MODEL_NAME:-${DECIDER_CHECKPOINT##*/}}
API_PORT=${API_PORT:-8000}
MAX_BATCH=${MAX_BATCH:-}
MAX_BATCH_TOKENS=${MAX_BATCH_TOKENS:-}
HEALTH_TIMEOUT_S=${HEALTH_TIMEOUT_S:-300}
PROXY_PORT=${PROXY_PORT:-3128}
SSH_OPTS=(-T -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o ServerAliveInterval=30)
echo "deploy $DECIDER_CHECKPOINT ($DECIDER_PKG) to $HOST:$API_PORT"

# git 来源先在本机打 wheel：锁定所取的提交，GPU 机也无需访问 GitHub
UPLOAD=()
WHEEL_DIR=""
case "$DECIDER_PKG" in
  git+*|*" @ git+"*)
    WHEEL_DIR=$(mktemp -d)
    python3 -m pip wheel -q --no-deps -w "$WHEEL_DIR" "$DECIDER_PKG"
    WHEEL=$(ls "$WHEEL_DIR"/*.whl) ;;
  *.whl) WHEEL=$DECIDER_PKG ;;
  *) WHEEL="" ;;
esac
if [ -n "$WHEEL" ]; then
  echo "wheel: $(basename "$WHEEL")"
  UPLOAD+=("$WHEEL")
  DECIDER_PKG="/tmp/strands-decider-src/$(basename "$WHEEL")"
fi

for i in $(seq 1 30); do
  ssh "${SSH_OPTS[@]}" "ubuntu@$HOST" true 2>/dev/null && break
  [ "$i" = 30 ] && { echo "ssh to $HOST not ready"; exit 1; }
  sleep 10
done

PROXY_PID=""
if ! curl -s -o /dev/null -x "http://127.0.0.1:$PROXY_PORT" https://pypi.org/simple/ 2>/dev/null; then
  python3 "$HERE/connect_proxy.py" "$PROXY_PORT" >/tmp/strands-decider-proxy.log 2>&1 &
  PROXY_PID=$!
  sleep 1
fi
trap '[ -n "$PROXY_PID" ] && kill "$PROXY_PID" 2>/dev/null; [ -n "$WHEEL_DIR" ] && rm -rf "$WHEEL_DIR"; true' EXIT

ssh "${SSH_OPTS[@]}" "ubuntu@$HOST" 'rm -rf /tmp/strands-decider-src && mkdir -p /tmp/strands-decider-src'
scp -q -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
  "$HERE/openai_server.py" "$HERE/strands-decider.service" "$HERE/remote_setup.sh" ${UPLOAD[@]+"${UPLOAD[@]}"} \
  "ubuntu@$HOST:/tmp/strands-decider-src/"
REMOTE_ENV=$(printf '%q ' "https_proxy=http://127.0.0.1:$PROXY_PORT" "DECIDER_CHECKPOINT=$DECIDER_CHECKPOINT" \
  "DECIDER_PKG=$DECIDER_PKG" "DECIDER_MODEL_NAME=$DECIDER_MODEL_NAME" "DECIDER_PORT=$API_PORT" \
  "DECIDER_MAX_BATCH=$MAX_BATCH" "DECIDER_MAX_BATCH_TOKENS=$MAX_BATCH_TOKENS")
ssh "${SSH_OPTS[@]}" -R "$PROXY_PORT:127.0.0.1:$PROXY_PORT" "ubuntu@$HOST" \
  "env $REMOTE_ENV bash /tmp/strands-decider-src/remote_setup.sh"

echo "waiting up to ${HEALTH_TIMEOUT_S}s for http://$HOST:$API_PORT/health"
deadline=$((SECONDS + HEALTH_TIMEOUT_S))
until curl -sf "http://$HOST:$API_PORT/health"; do
  [ "$SECONDS" -lt "$deadline" ] || { echo "not healthy; check: ssh ubuntu@$HOST journalctl -u strands-decider"; exit 1; }
  sleep 5
done
echo
echo "ready after $((SECONDS - deadline + HEALTH_TIMEOUT_S))s"
python3 "$HERE/smoke_test.py" "http://$HOST:$API_PORT"
