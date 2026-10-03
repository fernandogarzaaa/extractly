#!/usr/bin/env bash
# auto-update.sh: pull-based auto-deploy for the Extractly box.
# Mirrors the signal-lab pattern. Runs from cron every 5 minutes.
# The box is a PURE DEPLOY TARGET: `git reset --hard` on change.
# Never keep local edits on the box; commit them instead.
set -euo pipefail

REPO="${EXTRACTLY_REPO:?set EXTRACTLY_REPO to the repo checkout path}"
SERVICE="${EXTRACTLY_SERVICE:-extractly}"
PORT="${EXTRACTLY_PORT:-3200}"
BRANCH="${EXTRACTLY_BRANCH:-main}"
LOCK="/tmp/extractly-auto-update.lock"

log() { echo "$(date -u +%FT%TZ) [auto-update] $*"; }

exec 9>"$LOCK"
if ! flock -n 9; then
  log "another run in progress, skipping"
  exit 0
fi

cd "$REPO"

if ! git fetch origin "$BRANCH" --quiet 2>/dev/null; then
  exit 0
fi

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"
if [ "$LOCAL" = "$REMOTE" ]; then
  exit 0
fi

log "updating $LOCAL -> $REMOTE"
git reset --hard "origin/$BRANCH" --quiet

if git diff --name-only "$LOCAL" "$REMOTE" -- requirements.txt | grep -q .; then
  log "requirements changed, reinstalling"
  "$REPO/.venv/bin/pip" install -r "$REPO/requirements.txt" --quiet
fi

sudo systemctl restart "$SERVICE"
sleep 4
if curl -sf "http://127.0.0.1:$PORT/healthz" >/dev/null; then
  log "healthy after update"
else
  log "HEALTH CHECK FAILED after update"
  exit 1
fi
