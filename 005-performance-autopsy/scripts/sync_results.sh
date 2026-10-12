#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs
LOG_FILE="logs/sync_results_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
if [[ $# -gt 1 ]]; then echo "Usage: $0 [local_destination]" >&2; exit 2; fi
LOCAL_DEST="${1:-$ROOT_DIR}"
[[ -f config.env ]] || { echo "config.env not found" >&2; exit 1; }
set -a
# shellcheck disable=SC1091
source config.env
set +a
[[ -n "${DROPLET_IP:-}" ]] || { echo "DROPLET_IP is empty" >&2; exit 1; }
SSH_USER="${SSH_USER:-root}"
REMOTE_DIR="${REMOTE_REPO_DIR:-/root/rocm-recipes}"
mkdir -p "$LOCAL_DEST"
rsync -avz --progress -e ssh "$SSH_USER@$DROPLET_IP:$REMOTE_DIR/results/" "$LOCAL_DEST/results/"
# Omit verbose/progress output so the verification emits changed names only.
DIFFERING_FILES="$(rsync -az -e ssh -n --checksum --out-format='%n' \
  "$SSH_USER@$DROPLET_IP:$REMOTE_DIR/results/" "$LOCAL_DEST/results/" \
  | awk 'length($0) && $0 !~ /\/$/')"
if [[ -n "$DIFFERING_FILES" ]]; then
  echo "Sync incomplete; files differ:"
  printf '%s\n' "$DIFFERING_FILES"
  exit 1
fi
printf -v remote_command 'find %q -type f | wc -l' "$REMOTE_DIR/results"
printf -v remote_command '%q' "$remote_command"
# shellcheck disable=SC2029 # The quoted command is intentionally built locally.
REMOTE_COUNT="$(ssh "$SSH_USER@$DROPLET_IP" "bash -o pipefail -c $remote_command")"
echo "Remote file count: $REMOTE_COUNT"
[[ "$REMOTE_COUNT" =~ ^[[:space:]]*[0-9]+[[:space:]]*$ ]] || { echo "Invalid remote file count" >&2; exit 1; }
echo "Sync verified: 0 files differ"
exit 0
