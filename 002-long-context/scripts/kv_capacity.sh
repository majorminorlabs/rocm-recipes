#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT_DIR"; mkdir -p logs
LOG="logs/kv_capacity_$(date +%Y%m%d_%H%M%S).log"; exec > >(tee -a "$LOG") 2>&1
DRY=0; [[ "${1:-}" == --dry-run ]] && { DRY=1; shift; }; [[ $# == 1 ]] || { echo 'Usage: kv_capacity.sh [--dry-run] <run_id>' >&2; exit 2; }
id=$1; [[ $id =~ ^[A-Za-z0-9._-]+$ ]] || exit 2; out="results/raw/L0/$id"; cmd='grep -iE "kv cache|maximum concurrency" <server log>; rocm-smi --showmeminfo vram --json'
if ((DRY)); then printf 'mkdir -p %q; %s\n' "$out" "$cmd"; exit 0; fi
mkdir -p "$out"; PINS_JSON=$("$ROOT_DIR/scripts/pins.sh" "$(python3 -c 'import json;print(json.load(open("logs/current_server.json"))["hf_repo"])')"); export PINS_JSON
python3 - "$id" "$out" <<'PY'
import json,re,sys,datetime,subprocess,os
rid,out=sys.argv[1:]; cfg=json.load(open('logs/current_server.json')); log=cfg['server_log']; lines=open(log,errors='replace').readlines(); raw=[x for x in lines if re.search(r'kv cache|maximum concurrency',x,re.I)]; open(out+'/capacity_raw.txt','w').writelines(raw)
open(out+'/backend.txt','w').writelines([x for x in lines if re.search(r'backend|aiter|triton|paged attention|attn',x,re.I)])
try:
 result=subprocess.run(['rocm-smi','--showmeminfo','vram','--json'],capture_output=True,text=True,errors='replace',check=False)
 if result.returncode == 0:
  open(out+'/vram.json','w').write(result.stdout)
 else:
  json.dump({'error':result.stderr.strip() or result.stdout.strip() or f'rocm-smi exited {result.returncode}'},open(out+'/vram.json','w'),indent=2)
except OSError as exc:
 json.dump({'error':str(exc)},open(out+'/vram.json','w'),indent=2)
def find(pattern,cast):
 for x in raw:
  m=re.search(pattern,x,re.I)
  if m: return cast(m.group(1).replace(',',''))
 return None
kv=find(r'GPU KV cache size:\s*([\d,]+)\s+tokens',int); con=find(r'Maximum concurrency for [\d,]+ tokens per request:\s*([\d.]+)',float)
json.dump({'kv_cache_tokens':kv,'max_concurrency_at_max_len':con},open(out+'/capacity.json','w'),indent=2)
meta={'run_id':rid,'recipe':'L0','model':cfg['hf_repo'],'weights_precision':cfg['weights_precision'],'kv_cache_dtype':cfg['kv_cache_dtype'],'max_model_len':int(cfg['max_model_len']),'gpu_memory_utilization':float(cfg['gpu_memory_utilization']),'server_args':cfg['server_args'],'engine':'vllm','input_len':None,'output_len':None,'concurrency':None,'num_prompts':None,'started_at':cfg['started_at'],'finished_at':datetime.datetime.now().astimezone().isoformat(),'status':'ok' if kv is not None and con is not None else 'failed','error':'' if kv is not None and con is not None else 'Could not parse KV cache tokens and/or maximum concurrency'}
meta.update(json.loads(os.environ['PINS_JSON']))
json.dump(meta,open(out+'/meta.json','w'),indent=2)
if kv is None or con is None: print(meta['error'],file=sys.stderr); sys.exit(1)
PY
