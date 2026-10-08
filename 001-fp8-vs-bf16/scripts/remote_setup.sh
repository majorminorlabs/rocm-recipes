#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs
LOG_FILE="logs/remote_setup_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
if [[ $# -ne 1 ]]; then echo "Usage: $0 <scratch_dir>" >&2; exit 2; fi
SCRATCH_DIR="$1"
[[ -d "$SCRATCH_DIR" ]] || { echo "Scratch directory not mounted: $SCRATCH_DIR" >&2; exit 1; }
command -v docker >/dev/null || { echo "docker not found" >&2; exit 1; }
mkdir -p "$SCRATCH_DIR/hf" results/env results/raw logs
docker info >/dev/null
echo "Remote setup ready; scratch directory: $SCRATCH_DIR"
