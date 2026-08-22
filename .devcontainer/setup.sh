#!/usr/bin/env bash
# Codespace provisioning. This is the DEV box — no GPU, no models.
# The GB10 is provisioned separately by Role A via scripts/setup_box.sh.
set -euo pipefail

echo "==> System packages"
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg curl gnupg jq

echo "==> MongoDB 8.0 (local, for development against real collections)"
curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc \
  | sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor
echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" \
  | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list >/dev/null
sudo apt-get update -qq
sudo apt-get install -y -qq mongodb-org
sudo mkdir -p /data/db && sudo chown -R "$(whoami)" /data/db
(mongod --dbpath /data/db --bind_ip 127.0.0.1 --fork --logpath /tmp/mongod.log || true)

echo "==> Python environment"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q \
  fastapi "uvicorn[standard]" websockets pymongo motor \
  numpy pillow opencv-python-headless \
  scenedetect httpx pydantic python-multipart ruff

echo "==> Agent tooling (memory + knowledge graph), mirroring the host setup"
pip install -q mempalace graphifyy || echo "    (skipped — install manually if needed)"

echo
echo "==================================================================="
echo " Codespace ready."
echo
echo "   1. Read docs/ROLES.md  — your branch and your directories"
echo "   2. Read docs/api.md    — the contract you build against"
echo "   3. Start the mock:     uvicorn backend.mock.app:app --reload --port 8000"
echo
echo " One manual step: run 'claude' once to authenticate. Interactive"
echo " login cannot be scripted."
echo
echo " Reminder: this box has NO GPU. Model work happens on the GB10."
echo "==================================================================="
