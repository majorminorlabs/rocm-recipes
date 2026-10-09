#!/usr/bin/env python3
"""Small standalone needle retrieval check; not the RULER harness.

Two modes:
  simple (default): one needle in a repeated noise haystack (RULER niah_single_1 style).
  --hard: one target needle plus 3 distractor needles with other keys, in real text
          read from --haystack-file (RULER niah_multikey style).
"""
import argparse
import datetime
import hashlib
import json
import os
import random
import statistics
import subprocess
import time
import urllib.request

WORDS = 'amber birch cedar dawn ember frost grove harbor indigo juniper kestrel lunar maple nectar olive pebble quartz river silver thistle umber violet willow xenon yarrow zephyr acorn beacon copper drift echo fern galaxy hollow island jasper kernel meadow north opal prairie quiet robin spruce timber unity valley winter'.split()
SENTENCES = ['The grass is green.', 'The sky is blue.', 'The sun is yellow.',
             'Here we go.', 'There and back again.']
BASE = 'http://localhost:8000'


def load_text_sentences(path):
    """Split a plain-text file into sentences. Strips Project Gutenberg header/footer if present."""
    with open(path, encoding='utf-8', errors='replace') as f:
        text = f.read()
    start = text.find('*** START OF')
    if start != -1:
        text = text[text.find('\n', start) + 1:]
    end = text.find('*** END OF')
    if end != -1:
        text = text[:end]
    text = ' '.join(text.split())
    parts = [p.strip() for p in text.replace('? ', '?|').replace('! ', '!|').replace('. ', '.|').split('|')]
    sentences = [p for p in parts if len(p) > 1]
    if len(sentences) < 100:
        raise ValueError(f'haystack file has too few sentences: {len(sentences)}')
    return sentences


def make_needles(seed, hard):
    r = random.Random(seed)
    if not hard:  # same draws as session 1, so simple-mode prompts are byte-identical
        keys = [r.choice(WORDS)]
        numbers = [str(r.randint(1_000_000, 9_999_999))]
    else:
        keys = r.sample(WORDS, 4)
        numbers = [str(r.randint(1_000_000, 9_999_999)) for _ in keys]
        while len(set(numbers)) != len(numbers):
            numbers = [str(r.randint(1_000_000, 9_999_999)) for _ in keys]
    needles = [f'One of the special magic numbers for {k} is: {n}.' for k, n in zip(keys, numbers)]
    return keys, numbers, needles


def build_prompt(target, depth, seed, counter=None, source=None, hard=False):
    """Return (prompt, needles, keys, numbers, sentence_count, target_pos).

    keys[0]/numbers[0]/needles[0] is the target. In hard mode the 3 distractors
    sit at depth+0.25, +0.5 and +0.75 (wrapping), so they never share the target's spot.
    """
    source = source or SENTENCES
    keys, numbers, needles = make_needles(seed, hard)
    depths = [depth] + ([(depth + k) % 1.0 for k in (.25, .5, .75)] if hard else [])

    def prompt(n):
        sentences = (source * (n // len(source) + 1))[:n]
        placed = sorted(zip(depths, needles), key=lambda x: x[0], reverse=True)
        haystack = sentences.copy()
        positions = {}
        for d, nd in placed:  # insert deepest first so earlier indexes stay valid
            pos = max(0, min(len(haystack), round(len(sentences) * d)))
            haystack.insert(pos, nd)
            positions[nd] = pos
        text = ' '.join(haystack)
        question = ('\nWhat is the special magic number for ' + keys[0] +
                    ' mentioned in the provided text? Answer with the number only.')
        return text + question, len(haystack), haystack.index(needles[0])

    if counter is None:
        counter = lambda text: len(text.split())
    lo, hi = target - 512, target - 128
    n = max(1, target // 5)
    for _ in range(100):
        full, _, _ = prompt(n)
        count = counter(full)
        if lo <= count <= hi:
            break
        n = max(1, round(n * ((lo + hi) / 2) / count))
    else:
        raise ValueError('Could not size prompt in requested token window')
    full, sentence_count, pos = prompt(n)
    return full, needles, keys, numbers, sentence_count, pos


def call(path, payload):
    req = urllib.request.Request(BASE + path, json.dumps(payload).encode(),
                                 {'Content-Type': 'application/json'})
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=1800) as response:
        return json.load(response), time.monotonic() - start


def grade(content, number):
    return bool(content is not None and number in content)


def self_test():
    fake = lambda text: int(len(text.split()) * 1.3)
    for depth in (.1, .5, .9):
        prompt, needles, _, numbers, count, pos = build_prompt(2000, depth, 1, fake)
        text = prompt.split('\nWhat is', 1)[0]
        before = text.split(needles[0], 1)[0]
        assert prompt.count(needles[0]) == 1
        assert not before or before.endswith('. ')
        assert abs(pos - (count - 1) * depth) < count * .12
        assert grade('answer ' + numbers[0], numbers[0]) and not grade('0000000', numbers[0])
        assert not grade(None, numbers[0])
    # hard mode with a synthetic "real text" source
    src = [f'Sentence number {i} talks about the weather and the road.' for i in range(500)]
    for depth in (.1, .5, .9):
        prompt, needles, keys, numbers, count, pos = build_prompt(4000, depth, 2, fake, src, hard=True)
        assert len(set(keys)) == 4 and len(set(numbers)) == 4
        for nd in needles:
            assert prompt.count(nd) == 1, 'every needle appears exactly once'
        assert keys[0] in prompt.rsplit('\nWhat is', 1)[1], 'question asks for the target key'
        assert abs(pos - (count - 1) * depth) < count * .12
    print('needle self-test passed')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--run-id')
    parser.add_argument('--target-tokens', type=int)
    parser.add_argument('--max-tokens', type=int)
    parser.add_argument('--reasoning-effort', choices=['low'])
    parser.add_argument('--hard', action='store_true', help='real-text haystack plus 3 distractor needles')
    parser.add_argument('--haystack-file', help='plain-text file for --hard')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.run_id or not args.target_tokens or not args.max_tokens:
        parser.error('--run-id, --target-tokens and --max-tokens required')
    if args.hard and not args.haystack_file:
        parser.error('--hard requires --haystack-file')
    recipe = 'L3H' if args.hard else 'L3'
    out = f'results/raw/{recipe}/{args.run_id}'
    if args.dry_run:
        print(f'POST {BASE}/tokenize, then 9 requests to {BASE}/v1/chat/completions; mode={"hard" if args.hard else "simple"}; output {out}/')
        return
    if not all(ch.isalnum() or ch in '._-' for ch in args.run_id):
        parser.error('invalid run-id')
    source, haystack_sha = None, None
    if args.hard:
        source = load_text_sentences(args.haystack_file)
        with open(args.haystack_file, 'rb') as f:
            haystack_sha = hashlib.sha256(f.read()).hexdigest()
    os.makedirs(out, exist_ok=True)
    cfg = json.load(open('logs/current_server.json'))
    pins = json.loads(subprocess.check_output([os.path.join(os.path.dirname(__file__), 'pins.sh'),
                                               cfg['hf_repo']], text=True))
    started = datetime.datetime.now().astimezone().isoformat()
    rows = []
    for depth in (.1, .5, .9):
        for seed in (1, 2, 3):
            row = {'depth': depth, 'seed': seed, 'correct': False}
            try:
                model = cfg['hf_repo']
                prompt, needles, keys, numbers, _, _ = build_prompt(
                    args.target_tokens, depth, seed,
                    lambda text: call('/tokenize', {'model': model, 'prompt': text})[0]['count'],
                    source, args.hard)
                row.update(key=keys[0], number=numbers[0])
                if args.hard:
                    row.update(distractor_keys=keys[1:], distractor_numbers=numbers[1:])
                result, latency = call('/v1/chat/completions', {
                    'model': model, 'messages': [{'role': 'user', 'content': prompt}],
                    'temperature': 0, 'seed': seed, 'max_tokens': args.max_tokens,
                    **({'reasoning_effort': 'low'} if args.reasoning_effort else {})})
                choice = result.get('choices', [{}])[0]
                content = (choice.get('message') or {}).get('content')
                usage = result.get('usage') or {}
                row.update(prompt_tokens=usage.get('prompt_tokens'),
                           completion_tokens=usage.get('completion_tokens'),
                           finish_reason=choice.get('finish_reason'), latency_s=latency,
                           content=content, correct=grade(content, numbers[0]))
                if args.hard:
                    row['distractor_hit'] = any(grade(content, n) for n in numbers[1:])
            except Exception as exc:
                row['error'] = str(exc)
            rows.append(row)
            with open(out + '/needle.json', 'w') as f:
                json.dump(rows, f, indent=2)
                f.write('\n')
    counts = [row['prompt_tokens'] for row in rows if row.get('prompt_tokens') is not None]
    errors = [row for row in rows if 'error' in row]
    meta = {'run_id': args.run_id, 'recipe': recipe, 'model': cfg['hf_repo'],
            'weights_precision': cfg['weights_precision'],
            'kv_cache_dtype': cfg['kv_cache_dtype'],
            'max_model_len': int(cfg['max_model_len']), 'server_args': cfg['server_args'],
            'engine': 'vllm',
            'method': ('multi-key: real-text haystack + 3 distractor needles, own script'
                       if args.hard else 'single-needle, RULER-style noise haystack, own script'),
            'haystack_file': os.path.basename(args.haystack_file) if args.hard else None,
            'haystack_sha256': haystack_sha,
            'target_tokens': args.target_tokens, 'max_tokens': args.max_tokens,
            'needle_correct': sum(row['correct'] for row in rows),
            'needle_total': len(rows),
            'needle_errors': len(errors),
            'distractor_hits': sum(1 for row in rows if row.get('distractor_hit')) if args.hard else None,
            'mean_prompt_tokens': statistics.mean(counts) if counts else None,
            'started_at': started,
            'finished_at': datetime.datetime.now().astimezone().isoformat(),
            'status': 'failed' if len(errors) == len(rows) else 'ok',
            'error': '; '.join(row['error'] for row in errors) if len(errors) == len(rows) else ''}
    meta.update(pins)
    with open(out + '/meta.json', 'w') as f:
        json.dump(meta, f, indent=2)
        f.write('\n')


if __name__ == '__main__':
    main()
