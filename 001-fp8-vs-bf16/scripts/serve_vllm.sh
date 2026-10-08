#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs
LOG_FILE="logs/serve_vllm_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

usage() { echo "Usage: $0 [--dry-run] <hf_repo> [extra vLLM args...]"; }
DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then DRY_RUN=1; shift; fi
if [[ $# -lt 1 ]]; then usage >&2; exit 2; fi
HF_REPO="$1"; shift
if [[ -f config.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source config.env
  set +a
fi
SCRATCH_DIR="${SCRATCH_DIR:-/mnt/scratch}"
VLLM_IMAGE="${VLLM_IMAGE:-}"
CONTAINER_NAME="vllm-server"
DOCKER_ARGS=(docker run -d --name "$CONTAINER_NAME" --device=/dev/kfd --device=/dev/dri --group-add video --ipc=host --shm-size 16g --security-opt seccomp=unconfined -p 8000:8000 -v "$SCRATCH_DIR/hf:/root/.cache/huggingface" -v "$ROOT_DIR/results:/workspace/results")
if [[ -n "${HF_TOKEN:-}" ]]; then DOCKER_ARGS+=(-e HF_TOKEN); fi
DOCKER_ARGS+=("${VLLM_IMAGE:-<VLLM_IMAGE_REQUIRED>}" vllm serve "$HF_REPO" --host 0.0.0.0 --port 8000 "$@")
if [[ $DRY_RUN -eq 1 ]]; then
  printf ' %q' "${DOCKER_ARGS[@]}"; printf '\n'
  printf 'curl --fail --silent http://localhost:8000/v1/models\n'
  exit 0
fi
if [[ -z "$VLLM_IMAGE" ]]; then echo "VLLM_IMAGE must be set in config.env" >&2; exit 1; fi
mkdir -p "$SCRATCH_DIR/hf"
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
"${DOCKER_ARGS[@]}"
nohup docker logs -f "$CONTAINER_NAME" </dev/null >"$LOG_FILE.server" 2>&1 &
SERVER_LOG_PID=$!
printf '%s\n' "$SERVER_LOG_PID" > logs/vllm_server_log.pid
deadline=$((SECONDS + 1800))
while true; do
  if [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || true)" != "true" ]]; then
    echo "vLLM container is not running" >&2
    docker logs --tail 40 "$CONTAINER_NAME" >&2 || true
    exit 1
  fi
  if curl --fail --silent http://localhost:8000/v1/models >/dev/null; then break; fi
  if (( SECONDS >= deadline )); then echo "Timed out waiting for vLLM /v1/models after 30 minutes" >&2; exit 1; fi
  sleep 10
done
echo "vLLM server is ready; log: $LOG_FILE.server"
