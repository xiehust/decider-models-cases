#!/usr/bin/env bash
# 在管理机上执行：deploy.sh <gpu-private-ip>
# 启动本地 CONNECT 代理（仅 127.0.0.1），经 ssh -R 隧道让无公网的 GPU 机一次性下载依赖与权重，
# 安装 systemd 服务，等待就绪后跑冒烟测试。隧道随 ssh 结束而关闭。
set -euo pipefail
HOST=${1:?usage: deploy.sh <gpu-private-ip>}
HERE=$(cd "$(dirname "$0")" && pwd)
PROXY_PORT=${PROXY_PORT:-3128}
SSH_OPTS=(-T -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o ServerAliveInterval=30)

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
trap '[ -n "$PROXY_PID" ] && kill "$PROXY_PID" 2>/dev/null || true' EXIT

ssh "${SSH_OPTS[@]}" "ubuntu@$HOST" 'mkdir -p /tmp/strands-decider-src'
scp -q -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
  "$HERE/openai_server.py" "$HERE/strands-decider.service" "$HERE/remote_setup.sh" \
  "ubuntu@$HOST:/tmp/strands-decider-src/"
ssh "${SSH_OPTS[@]}" -R "$PROXY_PORT:127.0.0.1:$PROXY_PORT" "ubuntu@$HOST" \
  "https_proxy=http://127.0.0.1:$PROXY_PORT bash /tmp/strands-decider-src/remote_setup.sh"

echo "waiting for http://$HOST:8000/health"
for i in $(seq 1 60); do
  curl -sf "http://$HOST:8000/health" && { echo; break; }
  [ "$i" = 60 ] && { echo "not healthy; check: ssh ubuntu@$HOST journalctl -u strands-decider"; exit 1; }
  sleep 5
done
python3 "$HERE/smoke_test.py" "http://$HOST:8000"
