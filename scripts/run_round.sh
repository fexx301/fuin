#!/usr/bin/env bash
# Run every model of a sealed round to completion, patiently: on any failure (network loss, timeouts, a
# refused preflight) wait until NEAR AI is reachable again, then resume. Rows already saved are never redone.
# Usage: scripts/run_round.sh ROUND_ID PARALLEL MODEL [MODEL ...]      (keeps the machine awake while it runs)
set -u
cd "$(dirname "$0")/.."
id=$1; par=$2; shift 2
backup() { [ -d ~/Documents/fuin-private-backup ] && mkdir -p ~/Documents/fuin-private-backup/"$id" && cp "private/$id/state.json" ~/Documents/fuin-private-backup/"$id"/state.json; }
online() { curl -s -o /dev/null -m 15 https://cloud-api.near.ai/v1/model/list; }
for m in "$@"; do
  echo "== $m"
  for attempt in $(seq 1 300); do
    uv run --env-file .env fuin run --id "$id" --model "$m" --parallel "$par" && { backup; break; }
    backup
    echo "attempt $attempt failed at $(date -u +%H:%MZ); waiting for the network"
    until online; do sleep 30; done
    sleep 20
  done
done
uv run fuin status --id "$id"
