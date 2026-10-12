#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT_DIR"; mkdir -p logs
LOG="logs/stop_engine_$(date +%Y%m%d_%H%M%S).log"; exec > >(tee -a "$LOG") 2>&1
DRY=0; [[ ${1:-} == --dry-run ]] && DRY=1
if (( DRY )); then echo 'docker rm -f engine-server (ignore missing); kill logs/engine.pid; wait up to 30s; verify port 8000 free'; exit 0; fi
docker rm -f engine-server >/dev/null 2>&1 || true
if [[ -f logs/engine.pid ]]; then pid=$(cat logs/engine.pid); kill "$pid" 2>/dev/null || true; for _ in {1..30}; do kill -0 "$pid" 2>/dev/null || break; sleep 1; done; kill -0 "$pid" 2>/dev/null && { echo "pid $pid did not exit" >&2; exit 1; }; rm -f logs/engine.pid; fi
if ss -ltn | grep -q ':8000 '; then echo 'port 8000 still taken' >&2; exit 1; fi
