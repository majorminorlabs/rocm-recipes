#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
LOG_DIR=logs
[[ ${REHEARSAL:-0} != 1 ]] || LOG_DIR=results/rehearsal/logs
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/sync_results_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
if [[ $# -gt 1 ]]; then echo "Usage: $0 [local_destination]" >&2; exit 2; fi
LOCAL_DEST="${1:-$ROOT_DIR}"
[[ -f config.env ]] || { echo "config.env not found" >&2; exit 1; }
overrides=()
for key in REHEARSAL ATLAS_SSH_TARGET ATLAS_REMOTE_ROOT; do
  if declare -p "$key" >/dev/null 2>&1; then overrides+=("$key=${!key}"); fi
done
set -a
# shellcheck disable=SC1091
source config.env
set +a
if (( ${#overrides[@]} )); then
    for override in "${overrides[@]}"; do export "${override?}"; done
fi
SSH_USER="${SSH_USER:-root}"
REMOTE_DIR="${ATLAS_REMOTE_ROOT:-/home/atlas/rocm-recipes-006}"
TARGET="${ATLAS_SSH_TARGET:-$SSH_USER@${DROPLET_IP:-}}"
[[ $TARGET =~ ^[a-z_][a-z0-9_-]*@[A-Za-z0-9.-]+$ && $REMOTE_DIR =~ ^/home/atlas/[A-Za-z0-9_-]+$ ]] || exit 2
REMOTE_RESULTS="$REMOTE_DIR/results"
LOCAL_RESULTS="$LOCAL_DEST/results"
if [[ ${REHEARSAL:-0} == 1 ]]; then
  [[ $REMOTE_DIR == *-rehearsal ]] || exit 2
  REMOTE_RESULTS="$REMOTE_RESULTS/rehearsal"; LOCAL_RESULTS="$LOCAL_RESULTS/rehearsal"
fi
mkdir -p "$LOCAL_RESULTS"
rsync -avz --progress -e ssh "$TARGET:$REMOTE_RESULTS/" "$LOCAL_RESULTS/"
# Omit verbose/progress output so the verification emits changed names only.
DIFFERING_FILES="$(rsync -az -e ssh -n --checksum --out-format='%n' \
  "$TARGET:$REMOTE_RESULTS/" "$LOCAL_RESULTS/" \
  | awk 'length($0) && $0 !~ /\/$/')"
if [[ -n "$DIFFERING_FILES" ]]; then
  echo "Sync incomplete; files differ:"
  printf '%s\n' "$DIFFERING_FILES"
  exit 1
fi
printf -v remote_command 'find %q -type f | wc -l' "$REMOTE_RESULTS"
printf -v remote_command '%q' "$remote_command"
# shellcheck disable=SC2029 # The quoted command is intentionally built locally.
REMOTE_COUNT="$(ssh "$TARGET" "bash -o pipefail -c $remote_command")"
echo "Remote file count: $REMOTE_COUNT"
[[ "$REMOTE_COUNT" =~ ^[[:space:]]*[0-9]+[[:space:]]*$ ]] || { echo "Invalid remote file count" >&2; exit 1; }
echo "Sync verified: 0 files differ"
exit 0
