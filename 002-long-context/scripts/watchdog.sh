#!/usr/bin/env bash
set -Euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 1
mkdir -p logs
LOG_FILE="logs/watchdog.log"
DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then DRY_RUN=1; shift; fi
if [[ $# -ne 0 ]]; then echo "Usage: $0 [--dry-run]" >&2; exit 2; fi
[[ -f config.env ]] || { echo "config.env not found"; exit 1; }
set -a
# shellcheck disable=SC1091
source config.env
set +a
[[ -n "${DROPLET_ID:-}" ]] || { echo "DROPLET_ID is empty"; exit 1; }
[[ -n "${HARD_DEADLINE:-}" ]] || { echo "HARD_DEADLINE is empty"; exit 1; }
[[ "$HARD_DEADLINE" =~ (Z|[+-][0-9]{2}:[0-9]{2})$ ]] || { echo "HARD_DEADLINE must include a UTC offset" >&2; exit 1; }
deadline_epoch="$(python3 -c 'import datetime,sys; d=datetime.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00")); print(int(d.timestamp()))' "$HARD_DEADLINE")" || exit 1
now_epoch="$(date +%s)"
delay=$((deadline_epoch - now_epoch))
COMMAND=(doctl compute droplet delete "$DROPLET_ID" --force)
if [[ $DRY_RUN -eq 1 ]]; then
  printf 'deadline_epoch=%s\nseconds_remaining=%s\n' "$deadline_epoch" "$delay"
  printf '%q ' "${COMMAND[@]}"; printf '\n'
  exit 0
fi
RETRY_WAIT="${WATCHDOG_RETRY_WAIT_SECONDS:-30}"
[[ "$RETRY_WAIT" =~ ^[0-9]+$ ]] || { echo "invalid WATCHDOG_RETRY_WAIT_SECONDS" >&2; exit 2; }
exec >>"$LOG_FILE" 2>&1
while (( $(date +%s) < deadline_epoch )); do sleep 60; done
for ((attempt = 1; attempt <= 10; attempt++)); do
  printf '%s attempt %s/10 deleting DROPLET_ID=%s\n' "$(date -Iseconds)" "$attempt" "$DROPLET_ID"
  "${COMMAND[@]}"
  if ids="$(doctl compute droplet list --format ID --no-header)"; then
    if ! awk -v id="$DROPLET_ID" '$1 == id {found=1} END {exit !found}' <<<"$ids"; then
      printf '%s DROPLET_ID=%s confirmed absent\n' "$(date -Iseconds)" "$DROPLET_ID"
      exit 0
    fi
  fi
  if (( attempt < 10 )); then sleep "$RETRY_WAIT"; fi
done
printf '%s WATCHDOG FAILED DROPLET_ID=%s\n' "$(date -Iseconds)" "$DROPLET_ID"
osascript -e 'display notification "Droplet NOT destroyed" with title "ROCm watchdog"'
exit 1
