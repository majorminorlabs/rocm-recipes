#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs
LOG_FILE="logs/push_repo_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then DRY_RUN=1; shift; fi
if [[ $# -ne 0 ]]; then echo "Usage: $0 [--dry-run]" >&2; exit 2; fi
[[ -f config.env ]] || { echo "config.env not found" >&2; exit 1; }
set -a
# shellcheck disable=SC1091
source config.env
set +a
[[ -n "${DROPLET_IP:-}" ]] || { echo "DROPLET_IP is empty" >&2; exit 1; }
SSH_USER="${SSH_USER:-root}"
REMOTE_REPO_DIR="${REMOTE_REPO_DIR:-/root/rocm-recipes}"
printf -v remote_root '%q' "$REMOTE_REPO_DIR"
printf -v remote_results '%q' "$REMOTE_REPO_DIR/results"
printf -v remote_logs '%q' "$REMOTE_REPO_DIR/logs"
MKDIR=(ssh "$SSH_USER@$DROPLET_IP" "mkdir -p $remote_root $remote_results $remote_logs")
# No trailing slash on scripts: preserve the scripts/ directory on the remote.
COPY=(rsync -az -e ssh --exclude=.git --exclude=results --exclude='*token*' --exclude='*.key' scripts config.env "$SSH_USER@$DROPLET_IP:$REMOTE_REPO_DIR/")
if [[ $DRY_RUN -eq 1 ]]; then
  printf '%q ' "${MKDIR[@]}"; printf '\n'
  printf '%q ' "${COPY[@]}"; printf '\n'
  exit 0
fi
"${MKDIR[@]}"
"${COPY[@]}"
