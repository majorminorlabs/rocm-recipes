#!/usr/bin/env python3
"""Sample ROCm VRAM and engine metrics once per second; absent metrics stay null."""
import os
import json, signal, sys, time, urllib.request
from pathlib import Path
from ttft_006 import histogram

running = True

def stop(_sig, _frame):
    global running
    running = False

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

def metric(text, names):
    for line in text.splitlines():
        if line.startswith('#'):
            continue
        name = line.split('{', 1)[0].split()[0] if line.split() else ''
        if name in names:
            try: return float(line.split()[-1])
            except (ValueError, IndexError): return None
    return None

def sample(engine):
    vram = None
    rehearsal = os.environ.get('REHEARSAL') == '1'
    try:
        if rehearsal: raise RuntimeError('CPU rehearsal: no GPU sampling')
        import subprocess
        raw = subprocess.run(['rocm-smi', '--showmeminfo', 'vram', '--json'], capture_output=True, text=True, timeout=5, check=True).stdout
        parsed = json.loads(raw)
        vals=[]
        def walk(x):
            if isinstance(x, dict):
                for k,v in x.items():
                    if 'used' in k.lower() and ('vram' in k.lower() or 'memory' in k.lower()):
                        try: vals.append(float(str(v).replace(',', '').split()[0]))
                        except ValueError: pass
                    walk(v)
            elif isinstance(x,list):
                for v in x: walk(v)
        walk(parsed)
        if vals: vram=max(vals)/1048576
    except Exception: pass
    metrics=None
    try:
        with urllib.request.urlopen('http://localhost:8000/metrics', timeout=2) as r: metrics=r.read().decode(errors='replace')
    except Exception: pass
    if metrics is None: return {'ts':time.time(),'peak_vram_mb':vram,'kv_usage':None,'preemptions':None,'prefix_hits':None,'prefix_queries':None,'sglang_hit_rate':None,'engine_ttft_histogram':None}
    return {'ts':time.time(),'peak_vram_mb':vram,
       'rehearsal':rehearsal,
       'kv_usage':None if rehearsal else metric(metrics, {'vllm:kv_cache_usage_perc','vllm:gpu_cache_usage_perc','sglang:token_usage'}),
       'preemptions':None if rehearsal else metric(metrics, {'vllm:num_preemptions_total'}),
       'prefix_hits':metric(metrics, {'vllm:prefix_cache_hits_total'}),
       'prefix_queries':metric(metrics, {'vllm:prefix_cache_queries_total'}),
       'sglang_hit_rate':metric(metrics, {'sglang:cache_hit_rate'}),
       'engine_ttft_histogram':histogram(metrics, engine)}

def main():
    if len(sys.argv)==2 and sys.argv[1]=='--self-test':
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import tempfile, threading, os
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body=b'# HELP vllm:kv_cache_usage_perc usage\nvllm:kv_cache_usage_perc 0.5\n'
                self.send_response(200); self.end_headers(); self.wfile.write(body)
            def log_message(self,*_): pass
        server=HTTPServer(('127.0.0.1',0),Handler); threading.Thread(target=server.serve_forever,daemon=True).start()
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/metrics') as r: raw=r.read().decode()
        server.shutdown()
        assert metric(raw, {'vllm:kv_cache_usage_perc'}) == .5
        assert metric('# HELP x x\nx 1\n', {'vllm:kv_cache_usage_perc'}) is None
        with tempfile.TemporaryDirectory() as d:
            fake=Path(d)/'rocm-smi'; fake.write_text('\n'.join(['#!/bin/sh', "cat <<'EOF'", '{\"GPU\":{\"VRAM Total Used Memory (B)\":\"1048576\"}}', 'EOF', ''])); fake.chmod(0o755)
            env=os.environ.copy(); env['PATH']=d+':'+env.get('PATH','')
            raw=json.loads(__import__('subprocess').run([str(fake),'--showmeminfo','vram','--json'],capture_output=True,text=True,check=True).stdout)
            assert 'GPU' in raw
        print('gpu_sampler self-test: fake /metrics server and rocm-smi: ok'); return
    if len(sys.argv)!=3: raise SystemExit('usage: gpu_sampler.py <out_dir> <engine>')
    out,engine=sys.argv[1:]
    p=Path(out); p.mkdir(parents=True,exist_ok=True)
    with (p/'samples.jsonl').open('a') as f:
        while running:
            f.write(json.dumps(sample(engine))+'\n'); f.flush()
            for _ in range(10):
                if not running: break
                time.sleep(.1)
if __name__=='__main__': main()
