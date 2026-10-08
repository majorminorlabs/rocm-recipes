#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs
LOG_FILE="logs/bench_serve_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
usage() { echo "Usage: $0 [--dry-run] [--no-warmup] <model> <concurrency> <run_id> <precision>"; }
DRY_RUN=0
WARMUP_ENABLED=1
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --no-warmup) WARMUP_ENABLED=0 ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done
if [[ $# -ne 4 ]]; then usage >&2; exit 2; fi
MODEL="$1"; CONCURRENCY="$2"; RUN_ID="$3"; PRECISION="$4"
case "$PRECISION" in bf16|fp8|mxfp4|q4_k_m) ;; *) echo "invalid precision" >&2; exit 2 ;; esac
if [[ -f config.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source config.env
  set +a
fi
SCRATCH_DIR="${SCRATCH_DIR:-/mnt/scratch}"
[[ "$CONCURRENCY" =~ ^[1-9][0-9]*$ ]] || { echo "concurrency must be a positive integer" >&2; exit 2; }
[[ "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "invalid run_id" >&2; exit 2; }
NUM_PROMPTS=$((CONCURRENCY * 8)); (( NUM_PROMPTS < 32 )) && NUM_PROMPTS=32
RESULT_DIR="results/raw/R2/$RUN_ID"
CONTAINER_NAME="vllm-server"
BENCH_BASE=(vllm bench serve --model "$MODEL" --backend vllm --dataset-name random --random-input-len 1024 --random-output-len 256)
WARMUP=("${BENCH_BASE[@]}" --num-prompts 16 --max-concurrency 8)
BENCH=("${BENCH_BASE[@]}" --num-prompts "$NUM_PROMPTS" --max-concurrency "$CONCURRENCY" --save-result --result-dir "/workspace/$RESULT_DIR")
if [[ $DRY_RUN -eq 1 ]]; then
  if [[ $WARMUP_ENABLED -eq 1 ]]; then
    printf 'docker exec %q' "$CONTAINER_NAME"; printf ' %q' "${WARMUP[@]}"; printf '\n'
  fi
  printf 'docker exec %q' "$CONTAINER_NAME"; printf ' %q' "${BENCH[@]}"; printf '\n'
  printf 'mkdir -p %q\n' "$RESULT_DIR"
  exit 0
fi
mkdir -p "$RESULT_DIR"
STARTED_AT="$(date -Iseconds)"
EXIT_CODE=0
WARMUP_FAILED=0
if docker exec "$CONTAINER_NAME" vllm bench serve --help >"$LOG_FILE.help" 2>&1; then
  if [[ $WARMUP_ENABLED -eq 1 ]]; then
    docker exec "$CONTAINER_NAME" "${WARMUP[@]}" >"$LOG_FILE.warmup" 2>&1 || EXIT_CODE=$?
  fi
  if (( EXIT_CODE == 0 )); then
    set +e
    docker exec "$CONTAINER_NAME" "${BENCH[@]}" 2>&1 | tee "$LOG_FILE.output"
    EXIT_CODE=${PIPESTATUS[0]}
    set -e
  else
    WARMUP_FAILED=1
    cp "$LOG_FILE.warmup" "$LOG_FILE.output"
    cat "$LOG_FILE.output"
  fi
else
  EXIT_CODE=$?
  cp "$LOG_FILE.help" "$LOG_FILE.output"
fi
FINISHED_AT="$(date -Iseconds)"
ENGINE_VERSION="$(docker exec "$CONTAINER_NAME" python -c 'import vllm; print(vllm.__version__)' 2>/dev/null || true)"
IMAGE_DIGEST="$(docker inspect --format '{{index .RepoDigests 0}}' "${VLLM_IMAGE:-}" 2>/dev/null || true)"
ROCM_JSON="$("$ROOT_DIR/scripts/rocm_version.sh")"
MODEL_REVISION="$(cat "$SCRATCH_DIR/hf/hub/models--${MODEL//\//--}/refs/main" 2>/dev/null || true)"
ERROR=""
if (( EXIT_CODE != 0 )); then ERROR="$(tail -20 "$LOG_FILE.output")"; fi
if [[ $WARMUP_FAILED -eq 1 ]]; then ERROR="warmup failed: $ERROR"; fi
export RUN_ID MODEL PRECISION CONCURRENCY NUM_PROMPTS WARMUP_ENABLED STARTED_AT FINISHED_AT ENGINE_VERSION IMAGE_DIGEST ROCM_JSON MODEL_REVISION ERROR EXIT_CODE
python3 - "$RESULT_DIR/meta.json" <<'PY'
import json, os, sys
e = os.environ
meta = {key.lower(): e[key] for key in (
    "RUN_ID", "MODEL", "MODEL_REVISION", "PRECISION", "ENGINE_VERSION",
    "IMAGE_DIGEST", "STARTED_AT", "FINISHED_AT", "ERROR")}
rocm = json.loads(e["ROCM_JSON"])
meta.update(rocm=rocm, rocm_version=rocm["host_rocm"] or rocm["container_hip"])
meta.update(recipe="R2", engine="vllm", concurrency=int(e["CONCURRENCY"]),
            input_len=1024, output_len=256, num_prompts=int(e["NUM_PROMPTS"]),
            status="ok" if e["EXIT_CODE"] == "0" else "failed",
            warmup=e["WARMUP_ENABLED"] == "1")
with open(sys.argv[1], "w") as f:
    json.dump(meta, f, indent=2)
    f.write("\n")
PY
exit "$EXIT_CODE"
