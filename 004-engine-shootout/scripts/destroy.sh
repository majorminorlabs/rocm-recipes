#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs
LOG_FILE="logs/destroy_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then DRY_RUN=1; shift; fi
if [[ $# -ne 0 ]]; then echo "Usage: $0 [--dry-run]" >&2; exit 2; fi
[[ -f config.env ]] || { echo "config.env not found" >&2; exit 1; }
set -a
# shellcheck disable=SC1091
source config.env
set +a
if [[ -z "${DROPLET_ID:-}" ]]; then echo "DROPLET_ID is empty; refusing to delete" >&2; exit 1; fi
COMMAND=(doctl compute droplet delete "$DROPLET_ID" --force)
if [[ $DRY_RUN -eq 1 ]]; then printf '%q ' "${COMMAND[@]}"; printf '\n'; exit 0; fi
for ((attempt = 1; attempt <= 3; attempt++)); do
  echo "Delete attempt $attempt/3 for DROPLET_ID=$DROPLET_ID"
  "${COMMAND[@]}" || true
  if ids="$(doctl compute droplet list --format ID --no-header)"; then
    if ! awk -v id="$DROPLET_ID" '$1 == id {found=1} END {exit !found}' <<<"$ids"; then
      echo "DROPLET_ID=$DROPLET_ID confirmed absent"
      exit 0
    fi
  fi
done
echo "Failed to confirm deletion of DROPLET_ID=$DROPLET_ID" >&2
exit 1
