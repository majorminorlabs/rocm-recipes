#!/usr/bin/env python3
"""Section 5b W-MP prompts. Run offline inside the SGLang image with its tokenizer."""
import argparse
import hashlib
import json
import math
import random
import re
from pathlib import Path

ROLES = {
    'G1': 'You are a coder. Implement a small, correct change in the supplied source.',
    'G2': 'You are a test writer. Propose focused tests for the supplied source.',
    'G3': 'You are a reviewer. Review the supplied source for correctness and edge cases.',
    'G4': 'You are a debugger. Find and explain a reproducible defect in the supplied source.',
}
SHARES = [40, 30, 20, 10]
FALLBACK = [2048, 4096, 8192, 16384]
SEED = 6101550


def percentile(values, p):
    values = sorted(values); pos = (len(values) - 1) * p; lo = math.floor(pos)
    return values[lo] + (values[math.ceil(pos)] - values[lo]) * (pos - lo)


def prefix_lengths(paths):
    values, missing = [], 0
    for path in paths:
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row.get('event') != 'response':
                continue
            value = row.get('tokens_cached')
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                values.append(value)
            else:
                missing += 1
    fallback = not values or missing > 0
    return (FALLBACK.copy() if fallback else [int(math.floor(percentile(values, p) / 256 + .5) * 256) for p in (.25, .5, .75, .95)]), {
        'fallback': fallback, 'cached_counts_available': len(values), 'cached_counts_missing': missing,
        'method': 'linear percentiles; nearest 256, half up', 'proxy_logs': [str(p) for p in paths]}


def counts(total):
    base = [total * s // 100 for s in SHARES]
    for i in sorted(range(4), key=lambda i: (-(total * SHARES[i] % 100), i))[:total - sum(base)]:
        base[i] += 1
    return base


def build(tok, atlas, out, logs=(), seed=SEED, rehearsal=False):
    atlas = atlas.resolve()
    lengths, selection = prefix_lengths(logs)
    frozen = json.loads((atlas / 'tasks/FROZEN.json').read_text())
    files, corpus, seen = [], [], set()
    for task in frozen['tasks']:
        folder = atlas / 'tasks' / task['id']
        meta = (folder / 'task.yaml').read_text()
        match = re.search(r'^base:\s*([^\s]+)\s*$', meta, re.M)
        if not match:
            raise ValueError('Missing frozen base: ' + task['id'])
        base = (folder / match[1]).resolve()
        if not base.is_relative_to(folder.resolve()):
            raise ValueError('Unsafe frozen base')
        for path in sorted(base.rglob('*')):
            if (not path.is_file() or path.is_symlink() or path.suffix not in ('.py', '.ts', '.js', '.tsx', '.jsx', '.rs', '.go', '.c', '.cpp', '.h')
                    or any(p.lower() in ('test', 'tests', '__tests__', 'hidden_tests', '.git', 'node_modules') for p in path.relative_to(base).parts)):
                continue
            data = path.read_bytes(); digest = hashlib.sha256(data).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            text = data.decode('utf-8')
            ids = tok.encode(f'\n# source: {path.relative_to(atlas)}\n' + text, add_special_tokens=False)
            files.append({'path': str(path.relative_to(atlas)), 'sha256': digest, 'corpus_start': len(corpus), 'tokens': len(ids)})
            corpus.extend(ids)
    cursor = 0

    def fit(head, tail, target, tolerance=0):
        nonlocal cursor
        available = corpus[cursor:cursor + target + 512]
        need = target - len(tok.encode(head + tail, add_special_tokens=False))
        if need <= 0 or len(available) < need:
            raise ValueError('Prefix too short for role, or frozen source exhausted; no substitute/fallback')
        for _ in range(20):
            text = head + tok.decode(available[:need]) + tail
            actual = len(tok.encode(text, add_special_tokens=False))
            if abs(actual - target) <= tolerance:
                start = cursor; cursor += need
                return text, actual, [start, cursor]
            need += target - actual
            if need <= 0 or need > len(available):
                break
        raise ValueError('Tokenizer cannot meet the requested prefix length exactly')

    prefixes, groups = {}, {}
    for group, target in zip(ROLES, lengths):
        text, actual, source_range = fit(ROLES[group] + '\n\n', '', target)
        prefixes[group] = text
        groups[group] = {'role': ROLES[group], 'percentile': dict(zip(ROLES, [25, 50, 75, 95]))[group],
                         'prefix_tokens': actual, 'source_range': source_range, 'requested_share': SHARES[int(group[-1]) - 1] / 100}
    out.mkdir(parents=True, exist_ok=False)
    hashes, splits, index = {}, {}, 0
    splits_spec = [('wmp-20.jsonl',20,counts(20)),('kx-0.jsonl',8,[2,2,2,2])] if rehearsal else [('wmp-256.jsonl', 256, counts(256)), ('wmp-128.jsonl', 128, counts(128)), ('kx-0.jsonl', 8, [2, 2, 2, 2])]
    for name, n, share in splits_spec:
        rows = []
        for group, amount in zip(ROLES, share):
            for _ in range(amount):
                request_id = f'WMP-{index:04d}'; index += 1
                suffix, actual, source_range = fit('```\n', f'\n```\nTask {request_id}: {ROLES[group]}\n', 1024, 32)
                messages = [{'role': 'system', 'content': prefixes[group]}, {'role': 'user', 'content': suffix}]
                chat = tok.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
                ids = chat['input_ids'] if hasattr(chat, 'keys') else chat
                if ids and isinstance(ids[0], (list, tuple)):
                    ids = ids[0]
                if len(ids) + 256 > 131072:
                    raise ValueError('Derived prefix exceeds study context after suffix/template/output; skip 5b')
                rows.append({'request_id': request_id, 'group': group, 'messages': messages,
                             'suffix_tokens': actual, 'chat_tokens': len(ids), 'source_range': source_range})
        random.Random(seed + n).shuffle(rows)
        body = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows)
        (out / name).write_text(body)
        hashes[name] = hashlib.sha256(body.encode()).hexdigest()
        splits[name] = {'requests': n, 'group_counts': dict(zip(ROLES, share)), 'seed': seed + n, 'order': [r['request_id'] for r in rows]}
    for group, text in prefixes.items():
        name = f'prefix_{group}.txt'; (out / name).write_text(text)
        hashes[name] = hashlib.sha256(text.encode()).hexdigest()
    manifest = {'atlas_commit': '279889b8f42c607344781766503602a8c462f5df', 'frozen_manifest_sha256': hashlib.sha256((atlas / 'tasks/FROZEN.json').read_bytes()).hexdigest(), 'rehearsal':rehearsal, 'fixture':rehearsal, 'workload': 'W-MP', 'model': 'Qwen/Qwen3.8-27B', 'seed': seed, 'groups': groups,
                'prefix_selection': selection, 'files_sha256': hashes, 'splits': splits, 'output_tokens': 256,
                'suffix_target_tokens': 1024, 'suffix_tolerance_tokens': 32,
                'share_method': 'largest remainder integer allocation; G order breaks ties',
                'source_files': files, 'source_tokens_used': cursor, 'source_tokens_available': len(corpus)}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--atlas', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--proxy-logs', type=Path, nargs='*', default=[]); p.add_argument('--model', default='Qwen/Qwen3.8-27B')
    p.add_argument('--rehearsal', action='store_true'); p.add_argument('--dry-run', action='store_true'); p.add_argument('--revision', required=True); p.add_argument('--seed', type=int, default=SEED)
    a = p.parse_args()
    if a.dry_run:
        lengths, selection = prefix_lengths(a.proxy_logs)
        print(json.dumps({'prefix_lengths': lengths, 'selection': selection, 'counts_256': counts(256), 'counts_128': counts(128), 'kx0': [2, 2, 2, 2], 'seed': a.seed}))
        raise SystemExit(0)
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.model, revision=a.revision, local_files_only=True)
    manifest = build(tok, a.atlas, a.output, a.proxy_logs, a.seed, a.rehearsal)
    manifest.update(tokenizer_revision=a.revision, tokenizer_class=type(tok).__name__)
    (a.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
