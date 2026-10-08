#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs
LOG_FILE="logs/stop_vllm_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
if [[ $# -ne 0 ]]; then echo "Usage: $0" >&2; exit 2; fi
docker rm -f vllm-server
if [[ -f logs/vllm_server_log.pid ]]; then
  read -r log_pid < logs/vllm_server_log.pid
  kill "$log_pid" 2>/dev/null || true
  rm -f logs/vllm_server_log.pid
fi
