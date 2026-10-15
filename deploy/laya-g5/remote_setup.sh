#!/usr/bin/env bash
set -euo pipefail
LAYA_APP=/opt/laya
LAYA_COMMIT=432312b36714d8889eba405507b37eda25257d9c
LAYA_REVISION=1720e3e3357cfe1e281542e223f8273b0890ca34
sudo mkdir -p "$LAYA_APP"
sudo chown ubuntu:ubuntu "$LAYA_APP"
for candidate in python3 python3.13 python3.12; do
  if "$candidate" -c 'import ensurepip' 2>/dev/null; then
    "$candidate" -m venv "$LAYA_APP/venv"
    break
  fi
done
"$LAYA_APP/venv/bin/python" -m pip install --upgrade pip
"$LAYA_APP/venv/bin/pip" install "laya[serve] @ git+https://github.com/NandhaKishorM/laya.git@$LAYA_COMMIT"
export HF_HOME="$LAYA_APP/hf"
export LAYA_REVISION
"$LAYA_APP/venv/bin/python" - <<'PY'
import json, os, torch, transformers, laya
from pathlib import Path
assert torch.cuda.is_available(), "CUDA required; do not accept CPU fallback"
agent = laya.load("convaiinnovations/laya-multilingual", device="cuda", revision=os.environ["LAYA_REVISION"])
assert agent.device.type == "cuda"
data = {
    "torch": torch.__version__, "transformers": transformers.__version__, "laya": laya.__version__,
    "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0), "device": str(agent.device),
    "revision": agent.revision, "amp_dtype": str(agent.dtype), "config": agent.cfg,
    "parameters": sum(p.numel() for p in agent.model.parameters()),
}
Path("/opt/laya/environment.json").write_text(json.dumps(data, indent=2) + "\n")
print(json.dumps(data, indent=2))
PY
"$LAYA_APP/venv/bin/pip" freeze > "$LAYA_APP/requirements.lock.txt"
sudo tee /etc/systemd/system/laya.service >/dev/null <<EOF
[Unit]
Description=Laya multilingual decision service
After=network-online.target

[Service]
User=ubuntu
WorkingDirectory=$LAYA_APP
Environment=HF_HOME=$LAYA_APP/hf
Environment=HF_HUB_OFFLINE=1
Environment=LAYA_DEVICE=cuda
Environment=LAYA_HOST=127.0.0.1
Environment=LAYA_PORT=8000
Environment=LAYA_PRELOAD=1
Environment=LAYA_MODELS=multilingual
Environment=LAYA_MAX_LOADED=1
Environment=LAYA_AUTO_TASK=0
Environment=LAYA_REVISION=$LAYA_REVISION
Environment='LAYA_EXTRA_MODELS={"multilingual":"convaiinnovations/laya-multilingual"}'
ExecStart=$LAYA_APP/venv/bin/laya-serve
Restart=on-failure
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now laya
