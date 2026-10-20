#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
STUDY_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
CONFIG_FILE=''
while (( $# )); do
    case $1 in
        --root) STUDY_DIR=$2; shift 2;;
        --config) CONFIG_FILE=$2; shift 2;;
        *) echo "PREFLIGHT FAIL: usage: preflight_006.sh [--root STUDY] [--config FILE]" >&2; exit 2;;
    esac
done
CONFIG_FILE=${CONFIG_FILE:-$STUDY_DIR/config.env}
[[ -f $CONFIG_FILE ]] || { echo "PREFLIGHT FAIL: missing config: $CONFIG_FILE" >&2; exit 1; }
# Preserve the same explicit lifecycle overrides as atlas_remote.sh.
overrides=()
for key in CREATED_AT HARD_DEADLINE SESSION_CAP_HOURS; do
    if declare -p "$key" >/dev/null 2>&1; then overrides+=("$key=${!key}"); fi
done
set -a
# shellcheck source=/dev/null
source "$CONFIG_FILE"
set +a
for override in "${overrides[@]+"${overrides[@]}"}"; do export "${override?}"; done
exec python3 "$SCRIPT_DIR/preflight_006.py" --root "$STUDY_DIR" --atlas "${ATLAS_SOURCE:-../atlas}"
