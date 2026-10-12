#!/usr/bin/env bash
# Best effort engine and model provenance; outputs one JSON object.
set -u
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; [[ -f $ROOT_DIR/config.env ]] && { set -a; # shellcheck source=/dev/null
 source "$ROOT_DIR/config.env"; set +a; }
SCRATCH_DIR=${SCRATCH_DIR:-/mnt/scratch}; MODEL=${1:-}; engine=$(python3 -c 'import json;print(json.load(open("logs/current_server.json"))["engine"])' 2>/dev/null || echo vllm)
case $engine in
vllm) SERVER_CONTAINER="engine-server"; ver=$(docker exec "$SERVER_CONTAINER" python3 -c 'import vllm;print(vllm.__version__)' 2>/dev/null || true); image=${VLLM_IMAGE:-};;
sglang) SERVER_CONTAINER="engine-server"; ver=$(docker exec "$SERVER_CONTAINER" python3 -c 'import sglang;print(sglang.__version__)' 2>/dev/null || true); image=${SGLANG_IMAGE:-};;
*) ver=$(git -C "$SCRATCH_DIR/llama.cpp" rev-parse HEAD 2>/dev/null || true); image=;; esac
# Prefer the image the server was actually started with (covers SGLANG_IMAGE_FALLBACK).
started=$(python3 -c 'import json;print(json.load(open("logs/current_server.json")).get("image") or "")' 2>/dev/null || true)
[[ $engine != llamacpp && -n $started ]] && image=$started
if [[ -n $image ]]; then digest=$(docker image inspect --format '{{index .RepoDigests 0}}' "$image" 2>/dev/null || echo "$image"); else digest=''; fi
aiter=''; [[ -n ${SERVER_CONTAINER:-} ]] && aiter=$(docker exec "$SERVER_CONTAINER" python3 -c 'import aiter,importlib.metadata as m;print(m.version("aiter"))' 2>/dev/null || true)
revision=$(cat "$SCRATCH_DIR/hf/hub/models--${MODEL//\//--}/refs/main" 2>/dev/null || true); rocm=$("$ROOT_DIR/scripts/rocm_version.sh" 2>/dev/null || echo '{}')
export ver digest revision aiter rocm
python3 - <<'PY'
import json,os
try:r=json.loads(os.environ['rocm'])
except:r={}
print(json.dumps({'model_revision':os.environ['revision'],'engine_version':os.environ['ver'],'image_digest':os.environ['digest'],'rocm_version':r.get('host_rocm') or r.get('container_hip') or '', 'aiter_version':os.environ['aiter']}))
PY
