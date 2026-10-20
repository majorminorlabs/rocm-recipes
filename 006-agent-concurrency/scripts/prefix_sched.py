#!/usr/bin/env python3
"""Section 5b closed-loop streaming client. Python standard library only."""
import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

GROUPS = ('G1', 'G2', 'G3', 'G4')


def quantile(values, p):
    if not values or any(v is None for v in values):
        return None
    values = sorted(values); pos = (len(values) - 1) * p; lo = math.floor(pos)
    return values[lo] + (values[math.ceil(pos)] - values[lo]) * (pos - lo)


async def http_stream(url, body=None):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
        raise ValueError('Expected a plain HTTP(S) engine endpoint')
    reader, writer = await asyncio.open_connection(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80),
                                                   ssl=ssl.create_default_context() if parsed.scheme == 'https' else None)
    try:
        payload = json.dumps(body).encode() if body is not None else b''
        path = parsed.path or '/'
        if parsed.query:
            path += '?' + parsed.query
        headers = f'{"POST" if body is not None else "GET"} {path} HTTP/1.1\r\nHost: {parsed.netloc}\r\nConnection: close\r\n'
        if body is not None:
            headers += f'Content-Type: application/json\r\nContent-Length: {len(payload)}\r\n'
        writer.write(headers.encode() + b'\r\n' + payload); await writer.drain()
        head = (await reader.readuntil(b'\r\n\r\n')).decode('latin1').split('\r\n')
        status = int(head[0].split()[1])
        if status != 200:
            raise ValueError(f'HTTP {status}')
        fields = dict(line.split(':', 1) for line in head[1:] if ':' in line)
        fields = {k.lower(): v.strip() for k, v in fields.items()}
        if 'chunked' in fields.get('transfer-encoding', '').lower():
            while True:
                size = int((await reader.readline()).split(b';', 1)[0].strip(), 16)
                if size == 0:
                    break
                yield await reader.readexactly(size)
                if await reader.readexactly(2) != b'\r\n':
                    raise ValueError('Malformed chunked stream')
        else:
            remaining = int(fields['content-length']) if 'content-length' in fields else None
            while remaining is None or remaining > 0:
                data = await reader.read(min(65536, remaining) if remaining is not None else 65536)
                if not data:
                    if remaining not in (None, 0):
                        raise ValueError('Truncated HTTP body')
                    break
                if remaining is not None:
                    remaining -= len(data)
                yield data
    finally:
        writer.close(); await writer.wait_closed()


async def request(base, prompt, model, timeout):
    row = {'request_id': prompt['request_id'], 'group': prompt['group'],
           'started_at': datetime.now(timezone.utc).isoformat(), 'prompt_tokens': None,
           'cached_tokens': None, 'ttft_s': None, 'e2e_s': None, 'output_tokens': None, 'status': 'error'}
    started = time.perf_counter(); done = False; buffer = b''; event_lines = []
    body = {'model': model, 'messages': prompt['messages'], 'stream': True,
            'stream_options': {'include_usage': True}, 'max_tokens': 256, 'ignore_eos': True}
    try:
        async with asyncio.timeout(timeout):
            async for chunk in http_stream(base.rstrip('/') + '/chat/completions', body):
                buffer += chunk
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1); line = line.rstrip(b'\r')
                    if line.startswith(b'data:'):
                        event_lines.append(line[5:].lstrip())
                    if not line and event_lines:
                        data = b'\n'.join(event_lines); event_lines = []
                        if data == b'[DONE]':
                            done = True; continue
                        event = json.loads(data)
                        if event.get('error'):
                            raise ValueError('Stream returned an error')
                        for choice in event.get('choices', []):
                            delta = choice.get('delta') or {}
                            if row['ttft_s'] is None and any(delta.get(k) for k in ('content', 'reasoning_content', 'reasoning', 'tool_calls')):
                                row['ttft_s'] = time.perf_counter() - started
                        usage = event.get('usage')
                        if usage:
                            row['prompt_tokens'] = usage.get('prompt_tokens')
                            row['output_tokens'] = usage.get('completion_tokens')
                            row['cached_tokens'] = (usage.get('prompt_tokens_details') or {}).get('cached_tokens', usage.get('cached_tokens'))
        if not done or row['ttft_s'] is None:
            raise ValueError('Missing terminal event or streamed token')
        row['status'] = 'ok'
    except Exception as error:
        row['error'] = f'{type(error).__name__}: {error}'
    row['e2e_s'] = time.perf_counter() - started
    return row


def cache_metric(text):
    for name in ('sglang:cache_hit_rate', 'sglang_cache_hit_rate'):
        values = []
        for line in text.splitlines():
            match = re.match(re.escape(name) + r'(?:\{[^}]*\})?\s+(\S+)', line)
            if match:
                value = float(match[1])
                if math.isfinite(value):
                    values.append(value)
        if values:
            kind = next((line.split()[-1] for line in text.splitlines() if line.startswith('# TYPE ' + name + ' ')), 'unknown')
            return {'name': name, 'type': kind, 'value': values[0] if len(set(values)) == 1 else None}
    return {'name': None, 'type': None, 'value': None}


async def scrape(base):
    try:
        url = base.rsplit('/v1', 1)[0] + '/metrics'
        async with asyncio.timeout(5):
            raw = b''.join([data async for data in http_stream(url)]).decode()
        return {'ts': time.time(), **cache_metric(raw), 'raw': raw}
    except Exception as error:
        return {'ts': time.time(), 'name': None, 'type': None, 'value': None, 'error': str(error)}


def usage_hit(rows):
    if not rows or any(r['cached_tokens'] is None or r['prompt_tokens'] is None for r in rows):
        return None
    total = sum(r['prompt_tokens'] for r in rows)
    return sum(r['cached_tokens'] for r in rows) / total if total else None


def summarize(rows, elapsed, metrics):
    groups = {}
    for group in GROUPS:
        subset = [r for r in rows if r['group'] == group]
        successful = [r for r in subset if r['status'] == 'ok']
        groups[group] = {'requests': len(subset), 'ok': len(successful), 'failed': len(subset) - len(successful),
                         'ttft_p50_s': quantile([r['ttft_s'] for r in successful], .5),
                         'ttft_p95_s': quantile([r['ttft_s'] for r in successful], .95), 'hit_rate': usage_hit(subset)}
    first, last = metrics[0], metrics[-1]
    comparable = first.get('name') == last.get('name') and first.get('value') is not None and last.get('value') is not None
    delta = last['value'] - first['value'] if comparable else None
    observed = {m['value'] for m in metrics if m.get('value') is not None}
    output = sum(r['output_tokens'] for r in rows) if all(r['output_tokens'] is not None for r in rows) else None
    return {'requests': len(rows), 'ok': sum(r['status'] == 'ok' for r in rows), 'elapsed_s': elapsed,
            'request_throughput': len(rows) / elapsed, 'output_tok_per_s': output / elapsed if output is not None else None,
            'groups': groups, 'overall_usage_hit_rate': usage_hit(rows),
            'overall_metric_delta': delta, 'cache_metric_name': first.get('name') or last.get('name'),
            'cache_metric_type': first.get('type') or last.get('type'), 'cache_metric_changed': len(observed) > 1,
            'cache_metric_before': first.get('value'), 'cache_metric_after': last.get('value'),
            'overall_cache_hit_rate_delta': delta,
            'metric_interpretation': 'end minus start; a gauge delta is a change in rate, not a run-wide hit fraction'}


async def run(prompts_path, output, concurrency, run_id, base='http://localhost:8000/v1', model='Qwen/Qwen3.8-27B', timeout=1800, settle=5):
    if not 1 <= concurrency <= 32:
        raise ValueError('Concurrency must be 1..32')
    raw = prompts_path.read_bytes()
    prompts = [json.loads(line) for line in raw.splitlines() if line]
    if not prompts or len({r['request_id'] for r in prompts}) != len(prompts) or any(r['group'] not in GROUPS for r in prompts):
        raise ValueError('Invalid/duplicate request IDs or groups')
    manifest_path = prompts_path.parent / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    if manifest and manifest['files_sha256'].get(prompts_path.name) != hashlib.sha256(raw).hexdigest():
        raise ValueError('Prompt file SHA-256 differs from manifest')
    output.mkdir(parents=True, exist_ok=False)
    rows, metrics = [], [await scrape(base)]
    stop = asyncio.Event()
    async def poll():
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), 1)
            except TimeoutError:
                metrics.append(await scrape(base))
    poller = asyncio.create_task(poll())
    iterator = iter(enumerate(prompts))
    started = time.perf_counter()
    with (output / 'requests.jsonl').open('w') as log:
        async def worker():
            for index, prompt in iterator:
                row = await request(base, prompt, model, timeout)
                row['dispatch_index'] = index
                row['rehearsal'] = os.environ.get('REHEARSAL') == '1'
                rows.append(row); log.write(json.dumps(row) + '\n'); log.flush()
        try:
            await asyncio.gather(*(worker() for _ in range(concurrency)))
        finally:
            elapsed = time.perf_counter() - started
            stop.set(); await poller
    # Metrics can update on a reporting interval; keep these samples outside throughput timing.
    for _ in range(settle):
        await asyncio.sleep(1); metrics.append(await scrape(base))
    metrics.append(await scrape(base))
    (output / 'metrics.jsonl').write_text(''.join(json.dumps(m) + '\n' for m in metrics))
    summary = summarize(rows, elapsed, metrics)
    summary.update(rehearsal=os.environ.get('REHEARSAL')=='1', run_id=run_id, concurrency=concurrency, prompts_sha256=hashlib.sha256(raw).hexdigest(),
                   fixture=bool(manifest.get('fixture')) if manifest else False, prompt_manifest=manifest, order=[r['request_id'] for r in prompts], model=model, max_output_tokens=256, ignore_eos=True)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def self_test(output):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import random
    import threading
    class Handler(BaseHTTPRequestHandler):
        calls = 0
        def do_GET(self):
            rate = .5 if Handler.calls else 0
            body = f'# TYPE sglang:cache_hit_rate gauge\nsglang:cache_hit_rate {rate}\n'.encode()
            self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_POST(self):
            json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            Handler.calls += 1
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.send_header('Transfer-Encoding', 'chunked'); self.end_headers()
            events = [{'choices': [{'delta': {'role': 'assistant'}}]}, {'choices': [{'delta': {'reasoning_content': 'think'}}]},
                      {'choices': [{'delta': {'content': 'ok'}}]}, {'choices': [], 'usage': {'prompt_tokens': 100, 'completion_tokens': 2, 'prompt_tokens_details': {'cached_tokens': 50}}}, '[DONE]']
            for event in events:
                body = b'data: ' + (event.encode() if isinstance(event, str) else json.dumps(event).encode()) + b'\n\n'
                self.wfile.write(f'{len(body):x}\r\n'.encode() + body + b'\r\n'); self.wfile.flush()
            self.wfile.write(b'0\r\n\r\n'); self.wfile.flush()
        def log_message(self, *_):
            pass
    output.mkdir(parents=True, exist_ok=False)
    prompts = [{'request_id': str(i), 'group': g, 'messages': [{'role': 'user', 'content': f'unique code {i}'}]} for i, g in enumerate(['G1'] * 16 + ['G2'] * 12 + ['G3'] * 8 + ['G4'] * 4)]
    random.Random(6101550).shuffle(prompts)
    path = output / 'prompts.jsonl'; path.write_text(''.join(json.dumps(p) + '\n' for p in prompts))
    manifest={'fixture':True,'server':'local fake streaming server; no model inference','seed':6101550,'group_counts':dict(zip(GROUPS,[16,12,8,4])),'files_sha256':{'prompts.jsonl':hashlib.sha256(path.read_bytes()).hexdigest()}}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        summary = asyncio.run(run(path, output / 'fake-run', 4, 'P0.9-fake', f'http://127.0.0.1:{server.server_port}/v1', settle=0))
        assert summary['ok'] == 40
        assert {g: v['requests'] for g, v in summary['groups'].items()} == dict(zip(GROUPS, [16, 12, 8, 4]))
        assert all(v['hit_rate'] == .5 and v['failed'] == 0 for v in summary['groups'].values())
        assert summary['cache_metric_changed'] and summary['overall_metric_delta'] == .5
        assert summary['order'] == [r['request_id'] for r in prompts]
        print('P0.9 fake streaming server: group tags, seeded order, usage and summaries pass')
    finally:
        server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dry-run', action='store_true'); p.add_argument('--self-test', action='store_true'); p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--prompts', type=Path); p.add_argument('--concurrency', type=int, default=16); p.add_argument('--run-id', default='Kx')
    p.add_argument('--base-url', default='http://localhost:8000/v1'); p.add_argument('--model', default='Qwen/Qwen3.8-27B')
    p.add_argument('--timeout', type=float, default=1800); p.add_argument('--metrics-settle-s', type=int, default=5)
    a = p.parse_args()
    if a.dry_run:
        print(json.dumps({'prompts': str(a.prompts), 'concurrency': a.concurrency, 'run_id': a.run_id, 'stream': True, 'max_tokens': 256, 'ignore_eos': True, 'output': str(a.output_dir), 'group_field_required': True}))
        raise SystemExit(0)
    if a.self_test:
        self_test(a.output_dir)
    else:
        if a.prompts is None:
            p.error('--prompts is required')
        result = asyncio.run(run(a.prompts, a.output_dir, a.concurrency, a.run_id, a.base_url, a.model, a.timeout, a.metrics_settle_s))
        print(json.dumps(result, indent=2))
        if result['ok'] != result['requests']:
            raise SystemExit(1)
