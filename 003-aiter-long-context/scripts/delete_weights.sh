#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs
LOG_FILE="logs/delete_weights_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
if [[ $# -ne 1 ]]; then echo "Usage: $0 <hf_repo>" >&2; exit 2; fi
HF_REPO="$1"
if [[ "$HF_REPO" == *..* || ! "$HF_REPO" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]]; then
  echo "Refusing invalid HF repo: $HF_REPO" >&2; exit 2
fi
if [[ -f config.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source config.env
  set +a
fi
SCRATCH_DIR="${SCRATCH_DIR:-/mnt/scratch}"
TARGET="$(python3 - "$SCRATCH_DIR" "models--${HF_REPO//\//--}" <<'PY'
from pathlib import Path
import sys
hub = Path(sys.argv[1]).resolve() / "hf" / "hub"
candidate = hub / sys.argv[2]
target = candidate.resolve()
if candidate.is_symlink() or target.parent != hub or target == hub:
    sys.exit("Refusing cache path outside the selected model directory")
print(target)
PY
)"
echo "Deleting only $TARGET"
rm -rf -- "$TARGET"
df -h "$SCRATCH_DIR"
