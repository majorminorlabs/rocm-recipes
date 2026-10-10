#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT_DIR"; mkdir -p logs
LOG="logs/serve_long_$(date +%Y%m%d_%H%M%S).log"; exec > >(tee -a "$LOG") 2>&1
DRY=0; [[ "${1:-}" == --dry-run ]] && { DRY=1; shift; }
[[ $# -ge 4 ]] || { echo 'Usage: [SERVE_ENV="NAME=VAL ..."] serve_long.sh [--dry-run] <hf_repo> <max_model_len> <kv_cache_dtype> <gpu_mem_util> [extra args...]' >&2; exit 2; }
repo=$1; maxlen=$2; dtype=$3; util=$4; shift 4
[[ $maxlen =~ ^[0-9]+$ && $util =~ ^0?\.[0-9]+$ ]] || { echo 'invalid max length or utilization' >&2; exit 2; }
[[ $dtype == auto || $dtype == fp8 ]] || { echo 'kv dtype must be auto or fp8' >&2; exit 2; }
# SERVE_ENV: space-separated NAME=VALUE pairs passed into the container (e.g. AITER switches).
ENV_ARGS=()
for kv in ${SERVE_ENV:-}; do
  [[ $kv =~ ^[A-Z0-9_]+=[A-Za-z0-9_.-]*$ ]] || { echo "invalid SERVE_ENV entry: $kv" >&2; exit 2; }
  ENV_ARGS+=(-e "$kv")
done
if [[ -f config.env ]]; then set -a; # shellcheck disable=SC1091
 source config.env; set +a; fi
SCRATCH_DIR=${SCRATCH_DIR:-/mnt/scratch}; VLLM_IMAGE=${VLLM_IMAGE:-}; SERVER_ARGS=(--host 0.0.0.0 --port 8000 --max-model-len "$maxlen" --gpu-memory-utilization "$util" --no-enable-prefix-caching --kv-cache-dtype "$dtype" "$@")
DOCKER=(docker run -d --name vllm-server --device=/dev/kfd --device=/dev/dri --group-add video --ipc=host --shm-size 16g --security-opt seccomp=unconfined -p 8000:8000 -v "$SCRATCH_DIR/hf:/root/.cache/huggingface" -v "$ROOT_DIR/results:/workspace/results" ${ENV_ARGS[@]+"${ENV_ARGS[@]}"} "${VLLM_IMAGE:-<VLLM_IMAGE_REQUIRED>}" vllm serve "$repo" "${SERVER_ARGS[@]}")
if (( DRY )); then printf '%q ' "${DOCKER[@]}"; printf '\n'; printf '%s\n' 'poll docker inspect and curl /v1/models for up to 45 minutes'; exit 0; fi
[[ -n $VLLM_IMAGE ]] || { echo 'VLLM_IMAGE must be set' >&2; exit 1; }
STARTED=$(date -Iseconds); docker rm -f vllm-server >/dev/null 2>&1 || true; "${DOCKER[@]}" >/dev/null
SERVER_LOG="logs/serve_long_${repo//\//_}_$(date +%Y%m%d_%H%M%S).server.log"; nohup docker logs -f vllm-server >"$SERVER_LOG" 2>&1 </dev/null &
# server_args records the env too, so every meta.json shows which kernels were requested.
RECORDED_ARGS="${SERVER_ARGS[*]}"; [[ -n ${SERVE_ENV:-} ]] && RECORDED_ARGS="ENV[${SERVE_ENV}] ${RECORDED_ARGS}"
python3 - "$repo" "$maxlen" "$dtype" "$util" "$RECORDED_ARGS" "$SERVER_LOG" "$STARTED" "${SERVE_ENV:-}" <<'PY'
import json,sys
keys=['hf_repo','max_model_len','kv_cache_dtype','gpu_memory_utilization','server_args','server_log','started_at','serve_env']; vals=sys.argv[1:]
cfg=dict(zip(keys,vals)); cfg['weights_precision']='mxfp4' if cfg['hf_repo']=='openai/gpt-oss-120b' else 'bf16'
with open('logs/current_server.json','w') as f: json.dump(cfg,f,indent=2); f.write('\n')
PY
deadline=$((SECONDS+2700)); while (( SECONDS < deadline )); do
 if [[ "$(docker inspect -f '{{.State.Running}}' vllm-server 2>/dev/null || true)" != true ]]; then docker logs --tail 60 vllm-server >&2; exit 1; fi
 curl --fail --silent http://localhost:8000/v1/models >/dev/null && exit 0 || true; sleep 10
done
echo 'Timed out waiting for vLLM /v1/models after 45 minutes' >&2; exit 1
