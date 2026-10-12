#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT_DIR"; mkdir -p logs
LOG="logs/bench_engine_$(date +%Y%m%d_%H%M%S).log"; if [[ ${1:-} != --dry-run && ! ( ${1:-} == --dataset && ${3:-} == --dry-run ) ]]; then exec > >(tee -a "$LOG") 2>&1; fi
DRY=0; DATASET=''; if [[ ${1:-} == --dataset ]]; then DATASET=$2; shift 2; fi; DATASET_MODE=random; [[ $DATASET == custom:* ]] && DATASET_MODE=W1_code; [[ ${1:-} == --dry-run ]] && { DRY=1; shift; }; [[ $# == 6 ]] || { echo 'Usage: bench_engine.sh [--dry-run] <run_id> <recipe> <input_len> <output_len> <concurrency> <num_prompts>' >&2; exit 2; }
id=$1; recipe=$2; ilen=$3; olen=$4; conc=$5; prompts=$6; [[ $id =~ ^[A-Za-z0-9._-]+$ && $recipe =~ ^L[12]$ && $ilen =~ ^[0-9]+$ && $olen =~ ^[0-9]+$ && $conc =~ ^[1-9][0-9]*$ && $prompts =~ ^[1-9][0-9]*$ ]] || exit 2
seed=$(python3 - "$id" <<'PY'
import re,sys,zlib
key=re.sub(r'-(VD|VT|SD|SX|LC1|LC4|B|K1|K2|K3|T)(?=-|$)','',sys.argv[1]); print(zlib.crc32(key.encode())%(2**31))
PY
)
out="results/raw/$recipe/$id"; cfg=logs/current_server.json
if [[ -f $cfg ]]; then readarray -t vals < <(python3 -c 'import json;d=json.load(open("logs/current_server.json"));print(d["hf_repo"]);print(d["engine"]);print(d["cfg"]);print(d["max_model_len"])'); MODEL=${vals[0]}; config=${vals[2]}; maxlen=${vals[3]}; else (( DRY )) || { echo 'No current server config' >&2; exit 1; }; MODEL='<hf_repo>'; config='<cfg>'; maxlen=999999; fi
if ((DRY)); then echo "seed=$seed"; # shellcheck disable=SC2016
 if [[ $DATASET == custom:* ]]; then printf 'docker run ... --dataset-name custom --dataset-path %q --custom-output-len %q --custom-skip-chat-template --percentile-metrics 'ttft,tpot,itl,e2el' --metric-percentiles '50,95,99' --max-concurrency %q --num-prompts %q --seed %q\n' "${DATASET#custom:}" "$olen" "$conc" "$prompts" "$seed"; else printf 'docker run ... --dataset-name random --random-input-len %q --random-output-len %q --percentile-metrics 'ttft,tpot,itl,e2el' --metric-percentiles '50,95,99' --max-concurrency %q --num-prompts %q --seed %q\n' "$ilen" "$olen" "$conc" "$prompts" "$seed"; fi; exit 0; fi
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
common=(--backend openai --base-url http://localhost:8000 --endpoint /v1/completions --model "$MODEL")
if [[ $DATASET == custom:* ]]; then
  run=("${common[@]}" --dataset-name custom --dataset-path "/workspace/${DATASET#custom:}" --custom-output-len "$olen" --custom-skip-chat-template --max-concurrency "$conc" --num-prompts "$prompts" --seed "$seed" --percentile-metrics 'ttft,tpot,itl,e2el' --metric-percentiles '50,95,99' --save-result --result-dir "/workspace/$out")
  warm=("${common[@]}" --dataset-name random --random-input-len 1024 --random-output-len 64 --random-range-ratio 0 --ignore-eos --max-concurrency 1 --num-prompts 2 --seed 1)
else
  run=("${common[@]}" --dataset-name random --random-input-len "$ilen" --random-output-len "$olen" --random-range-ratio 0 --ignore-eos --max-concurrency "$conc" --num-prompts "$prompts" --seed "$seed" --percentile-metrics 'ttft,tpot,itl,e2el' --metric-percentiles '50,95,99' --save-result --result-dir "/workspace/$out")
fi
if ! "${client[@]}" --help=all >"$LOG.help" 2>&1; then EXIT_CODE=1; STAGE='client help failed'; cp "$LOG.help" "$OUTPUT"; fi
if (( EXIT_CODE == 0 )); then
  for flag in --backend --base-url --endpoint --model --dataset-name --max-concurrency --num-prompts --seed --save-result --result-dir --percentile-metrics --metric-percentiles; do
    grep -q -- "$flag" "$LOG.help" || { EXIT_CODE=1; STAGE="client lacks $flag"; echo "$STAGE" >"$OUTPUT"; break; }
  done
fi
if (( EXIT_CODE == 0 )); then
  "${client[@]}" "${warm[@]}" >"$out/warmup_stdout.log" 2>&1 || { EXIT_CODE=$?; STAGE='warmup failed'; cp "$out/warmup_stdout.log" "$OUTPUT"; }
fi
if (( EXIT_CODE == 0 )); then
  if [[ $DATASET == custom:* ]]; then
    CUSTOM_MISSING=''
    if ! grep -- --dataset-name "$LOG.help" | grep -q custom; then CUSTOM_MISSING+=' --dataset-name custom'; fi
    for flag in --dataset-path --custom-output-len --custom-skip-chat-template; do
      grep -q -- "$flag" "$LOG.help" || CUSTOM_MISSING+=" $flag"
    done
    if [[ -n $CUSTOM_MISSING ]]; then
      if grep -q -- --random-prefix-len "$LOG.help"; then
        DATASET_MODE=W1_random_shared_prefix
        run=("${common[@]}" --dataset-name random --random-prefix-len 1536 --random-input-len 2560 --random-output-len "$olen" --random-range-ratio 0 --ignore-eos --max-concurrency "$conc" --num-prompts "$prompts" --seed "$seed" --percentile-metrics 'ttft,tpot,itl,e2el' --metric-percentiles '50,95,99' --save-result --result-dir "/workspace/$out")
      else
        EXIT_CODE=1; STAGE="client lacks custom flags ($CUSTOM_MISSING) and --random-prefix-len fallback"
      fi
    fi
  else
    for flag in --random-input-len --random-output-len --random-range-ratio --ignore-eos; do grep -q -- "$flag" "$LOG.help" || { EXIT_CODE=1; STAGE="client lacks $flag"; break; }; done
  fi
fi
if (( EXIT_CODE == 0 )); then
  engine=$(python3 -c 'import json;print(json.load(open("logs/current_server.json"))["engine"])')
  SLOG=$(python3 -c 'import json;print(json.load(open("logs/current_server.json"))["server_log"])')
  RETRACT0=$(grep -ci 'retract' "$SLOG" 2>/dev/null || true)
  python3 scripts/gpu_sampler.py "$out" "$engine" & SAMPLER_PID=$!
  "${client[@]}" "${run[@]}" >"$OUTPUT" 2>&1 || { EXIT_CODE=$?; STAGE="client exited $EXIT_CODE"; }
  kill -TERM "$SAMPLER_PID" 2>/dev/null || true; wait "$SAMPLER_PID" 2>/dev/null || true
  [[ $DATASET_MODE != W1_random_shared_prefix ]] || echo "Custom dataset flags unavailable; used documented shared-prefix random W1 input (1536 prefix + 2560 random tokens)." >>"$OUTPUT"
  RETRACT1=$(grep -ci 'retract' "$SLOG" 2>/dev/null || true)
  export RETRACTS=$(( ${RETRACT1:-0} - ${RETRACT0:-0} ))
fi
FINISHED=$(date -Iseconds); PINS_JSON=$("$ROOT_DIR/scripts/pins.sh" "$MODEL" 2>/dev/null || echo '{}')
[[ $PINS_JSON == \{* ]] || PINS_JSON='{}'
export DATASET DATASET_MODE id recipe ilen olen conc prompts STARTED FINISHED PINS_JSON seed out EXIT_CODE STAGE OUTPUT VLLM_IMAGE
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
samples=[]
try:
    for line in open(out+'/samples.jsonl'):
        try: samples.append(json.loads(line))
        except ValueError: pass
except OSError: pass
if samples:
    vram=[s.get('peak_vram_mb') for s in samples if s.get('peak_vram_mb') is not None]
    kv=[s.get('kv_usage') for s in samples if s.get('kv_usage') is not None]
    pp=[s.get('preemptions') for s in samples if s.get('preemptions') is not None]
    first,last=samples[0],samples[-1]
    if last.get('sglang_hit_rate') is not None: hit=last['sglang_hit_rate']
    elif last.get('prefix_hits') is not None:
        den=last.get('prefix_queries',0)-(first.get('prefix_queries') or 0); hit=(last['prefix_hits']-(first.get('prefix_hits') or 0))/den if den else None
    else: hit=None
else: vram=[]; kv=[]; pp=[]; hit=None
# vLLM bench writes median_<m>_ms / p95_<m>_ms / p99_<m>_ms; store as <m>_p50_ms etc.
pct = {}
for name in ('ttft', 'tpot', 'itl', 'e2el'):
    pct[f'{name}_p50_ms'] = result.get(f'median_{name}_ms', result.get(f'p50_{name}_ms'))
    pct[f'{name}_p95_ms'] = result.get(f'p95_{name}_ms')
    pct[f'{name}_p99_ms'] = result.get(f'p99_{name}_ms')
m = {'run_id': os.environ['id'], 'recipe': os.environ['recipe'], 'model': cfg['hf_repo'],
     'weights_precision': cfg['weights_precision'], 'kv_cache_dtype': cfg['kv_cache_dtype'],
     'max_model_len': int(cfg['max_model_len']), 'gpu_memory_utilization': cfg.get('gpu_memory_utilization'),
     'server_args': cfg['server_args'], 'engine': cfg['engine'], 'cfg': cfg['cfg'],
     'seed': int(os.environ['seed']), 'client_image': os.environ.get('VLLM_IMAGE', ''),
     'input_len': int(os.environ['ilen']), 'output_len': olen, 'concurrency': int(os.environ['conc']),
     'num_prompts': int(os.environ['prompts']), 'completed': completed, 'failed': failed,
     'mean_output_tokens': mean_out, **pct, 'output_tok_per_s': result.get('output_throughput'), 'total_tok_per_s': result.get('total_token_throughput'), 'started_at': os.environ['STARTED'], 'finished_at': os.environ['FINISHED'],
     'status': status, 'error': error, 'workload': 'W1' if os.environ.get('DATASET','').startswith('custom:') else 'W2', 'dataset_mode': os.environ.get('DATASET_MODE','random'), 'knob_set': cfg.get('knob_set','B'), 'quant': 'bf16+'+str(cfg.get('kv_cache_dtype','auto')), 'peak_vram_mb':max(vram) if vram else None, 'peak_kv_usage':max(kv) if kv else None, 'preemptions':(max(0,pp[-1]-pp[0]) if len(pp)>1 else (0 if pp else None)) if cfg['engine']=='vllm' else (int(os.environ['RETRACTS']) if os.environ.get('RETRACTS','').lstrip('-').isdigit() else None), 'prefix_cache_hit_rate':hit}
m.update(json.loads(os.environ['PINS_JSON']))
with open(out + '/meta.json', 'w') as f:
    json.dump(m, f, indent=2); f.write('\n')
raise SystemExit({'ok': 0, 'short_output': 3, 'partial': 4}.get(status, 1))
PY
