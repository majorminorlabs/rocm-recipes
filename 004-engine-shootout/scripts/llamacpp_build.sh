#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT_DIR"; mkdir -p logs
LOG="logs/llamacpp_build_$(date +%Y%m%d_%H%M%S).log"; exec > >(tee -a "$LOG") 2>&1
DRY=0; [[ ${1:-} == --dry-run ]] && { DRY=1; shift; }; [[ $# == 2 ]] || { echo 'Usage: llamacpp_build.sh [--dry-run] <checkout_dir> <commit>' >&2; exit 2; }
CHECKOUT_DIR=$1; COMMIT=$2; [[ $COMMIT =~ ^[0-9a-f]{40}$ ]] || { echo 'commit must be a full SHA' >&2; exit 2; }
if ((DRY)); then printf 'git clone https://github.com/ggml-org/llama.cpp %q (if missing); git -C %q fetch; git -C %q checkout %q; cmake build GGML_HIP=ON GPU_TARGETS=gfx942; verify HEAD; write results/env/llama_cpp_build.json\n' "$CHECKOUT_DIR" "$CHECKOUT_DIR" "$CHECKOUT_DIR" "$COMMIT"; exit 0; fi
command -v hipconfig >/dev/null || { echo 'hipconfig not found on host' >&2; exit 1; }; [[ -d $CHECKOUT_DIR/.git ]] || git clone https://github.com/ggml-org/llama.cpp "$CHECKOUT_DIR"; git -C "$CHECKOUT_DIR" fetch; git -C "$CHECKOUT_DIR" checkout "$COMMIT"; [[ $(git -C "$CHECKOUT_DIR" rev-parse HEAD) == "$COMMIT" ]] || exit 1
start=$(date -Iseconds); HIPCXX="$(hipconfig -l)/clang" HIP_PATH="$(hipconfig -R)" cmake -S "$CHECKOUT_DIR" -B "$CHECKOUT_DIR/build" -DGGML_HIP=ON -DGPU_TARGETS=gfx942 -DCMAKE_BUILD_TYPE=Release; cmake --build "$CHECKOUT_DIR/build" --config Release -j "$(getconf _NPROCESSORS_ONLN)"; mkdir -p results/env; python3 - "$COMMIT" "$start" <<'PY'
import json,sys,datetime
json.dump({'commit':sys.argv[1],'build_started_at':sys.argv[2],'built_at':datetime.datetime.now().astimezone().isoformat()},open('results/env/llama_cpp_build.json','w'),indent=2)
PY
