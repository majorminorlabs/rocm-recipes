#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT_DIR"; mkdir -p logs
LOG="logs/serve_engine_$(date +%Y%m%d_%H%M%S).log"; exec > >(tee -a "$LOG") 2>&1
DRY=0; [[ ${1:-} == --dry-run ]] && { DRY=1; shift; }
[[ $# -ge 4 ]] || { echo 'Usage: serve_engine.sh [--dry-run] <vllm|sglang|llamacpp> <cfg> <hf_repo> <max_model_len> [extra args...]' >&2; exit 2; }
engine=$1 cfg=$2 repo=$3 maxlen=$4; shift 4
case $repo in M1) repo=Qwen/Qwen3-Coder-30B-A3B-Instruct;; M7) repo=Qwen/Qwen3-32B;; esac
[[ $engine =~ ^(vllm|sglang|llamacpp)$ && $cfg =~ ^[A-Za-z0-9_-]+$ && $maxlen =~ ^[0-9]+$ ]] || exit 2
if [[ -f config.env ]]; then set -a; # shellcheck disable=SC1091
 source config.env; set +a; fi
SCRATCH_DIR=${SCRATCH_DIR:-/mnt/scratch}; ENV_ARGS=(); for kv in ${SERVE_ENV:-}; do [[ $kv =~ ^[A-Z0-9_]+=[A-Za-z0-9_.-]*$ ]] || exit 2; ENV_ARGS+=(-e "$kv"); done
SERVER_ARGS=(); DOCKER=(); image=''; dtype=auto
case $engine in
vllm) image=${VLLM_IMAGE:-<VLLM_IMAGE_REQUIRED>}; SERVER_ARGS=(--host 0.0.0.0 --port 8000 --max-model-len "$maxlen" --gpu-memory-utilization 0.92 --no-enable-prefix-caching --kv-cache-dtype auto "$@"); DOCKER=(docker run -d --name engine-server --device=/dev/kfd --device=/dev/dri --group-add video --ipc=host --shm-size 16g --security-opt seccomp=unconfined -p 8000:8000 -v "$SCRATCH_DIR/hf:/root/.cache/huggingface" -v "$ROOT_DIR/results:/workspace/results" ${ENV_ARGS[@]+"${ENV_ARGS[@]}"} "$image" vllm serve "$repo" "${SERVER_ARGS[@]}");;
sglang) image=${SGLANG_IMAGE:-<SGLANG_IMAGE_REQUIRED>}; SERVER_ARGS=(--model-path "$repo" --served-model-name "$repo" --host 0.0.0.0 --port 8000 --context-length "$maxlen" --disable-radix-cache "$@"); DOCKER=(docker run -d --name engine-server --device=/dev/kfd --device=/dev/dri --group-add video --ipc=host --shm-size 16g --security-opt seccomp=unconfined --cap-add SYS_PTRACE -e HF_HUB_OFFLINE=1 -p 8000:8000 -v "$SCRATCH_DIR/hf:/root/.cache/huggingface" -v "$ROOT_DIR/results:/workspace/results" ${ENV_ARGS[@]+"${ENV_ARGS[@]}"} "$image" python3 -m sglang.launch_server "${SERVER_ARGS[@]}");;
llamacpp)
[[ $cfg == LC1 || $cfg == LC4 ]] || { echo 'llamacpp cfg must be LC1 or LC4' >&2; exit 2; }
slots=1; ctx=131072; [[ $cfg == LC4 ]] && { slots=4; ctx=139264; }; dtype=f16
shards=(); while IFS= read -r -d '' x; do shards+=("$x"); done < <(find "$SCRATCH_DIR/hf/hub/models--unsloth--Qwen3-Coder-30B-A3B-Instruct-GGUF" -name '*BF16-00001-of-*.gguf' -print0 2>/dev/null || true)
(( ${#shards[@]} == 1 )) || (( DRY )) || { echo "Expected one BF16 first shard, found ${#shards[@]}" >&2; exit 1; }
shard=${shards[0]:-<first-BF16-shard>}; SERVER_ARGS=(-m "$shard" --alias "$repo" --host 0.0.0.0 --port 8000 -ngl 999 -c "$ctx" -np "$slots" --jinja "$@");;
esac
if (( DRY )); then if [[ $engine == llamacpp ]]; then printf 'nohup %q' "$SCRATCH_DIR/llama.cpp/build/bin/llama-server"; printf ' %q' "${SERVER_ARGS[@]}"; printf ' >logs/engine_server.log 2>&1 & echo $! >logs/engine.pid\n'; else printf '%q ' "${DOCKER[@]}"; printf '\n'; fi; echo 'poll GET /v1/models up to 45 minutes'; exit 0; fi
ss -ltn | grep -q ':8000 ' && { echo 'port 8000 is taken; run stop_engine.sh first' >&2; exit 1; }
STARTED=$(date -Iseconds); SERVER_LOG="logs/engine_${engine}_${cfg}_$(date +%Y%m%d_%H%M%S).server.log"
if [[ $engine == llamacpp ]]; then nohup "$SCRATCH_DIR/llama.cpp/build/bin/llama-server" "${SERVER_ARGS[@]}" >"$SERVER_LOG" 2>&1 </dev/null & echo $! > logs/engine.pid; else docker rm -f engine-server >/dev/null 2>&1 || true; "${DOCKER[@]}" >/dev/null; nohup docker logs -f engine-server >"$SERVER_LOG" 2>&1 </dev/null & fi
python3 - "$engine" "$cfg" "$repo" "$maxlen" "$dtype" "${SERVER_ARGS[*]}" "${SERVE_ENV:-}" "$image" "$SERVER_LOG" "$STARTED" <<'PY'
import json,sys
engine,cfg,repo,n,dtype,args,env,image,log,start=sys.argv[1:]
json.dump({'engine':engine,'cfg':cfg,'hf_repo':repo,'max_model_len':int(n),'kv_cache_dtype':dtype,'server_args':(('ENV['+env+'] ') if env else '')+args,'serve_env':env,'image':image if engine!='llamacpp' else 'llama.cpp@'+(open('config.env').read().split('LLAMACPP_COMMIT=',1)[1].splitlines()[0] if 'LLAMACPP_COMMIT=' in open('config.env').read() else ''),'server_log':log,'started_at':start,'weights_precision':'bf16','gpu_memory_utilization':0.92 if engine=='vllm' else None},open('logs/current_server.json','w'),indent=2)
PY
deadline=$((SECONDS+2700)); while (( SECONDS < deadline )); do
 if [[ $engine == llamacpp ]]; then pid=$(cat logs/engine.pid); kill -0 "$pid" 2>/dev/null || { tail -n 60 "$SERVER_LOG" >&2; exit 1; }; else [[ $(docker inspect -f '{{.State.Running}}' engine-server 2>/dev/null || true) == true ]] || { docker logs --tail 60 engine-server >&2; exit 1; }; fi
 # llama-server answers some routes while still loading weights; only /health returning 200 means ready.
 probe=/v1/models; [[ $engine == llamacpp ]] && probe=/health
 curl --fail --silent "http://localhost:8000$probe" >/dev/null && exit 0 || true; sleep 10
done
echo 'Timed out waiting for /v1/models after 45 minutes' >&2; exit 1
