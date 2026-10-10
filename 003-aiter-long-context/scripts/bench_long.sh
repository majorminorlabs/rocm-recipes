#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT_DIR"; mkdir -p logs
LOG="logs/bench_long_$(date +%Y%m%d_%H%M%S).log"; exec > >(tee -a "$LOG") 2>&1
DRY=0; [[ "${1:-}" == --dry-run ]] && { DRY=1; shift; }; [[ $# == 6 ]] || { echo 'Usage: bench_long.sh [--dry-run] <run_id> <recipe> <input_len> <output_len> <concurrency> <num_prompts>' >&2; exit 2; }
id=$1; recipe=$2; ilen=$3; olen=$4; conc=$5; prompts=$6; [[ $id =~ ^[A-Za-z0-9._-]+$ && $recipe =~ ^L[12]$ && $ilen =~ ^[0-9]+$ && $olen =~ ^[0-9]+$ && $conc =~ ^[1-9][0-9]*$ && $prompts =~ ^[1-9][0-9]*$ ]] || exit 2
out="results/raw/$recipe/$id"; cfg=logs/current_server.json
if [[ -f $cfg ]]; then
  MODEL=$(python3 -c 'import json;print(json.load(open("logs/current_server.json"))["hf_repo"])')
else
  (( DRY )) || { echo 'No current server config' >&2; exit 1; }
  MODEL='<hf_repo from logs/current_server.json>'
fi
base=(vllm bench serve --model "$MODEL" --backend vllm --dataset-name random --random-input-len "$ilen" --random-output-len "$olen" --random-range-ratio 0 --ignore-eos --max-concurrency "$conc" --num-prompts "$prompts" --seed 0)
warm=(vllm bench serve --model "$MODEL" --backend vllm --dataset-name random --random-input-len 1024 --random-output-len 64 --random-range-ratio 0 --ignore-eos --max-concurrency 1 --num-prompts 2 --seed 1)
if ((DRY)); then printf 'docker exec vllm-server vllm bench serve --help=all > %q.help\n' "$LOG"; printf 'docker exec vllm-server'; printf ' %q' "${warm[@]}"; printf '\n'; printf 'docker exec vllm-server'; printf ' %q' "${base[@]}"; printf ' --save-result --result-dir /workspace/%q\n' "$out"; exit 0; fi
maxlen=$(python3 -c 'import json;print(json.load(open("logs/current_server.json"))["max_model_len"])'); (( ilen+olen <= maxlen )) || { echo 'input_len + output_len exceeds max_model_len' >&2; exit 1; }
mkdir -p "$out"; STARTED=$(date -Iseconds); EXIT_CODE=0; WARMUP_FAILED=0; OUTPUT="$out/bench_stdout.log"
if docker exec vllm-server vllm bench serve --help=all >"$LOG.help" 2>&1; then
  for flag in --model --backend --dataset-name --random-input-len --random-output-len --random-range-ratio --ignore-eos --max-concurrency --num-prompts --seed --save-result; do
    if ! grep -q -- "$flag" "$LOG.help"; then echo "vllm bench serve lacks $flag" >"$OUTPUT"; EXIT_CODE=1; break; fi
  done
  if (( EXIT_CODE == 0 )); then
    if docker exec vllm-server "${warm[@]}" >"$out/warmup_stdout.log" 2>"$out/warmup.log"; then
      :
    else
      EXIT_CODE=$?; WARMUP_FAILED=1
      cat "$out/warmup_stdout.log" "$out/warmup.log" >"$OUTPUT"
    fi
  fi
  if (( EXIT_CODE == 0 )); then
    docker exec vllm-server "${base[@]}" --save-result --result-dir "/workspace/$out" >"$OUTPUT" 2>&1 || EXIT_CODE=$?
  fi
else
  EXIT_CODE=$?; cp "$LOG.help" "$OUTPUT"
fi
FINISHED=$(date -Iseconds); PINS_JSON=$("$ROOT_DIR/scripts/pins.sh" "$MODEL")
ERROR=''; if (( EXIT_CODE != 0 )); then ERROR=$(tail -n 20 "$OUTPUT"); fi
if (( WARMUP_FAILED )); then ERROR="warmup failed: $ERROR"; fi
export id recipe ilen olen conc prompts STARTED FINISHED EXIT_CODE ERROR PINS_JSON
python3 - "$out" <<'PY'
import json, os, sys
out=sys.argv[1]; c=json.load(open('logs/current_server.json'))
m={'run_id':os.environ['id'],'recipe':os.environ['recipe'],'model':c['hf_repo'],'weights_precision':c['weights_precision'],'kv_cache_dtype':c['kv_cache_dtype'],'max_model_len':int(c['max_model_len']),'gpu_memory_utilization':float(c['gpu_memory_utilization']),'server_args':c['server_args'],'engine':'vllm','input_len':int(os.environ['ilen']),'output_len':int(os.environ['olen']),'concurrency':int(os.environ['conc']),'num_prompts':int(os.environ['prompts']),'started_at':os.environ['STARTED'],'finished_at':os.environ['FINISHED'],'status':'ok' if os.environ['EXIT_CODE']=='0' else 'failed','error':os.environ['ERROR']}
m.update(json.loads(os.environ['PINS_JSON']))
with open(out+'/meta.json','w') as f: json.dump(m,f,indent=2); f.write('\n')
PY
exit "$EXIT_CODE"
