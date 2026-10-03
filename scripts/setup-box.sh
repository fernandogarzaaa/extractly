#!/usr/bin/env bash
# setup-box.sh: one-shot production setup for the Extractly box.
# Run ON THE BOX as the ubuntu user. Idempotent: safe to re-run.
#
# Prerequisite (do this FIRST, by hand, never in chat):
#   write /opt/extractly/extractly.env containing:
#       NEBIUS_API_KEY=<Token Factory key, dedicated "extractly-prod" key>
#   chmod 600 that file. The key never appears in chat, logs, or the repo.
set -euo pipefail

echo "[1/6] system deps"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv git curl

echo "[2/6] checkout"
sudo mkdir -p /opt/extractly
sudo chown ubuntu:ubuntu /opt/extractly
if [ -d /opt/extractly/.git ]; then
  cd /opt/extractly
  git fetch origin --quiet
  git reset --hard origin/main --quiet
else
  git clone --quiet https://github.com/fernandogarzaaa/extractly.git /opt/extractly
  cd /opt/extractly
fi

echo "[3/6] venv + deps"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --quiet -r requirements.txt

echo "[4/6] env file"
if [ ! -f /opt/extractly/extractly.env ]; then
  echo "MISSING /opt/extractly/extractly.env (must define NEBIUS_API_KEY). Aborting."
  exit 1
fi
chmod 600 /opt/extractly/extractly.env

echo "[5/6] systemd"
sudo cp /opt/extractly/scripts/extractly.service /etc/systemd/system/extractly.service
sudo systemctl daemon-reload
sudo systemctl enable --now extractly

echo "[6/6] auto-update cron"
(crontab -l 2>/dev/null | grep -v "extractly/scripts/auto-update.sh" || true
 echo "*/5 * * * * EXTRACTLY_REPO=/opt/extractly /opt/extractly/scripts/auto-update.sh >> /var/log/extractly-update.log 2>&1"
) | crontab -

sleep 6
curl -sf http://127.0.0.1:3200/healthz
echo ""
echo "DEPLOY OK"
