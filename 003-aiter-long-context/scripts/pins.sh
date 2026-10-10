#!/usr/bin/env bash
# Best-effort provenance pins for result metadata. Always print one JSON object.
set -u
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ROOT_DIR/config.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/config.env"
  set +a
fi
MODEL=${1:-}
SCRATCH_DIR=${SCRATCH_DIR:-/mnt/scratch}
ENGINE_VERSION="$(docker exec vllm-server python -c 'import vllm; print(vllm.__version__)' 2>/dev/null || true)"
IMAGE_DIGEST="$(docker inspect --format '{{index .RepoDigests 0}}' "${VLLM_IMAGE:-}" 2>/dev/null || true)"
ROCM_JSON="$("$ROOT_DIR/scripts/rocm_version.sh")"
MODEL_REVISION="$(cat "$SCRATCH_DIR/hf/hub/models--${MODEL//\//--}/refs/main" 2>/dev/null || true)"
export ENGINE_VERSION IMAGE_DIGEST ROCM_JSON MODEL_REVISION
python3 - <<'PY'
import json, os
try:
    rocm = json.loads(os.environ['ROCM_JSON'])
except (ValueError, KeyError):
    rocm = {}
print(json.dumps({
    'model_revision': os.environ['MODEL_REVISION'],
    'engine_version': os.environ['ENGINE_VERSION'],
    'image_digest': os.environ['IMAGE_DIGEST'],
    'rocm_version': rocm.get('host_rocm') or rocm.get('container_hip') or '',
}))
PY
