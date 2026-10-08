#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs
LOG_FILE="logs/llamacpp_bench_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
if [[ $# -ne 2 ]]; then echo "Usage: $0 <gguf_path> <run_id>" >&2; exit 2; fi
GGUF_PATH="$1"; RUN_ID="$2"
[[ -f "$GGUF_PATH" ]] || { echo "GGUF file not found: $GGUF_PATH" >&2; exit 1; }
[[ "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "invalid run_id" >&2; exit 2; }
if [[ -f config.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source config.env
  set +a
fi
SCRATCH_DIR="${SCRATCH_DIR:-/mnt/scratch}"
LLAMA_BENCH="${LLAMA_BENCH:-$SCRATCH_DIR/llama.cpp/build/bin/llama-bench}"
RESULT_DIR="results/raw/R4/$RUN_ID"
mkdir -p "$RESULT_DIR"
STARTED_AT="$(date -Iseconds)"
EXIT_CODE=0
"$LLAMA_BENCH" -m "$GGUF_PATH" -ngl 999 -p 512 -n 128 -r 3 -o json >"$RESULT_DIR/llama_bench.json" 2>"$LOG_FILE.output" || EXIT_CODE=$?
cat "$LOG_FILE.output"
FINISHED_AT="$(date -Iseconds)"
ENGINE_VERSION="$(cat results/raw/R4/llama_cpp_commit.txt 2>/dev/null || true)"
MODEL_REVISION="$(cat "$SCRATCH_DIR/hf/hub/models--unsloth--Qwen3-Coder-30B-A3B-Instruct-GGUF/refs/main" 2>/dev/null || true)"
ROCM_JSON="$("$ROOT_DIR/scripts/rocm_version.sh")"
ERROR=""
if (( EXIT_CODE != 0 )); then ERROR="$(tail -20 "$LOG_FILE.output")"; fi
export RUN_ID GGUF_PATH STARTED_AT FINISHED_AT ENGINE_VERSION MODEL_REVISION ROCM_JSON ERROR EXIT_CODE
python3 - "$RESULT_DIR/meta.json" <<'PY'
import json, os, sys
e = os.environ
meta = {key.lower(): e[key] for key in (
    "RUN_ID", "MODEL_REVISION", "ENGINE_VERSION",
    "STARTED_AT", "FINISHED_AT", "ERROR")}
rocm = json.loads(e["ROCM_JSON"])
meta.update(rocm=rocm, rocm_version=rocm["host_rocm"] or rocm["container_hip"])
meta.update(recipe="R4", model="unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF",
            precision="q4_k_m", engine="llama.cpp", image_digest="", concurrency=1,
            input_len=512, output_len=128, num_prompts=3, gguf_path=e["GGUF_PATH"],
            status="ok" if e["EXIT_CODE"] == "0" else "failed")
with open(sys.argv[1], "w") as f:
    json.dump(meta, f, indent=2)
    f.write("\n")
PY
exit "$EXIT_CODE"
