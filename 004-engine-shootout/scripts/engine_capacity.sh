#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT_DIR"; mkdir -p logs
LOG="logs/engine_capacity_$(date +%Y%m%d_%H%M%S).log"; exec > >(tee -a "$LOG") 2>&1
DRY=0; [[ ${1:-} == --dry-run ]] && { DRY=1; shift; }; [[ $# == 1 && $1 =~ ^[A-Za-z0-9._-]+$ ]] || { echo 'Usage: engine_capacity.sh [--dry-run] <run_id>' >&2; exit 2; }
id=$1; out="results/raw/L0/$id"
if (( DRY )); then echo "mkdir -p $out; capture server log capacity/backend lines and rocm-smi VRAM; parse per engine"; exit 0; fi
PINS_JSON=$("$ROOT_DIR/scripts/pins.sh" "$(python3 -c 'import json;print(json.load(open("logs/current_server.json"))["hf_repo"])')" 2>/dev/null || echo '{}'); [[ $PINS_JSON == \{* ]] || PINS_JSON='{}'; export PINS_JSON
python3 - "$id" "$out" <<'PY'
import datetime,json,re,subprocess,sys,os
rid,out=sys.argv[1:]; os.makedirs(out,exist_ok=True); c=json.load(open('logs/current_server.json')); lines=open(c['server_log'],errors='replace').readlines(); engine=c['engine']
raw=[x for x in lines if re.search(r'kv cache|maximum concurrency|max_total_num_tokens|#tokens:|n_ctx|n_slots',x,re.I)]; open(out+'/capacity_raw.txt','w').writelines(raw)
open(out+'/backend.txt','w').writelines(x for x in lines if re.search(r'backend|aiter|triton|paged attention|attn|attention|flash|rocm|hip|moe',x,re.I))
try:
 r=subprocess.run(['rocm-smi','--showmeminfo','vram','--json'],capture_output=True,text=True,check=False); json.dump(json.loads(r.stdout) if r.returncode==0 else {'error':r.stderr or r.stdout},open(out+'/vram.json','w'),indent=2)
except Exception as e: json.dump({'error':str(e)},open(out+'/vram.json','w'),indent=2)
def find(pat,cast=int):
 for line in raw:
  m=re.search(pat,line,re.I)
  if m:return cast(m.group(1).replace(',',''))
 return None
if engine=='vllm': kv=find(r'GPU KV cache size:\s*([\d,]+)\s+tokens'); con=find(r'Maximum concurrency for [\d,]+ tokens per request:\s*([\d.]+)',float); ok=kv is not None and con is not None
elif engine=='sglang': kv=find(r'max_total_num_tokens=(\d+)') or find(r'#tokens:\s*([\d,]+)'); con=None; ok=True
else: kv=find(r'n_ctx\s*=\s*([\d,]+)'); con=None; ok=True
json.dump({'kv_cache_tokens':kv,'max_concurrency_at_max_len':con},open(out+'/capacity.json','w'),indent=2)
meta={'run_id':rid,'recipe':'L0','model':c['hf_repo'],'weights_precision':c['weights_precision'],'kv_cache_dtype':c['kv_cache_dtype'],'max_model_len':c['max_model_len'],'server_args':c['server_args'],'engine':engine,'cfg':c['cfg'],'input_len':None,'output_len':None,'concurrency':None,'num_prompts':None,'started_at':c['started_at'],'finished_at':datetime.datetime.now().astimezone().isoformat(),'status':'ok' if ok else 'failed','error':'' if kv is not None else 'Capacity unparsed; raw lines and VRAM retained' if engine!='vllm' else 'Could not parse KV capacity'}
meta.update(json.loads(os.environ.get('PINS_JSON','{}')))
json.dump(meta,open(out+'/meta.json','w'),indent=2)
if not ok: sys.exit(1)
PY
