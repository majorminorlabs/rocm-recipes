#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT_DIR"; mkdir -p logs
LOG="logs/bench_engine_$(date +%Y%m%d_%H%M%S).log"; exec > >(tee -a "$LOG") 2>&1
DRY=0; [[ ${1:-} == --dry-run ]] && { DRY=1; shift; }; [[ $# == 6 ]] || { echo 'Usage: bench_engine.sh [--dry-run] <run_id> <recipe> <input_len> <output_len> <concurrency> <num_prompts>' >&2; exit 2; }
id=$1; recipe=$2; ilen=$3; olen=$4; conc=$5; prompts=$6; [[ $id =~ ^[A-Za-z0-9._-]+$ && $recipe =~ ^L[12]$ && $ilen =~ ^[0-9]+$ && $olen =~ ^[0-9]+$ && $conc =~ ^[1-9][0-9]*$ && $prompts =~ ^[1-9][0-9]*$ ]] || exit 2
seed=$(python3 - "$id" <<'PY'
import re,sys,zlib
key=re.sub(r'-(VD|VT|SD|SX|LC1|LC4)(?=-|$)','',sys.argv[1]); print(zlib.crc32(key.encode())%(2**31))
PY
)
out="results/raw/$recipe/$id"; cfg=logs/current_server.json
if [[ -f $cfg ]]; then readarray -t vals < <(python3 -c 'import json;d=json.load(open("logs/current_server.json"));print(d["hf_repo"]);print(d["engine"]);print(d["cfg"]);print(d["max_model_len"])'); MODEL=${vals[0]}; config=${vals[2]}; maxlen=${vals[3]}; else (( DRY )) || { echo 'No current server config' >&2; exit 1; }; MODEL='<hf_repo>'; config='<cfg>'; maxlen=999999; fi
if ((DRY)); then echo "seed=$seed"; # shellcheck disable=SC2016
 printf 'docker run --rm --network host -e HF_HUB_OFFLINE=1 -v $SCRATCH_DIR/hf:/root/.cache/huggingface -v $ROOT_DIR/results:/workspace/results $VLLM_IMAGE vllm bench serve --backend openai --base-url http://localhost:8000 --endpoint /v1/completions --model %q --dataset-name random --random-input-len %q --random-output-len %q --random-range-ratio 0 --ignore-eos --max-concurrency %q --num-prompts %q --seed %q --save-result --result-dir /workspace/%q\n' "$MODEL" "$ilen" "$olen" "$conc" "$prompts" "$seed" "$out"; exit 0; fi
(( ilen+olen <= maxlen )) || { echo 'input_len + output_len exceeds max_model_len' >&2; exit 1; }; [[ $config != LC4 ]] || (( ilen+olen <= 34816 )) || { echo 'LC4 per-slot context exceeded' >&2; exit 1; }
if [[ -f config.env ]]; then set -a; # shellcheck source=/dev/null
 source config.env; set +a; fi
SCRATCH_DIR=${SCRATCH_DIR:-/mnt/scratch}; VLLM_IMAGE=${VLLM_IMAGE:-}
[[ -n $VLLM_IMAGE ]] || { echo 'VLLM_IMAGE must be set' >&2; exit 1; }
mkdir -p "$out"; STARTED=$(date -Iseconds); OUTPUT="$out/bench_stdout.log"; EXIT_CODE=0; STAGE=''
# CLIENT_GPU=1 adds the GPU device flags to the client container (P1.5 decision table only).
DEV=(); [[ ${CLIENT_GPU:-0} == 1 ]] && DEV=(--device=/dev/kfd --device=/dev/dri --group-add video)
client=(docker run --rm --network host ${DEV[@]+"${DEV[@]}"} -e HF_HUB_OFFLINE=1 -v "$SCRATCH_DIR/hf:/root/.cache/huggingface" -v "$ROOT_DIR/results:/workspace/results" "$VLLM_IMAGE" vllm bench serve)
warm=(--backend openai --base-url http://localhost:8000 --endpoint /v1/completions --model "$MODEL" --dataset-name random --random-input-len 1024 --random-output-len 64 --random-range-ratio 0 --ignore-eos --max-concurrency 1 --num-prompts 2 --seed 1)
run=(--backend openai --base-url http://localhost:8000 --endpoint /v1/completions --model "$MODEL" --dataset-name random --random-input-len "$ilen" --random-output-len "$olen" --random-range-ratio 0 --ignore-eos --max-concurrency "$conc" --num-prompts "$prompts" --seed "$seed" --save-result --result-dir "/workspace/$out")
if ! "${client[@]}" --help=all >"$LOG.help" 2>&1; then EXIT_CODE=1; STAGE='client help failed'; cp "$LOG.help" "$OUTPUT"; fi
if (( EXIT_CODE == 0 )); then
  for flag in --backend --base-url --endpoint --model --dataset-name --random-input-len --random-output-len --random-range-ratio --ignore-eos --max-concurrency --num-prompts --seed --save-result --result-dir; do
    grep -q -- "$flag" "$LOG.help" || { EXIT_CODE=1; STAGE="client lacks $flag"; echo "$STAGE" >"$OUTPUT"; break; }
  done
fi
if (( EXIT_CODE == 0 )); then
  "${client[@]}" "${warm[@]}" >"$out/warmup_stdout.log" 2>&1 || { EXIT_CODE=$?; STAGE='warmup failed'; cp "$out/warmup_stdout.log" "$OUTPUT"; }
fi
if (( EXIT_CODE == 0 )); then
  "${client[@]}" "${run[@]}" >"$OUTPUT" 2>&1 || { EXIT_CODE=$?; STAGE="client exited $EXIT_CODE"; }
fi
FINISHED=$(date -Iseconds); PINS_JSON=$("$ROOT_DIR/scripts/pins.sh" "$MODEL" 2>/dev/null || echo '{}')
[[ $PINS_JSON == \{* ]] || PINS_JSON='{}'
export id recipe ilen olen conc prompts STARTED FINISHED PINS_JSON seed out EXIT_CODE STAGE OUTPUT VLLM_IMAGE
python3 - <<'PY'
import glob, json, os
out = os.environ['out']; cfg = json.load(open('logs/current_server.json')); result = {}
for path in sorted(glob.glob(out + '/**/*.json', recursive=True)):
    if path.endswith('meta.json'):
        continue
    try:
        obj = json.load(open(path))
    except (OSError, ValueError):
        continue
    if isinstance(obj, dict) and ('completed' in obj or 'total_output_tokens' in obj):
        result = obj
        break
completed = int(result.get('completed') or 0); failed = int(result.get('failed') or 0)
total = result.get('total_output_tokens')
if total is None:
    lens = result.get('output_lens') or []
    total = sum(int(x or 0) for x in lens)
olen = int(os.environ['olen']); code = int(os.environ['EXIT_CODE'])
mean_out = (total / completed) if completed else None
if code != 0:
    status, error = 'failed', os.environ['STAGE'] + ': ' + ''.join(open(os.environ['OUTPUT'], errors='replace').readlines()[-20:]) if os.path.exists(os.environ['OUTPUT']) else os.environ['STAGE']
elif not result:
    status, error = 'failed', 'Could not locate client result JSON'
elif completed == 0:
    status, error = 'failed', 'No requests completed'
elif mean_out < 0.95 * olen:
    status, error = 'short_output', f'Mean output {mean_out:.1f} tokens < 95% of {olen}'
elif failed > 0:
    status, error = 'partial', f'{failed} requests failed'
else:
    status, error = 'ok', ''
m = {'run_id': os.environ['id'], 'recipe': os.environ['recipe'], 'model': cfg['hf_repo'],
     'weights_precision': cfg['weights_precision'], 'kv_cache_dtype': cfg['kv_cache_dtype'],
     'max_model_len': int(cfg['max_model_len']), 'gpu_memory_utilization': cfg.get('gpu_memory_utilization'),
     'server_args': cfg['server_args'], 'engine': cfg['engine'], 'cfg': cfg['cfg'],
     'seed': int(os.environ['seed']), 'client_image': os.environ.get('VLLM_IMAGE', ''),
     'input_len': int(os.environ['ilen']), 'output_len': olen, 'concurrency': int(os.environ['conc']),
     'num_prompts': int(os.environ['prompts']), 'completed': completed, 'failed': failed,
     'mean_output_tokens': mean_out, 'started_at': os.environ['STARTED'], 'finished_at': os.environ['FINISHED'],
     'status': status, 'error': error}
m.update(json.loads(os.environ['PINS_JSON']))
with open(out + '/meta.json', 'w') as f:
    json.dump(m, f, indent=2); f.write('\n')
raise SystemExit({'ok': 0, 'short_output': 3, 'partial': 4}.get(status, 1))
PY
