#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs results/env
LOG_FILE="logs/collect_env_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
if [[ $# -ne 1 ]]; then echo "Usage: $0 <snapshot_name>" >&2; exit 2; fi
SNAPSHOT="$1"
[[ "$SNAPSHOT" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "invalid snapshot name" >&2; exit 2; }
OUT="results/env/$SNAPSHOT"
mkdir -p "$OUT"
capture() {
  local destination="$1"; shift
  if ! "$@" >"$destination" 2>&1; then printf 'NOT AVAILABLE\n' >>"$destination"; fi
}
capture "$OUT/rocm-smi.txt" rocm-smi
rocminfo >"$OUT/rocminfo_full.txt" 2>&1 || { printf 'NOT AVAILABLE\n' >>"$OUT/rocminfo_full.txt"; true; }
head -100 "$OUT/rocminfo_full.txt" >"$OUT/rocminfo.txt" || printf 'NOT AVAILABLE\n' >"$OUT/rocminfo.txt"
capture "$OUT/docker-images.txt" docker images --digests
capture "$OUT/uname.txt" uname -a
capture "$OUT/df.txt" df -h
capture "$OUT/rocm-version.txt" cat /opt/rocm/.info/version
"$ROOT_DIR/scripts/rocm_version.sh" >"$OUT/rocm-version.json"
