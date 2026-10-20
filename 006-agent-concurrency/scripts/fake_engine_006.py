#!/usr/bin/env python3
"""CPU-only OpenAI SSE rehearsal server. Never emits a solved claim or scores."""
import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rehearsal_006 import TOKENIZER_REVISION

MODEL = 'Qwen/Qwen3.8-27B'


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, engine, policy='lpm', token=None):
        super().__init__(address, Handler)
        self.engine, self.policy, self.token = engine, policy, token
        self.requests = 0
        self.lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        print(fmt % args, flush=True)

    def body(self, data, content_type='application/json'):
        raw = data.encode() if isinstance(data, str) else json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

    def do_GET(self):
        if self.path == '/v1/models':
            self.body({'object': 'list', 'data': [{'id': MODEL, 'object': 'model', 'owned_by': 'rehearsal', 'rehearsal_token': self.server.token}]})
        elif self.path == '/metrics':
            with self.server.lock:
                n = self.server.requests
            name = self.server.engine + ':time_to_first_token_seconds'
            lines = ['# TYPE '+name+' histogram']
            for bound in ('.001', '.005', '.01', '.1', '1', '+Inf'):
                lines.append(f'{name}_bucket{{model_name="{MODEL}",le="{bound}"}} {0 if float(bound) < .005 else n}')
            lines += [f'{name}_count {n}', f'{name}_sum {n * .005}']
            if self.server.engine == 'sglang':
                lines += ['# TYPE sglang:cache_hit_rate gauge', f'sglang:cache_hit_rate {0.5 if n else 0}']
            else:
                lines += [f'vllm:prefix_cache_hits_total {max(0,n-1)*2048}', f'vllm:prefix_cache_queries_total {n*4096}']
            self.body('\n'.join(lines)+'\n', 'text/plain; version=0.0.4')
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != '/v1/chat/completions':
            self.send_error(404); return
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        with self.server.lock:
            self.server.requests += 1
            n = self.server.requests
        # A real read-only tool round trip exercises the native harness and proxy.
        has_tool = any(m.get('role') == 'tool' for m in request.get('messages', []))
        tools = [t.get('function', {}) for t in request.get('tools', [])]
        tool = next((t for t in tools if t.get('name') == 'bash'), None)
        invoke = tool is not None and not has_tool
        usage = {'prompt_tokens': 4096, 'completion_tokens': 16, 'total_tokens': 4112,
                 'prompt_tokens_details': {'cached_tokens': 2048 if n > 1 else 0}}
        ident = 'chatcmpl-rehearsal-'+uuid.uuid4().hex
        def chunk(delta=None, finish=None, usage_value=None):
            return dict(id=ident, object='chat.completion.chunk', created=int(time.time()), model=MODEL,
                        choices=[] if usage_value else [dict(index=0, delta=delta or {}, finish_reason=finish)],
                        **({'usage': usage_value} if usage_value else {}))
        delta = {'tool_calls': [{'index': 0, 'id': 'call_'+uuid.uuid4().hex, 'type': 'function',
                                'function': {'name': 'bash', 'arguments': json.dumps({'command': 'pwd', 'description': 'Rehearsal read-only tool check'})}}]} if invoke else {'content': 'CPU rehearsal completed the transport check. No source change was attempted.'}
        if not request.get('stream'):
            message = {'role': 'assistant', 'reasoning_content': 'Checking the rehearsal transport.', **delta}
            if invoke:
                message['tool_calls'][0].pop('index')
            self.body(dict(id=ident, object='chat.completion', created=int(time.time()), model=MODEL,
                           choices=[dict(index=0, message=message, finish_reason='tool_calls' if invoke else 'stop')], usage=usage))
            return
        self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Transfer-Encoding', 'chunked'); self.end_headers()
        def send(value):
            data = ('data: '+(value if isinstance(value, str) else json.dumps(value))+'\n\n').encode()
            self.wfile.write(f'{len(data):X}\r\n'.encode()+data+b'\r\n'); self.wfile.flush()
        try:
            send(chunk({'role': 'assistant'})); time.sleep(.005)
            send(chunk({'reasoning_content': 'Checking the rehearsal transport.'}))
            send(chunk(delta)); send(chunk(finish='tool_calls' if invoke else 'stop'))
            send(chunk(usage_value=usage)); send('[DONE]')
            self.wfile.write(b'0\r\n\r\n'); self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def server_metadata(engine, policy='lpm', token=None):
    """Simulate configured settings, while identifying the runtime as a CPU fixture.

    vLLM's launch/provenance field shape matches the recorded session-3 server.
    No image/container ID, real engine version or weight hash is fabricated.
    """
    record = dict(engine=engine, schedule_policy=policy, hf_repo=MODEL,
        model_revision=TOKENIZER_REVISION, weights_precision=None, max_model_len=131072,
        engine_version='cpu-rehearsal-1', rehearsal=True, fixture=True, token=token)
    if engine == 'vllm':
        record.update(cfg='VT', weights_precision='bf16', kv_cache_dtype='auto',
            serve_env='VLLM_ROCM_USE_AITER=1', gpu_memory_utilization=0.92, knob_set='T',
            server_args='ENV[VLLM_ROCM_USE_AITER=1] --host 0.0.0.0 --port 8000 --max-model-len 131072 --gpu-memory-utilization 0.92 --kv-cache-dtype auto --attention-backend ROCM_AITER_UNIFIED_ATTN --dtype bfloat16 --enable-prefix-caching --max-num-batched-tokens 16384 --enable-prompt-tokens-details --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3')
    return record


def stop(root):
    path = root/'results/rehearsal/logs/fake_server.json'
    if not path.exists():
        return
    saved = json.loads(path.read_text()); pid = saved['pid']
    try:
        cmd = Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\x00', b' ').decode()
    except FileNotFoundError:
        path.unlink(); return
    if saved['token'] not in cmd or 'fake_engine_006.py' not in cmd:
        raise ValueError('Refuse to stop an unowned process')
    os.kill(pid, signal.SIGTERM)
    for _ in range(100):
        try:
            with urllib.request.urlopen('http://localhost:8000/v1/models', timeout=.1):
                pass
        except OSError:
            path.unlink(); return
        time.sleep(.1)
    raise ValueError('Owned fake server did not stop')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['start', 'stop', '_serve'])
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--engine', choices=['vllm', 'sglang'], default='sglang')
    p.add_argument('--policy', choices=['fcfs', 'lpm'], default='lpm')
    p.add_argument('--token')
    a = p.parse_args(); root = a.root.resolve()
    if os.environ.get('REHEARSAL') != '1':
        p.error('REHEARSAL=1 is required')
    if a.action == '_serve':
        # Bind the host interface too: the unchanged native proxy uses host-gateway.
        Server(('0.0.0.0', 8000), a.engine, a.policy, a.token).serve_forever(); return
    if a.action == 'stop':
        stop(root); return
    stop(root)
    logs = root/'results/rehearsal/logs'; logs.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    with (logs/f'fake_{a.engine}_{a.policy}_{token}.log').open('w') as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_serve', '--root', str(root),
                                    '--engine', a.engine, '--policy', a.policy, '--token', token],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (logs/'fake_server.json').write_text(json.dumps(dict(pid=process.pid, token=token)))
    for _ in range(100):
        if process.poll() is not None:
            raise ValueError('Fake server exited; inspect its log (port 8000 must be free)')
        try:
            with urllib.request.urlopen('http://localhost:8000/v1/models', timeout=.2) as response:
                if json.load(response)['data'][0].get('rehearsal_token') == token:
                    break
        except OSError:
            pass
        time.sleep(.1)
    else:
        stop(root); raise ValueError('Fake server readiness failed')
    (logs/'current_server.json').write_text(json.dumps(server_metadata(a.engine,a.policy,token), indent=2)+'\n')


if __name__ == '__main__':
    main()
