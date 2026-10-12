#!/usr/bin/env python3
"""Build the W1 coding-agent prompt set for ROCm Recipes 005.

Every prompt = chat template( SHARED PREFIX + task header + unique Django source ).
- SHARED PREFIX: a fixed agent system prompt + Django's README.rst + docs/intro/overview.txt,
  cut to exactly PREFIX_TOKENS tokens. Byte-identical in every prompt.
- Unique source: consecutive top-level blocks from django/**/*.py, consumed in order. A block
  (or the cut-off tail of one) is never used again, so prompts share nothing but the prefix.
- Total length per prompt after the chat template: TARGET +/- TOL tokens.
Runs inside the vLLM container (offline tokenizer). Stdlib + transformers only.
"""
import argparse
import hashlib
import json
import os
import re
import tarfile
import tempfile
import urllib.request
from pathlib import Path

PREFIX_TOKENS, TARGET, TOL = 1536, 4096, 32
SYSTEM = """You are a senior software engineer working as an autonomous coding agent inside a large Python web framework repository.

Tools available to you: read_file(path), search(pattern), run_tests(selector), apply_patch(diff). You call tools by writing the call on its own line. You never invent file contents you have not read.

Working rules:
1. Preserve every public API and its behavior unless the task explicitly asks for a change.
2. Follow the repository's existing style: naming, docstring format, import order, error messages.
3. Make the smallest change that fully solves the task. Do not reformat unrelated code.
4. Treat edge cases explicitly: empty inputs, None, unicode, timezone-aware values, very large inputs.
5. When you write tests, use pytest, keep each test focused on one behavior, and name it after that behavior.
6. When you find a bug, state the input that triggers it, the wrong result, and the correct result.
7. When you refactor, keep behavior identical and say why each change improves readability.
8. When you add type hints, use the most specific types the code actually supports.

Output format: start with a one-paragraph plan, then the code or analysis, then a short list of risks.

Repository overview follows.
"""
TASKS = ['Write pytest tests for the source below.',
         'Find and explain one bug or unhandled edge case in the source below.',
         'Refactor the source below for readability without changing behavior.',
         'Add precise type hints and docstrings to the source below.']
SPLITS = [('w1-c1.jsonl', 8), ('w1-c4.jsonl', 16), ('w1-c8.jsonl', 32), ('w1-c16.jsonl', 64), ('w1-c8-r2.jsonl', 32)]
TOTAL = 192  # 152 used by SPLITS, 40 spare
SKIP = re.compile(r'/(tests?|migrations|locale)/')


def source_blocks(tf, root):
    """Top-level def/class blocks from django/**/*.py in sorted path order."""
    names = sorted(m.name for m in tf.getmembers()
                   if m.isfile() and m.name.startswith(root + '/django/') and m.name.endswith('.py')
                   and not SKIP.search(m.name))
    for name in names:
        text = tf.extractfile(name).read().decode('utf-8', errors='replace')
        rel = name[len(root) + 1:]
        for part in re.split(r'(?=^(?:async\s+def|def|class)\s)', text, flags=re.M):
            if part.strip():
                yield rel, part.rstrip() + '\n'


def build(tok, tarball, out_dir, tokenizer_revision=None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tar_sha = hashlib.sha256(Path(tarball).read_bytes()).hexdigest()

    def count(content):
        encoded = tok.apply_chat_template([{'role': 'user', 'content': content}], tokenize=True,
                                          add_generation_prompt=True)
        # Transformers versions used by some serving images return a BatchEncoding
        # mapping here; len(mapping) counts fields (input_ids, attention_mask), not tokens.
        ids = encoded['input_ids'] if hasattr(encoded, 'keys') else encoded
        if hasattr(ids, 'shape') and len(ids.shape) > 1:
            return int(ids.shape[-1])
        if ids and isinstance(ids[0], (list, tuple)):
            return len(ids[0])
        return len(ids)

    def render(content):
        return tok.apply_chat_template([{'role': 'user', 'content': content}], tokenize=False,
                                       add_generation_prompt=True)

    with tarfile.open(tarball, 'r:gz') as tf:
        root = tf.getmembers()[0].name.split('/')[0]
        readme = tf.extractfile(f'{root}/README.rst').read().decode('utf-8', errors='replace')
        overview = tf.extractfile(f'{root}/docs/intro/overview.txt').read().decode('utf-8', errors='replace')
        prefix_ids = tok.encode(SYSTEM + '\n' + readme + '\n' + overview, add_special_tokens=False)
        if len(prefix_ids) < PREFIX_TOKENS:
            raise SystemExit(f'prefix source only {len(prefix_ids)} tokens, need {PREFIX_TOKENS}')
        prefix = tok.decode(prefix_ids[:PREFIX_TOKENS])
        blocks = list(source_blocks(tf, root))

    cursor = 0
    prompts, meta = [], []
    for i in range(TOTAL):
        content = prefix + f'\n\n=== TASK {i + 1} ===\n{TASKS[i % 4]}\n\n=== SOURCE ===\n'
        files = []
        while True:
            if cursor >= len(blocks):
                raise SystemExit(f'ran out of Django source at prompt {i}; refusing to reuse a block')
            rel, block = blocks[cursor]
            piece = f'# file: {rel}\n{block}' if not files or files[-1] != rel else block
            if count(content + piece) <= TARGET + TOL:
                content += piece
                files.append(rel)
                cursor += 1
                if count(content) >= TARGET - TOL:
                    break
                continue
            # Next block overflows: take as many of its lines as fit, then drop the rest of it.
            lines = piece.splitlines(keepends=True)
            lo, hi = 0, len(lines)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if count(content + ''.join(lines[:mid])) <= TARGET + TOL:
                    lo = mid
                else:
                    hi = mid - 1
            content += ''.join(lines[:lo])
            files.append(rel)
            cursor += 1
            break
        n = count(content)
        if not (TARGET - TOL <= n <= TARGET + TOL):
            raise SystemExit(f'prompt {i} is {n} tokens, outside {TARGET}+/-{TOL}')
        text = render(content)
        prompts.append(text)
        meta.append({'index': i, 'tokens': n, 'task': TASKS[i % 4], 'files': sorted(set(files))})

    if len(set(prompts)) != len(prompts):
        raise SystemExit('duplicate prompt generated')
    ids = [tok.encode(p, add_special_tokens=False) for p in prompts]
    shared = min(len(os.path.commonprefix([ids[0], x])) for x in ids[1:])

    offset, hashes = 0, {}
    for name, n in SPLITS:
        body = ''.join(json.dumps({'prompt': p}, ensure_ascii=False) + '\n' for p in prompts[offset:offset + n])
        (out / name).write_text(body, encoding='utf-8')
        hashes[name] = hashlib.sha256(body.encode()).hexdigest()
        offset += n
    tokens = [m['tokens'] for m in meta]
    manifest = {'repo_tarball_sha256': tar_sha, 'tokenizer_revision': tokenizer_revision,
                'prefix_tokens_requested': PREFIX_TOKENS, 'shared_prefix_tokens_min': shared,
                'target_tokens': TARGET, 'tolerance': TOL, 'prompts_built': TOTAL,
                'source_blocks_used': cursor, 'source_blocks_available': len(blocks),
                'token_count': {'min': min(tokens), 'max': max(tokens), 'mean': sum(tokens) / len(tokens)},
                'files_sha256': hashes, 'splits': dict(SPLITS), 'prompts': meta}
    (out / 'prompts_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


class FakeTok:
    """Whitespace tokenizer for --self-test: one token per whitespace-separated word."""
    def encode(self, text, add_special_tokens=False):
        return text.split()

    def decode(self, ids):
        return ' '.join(ids)

    def apply_chat_template(self, msgs, tokenize=True, add_generation_prompt=True):
        text = '<|im_start|>user\n' + msgs[0]['content'] + '<|im_end|>\n<|im_start|>assistant\n'
        return self.encode(text) if tokenize else text


def self_test():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / 'django-5.1.4'
        (root / 'docs/intro').mkdir(parents=True)
        (root / 'README.rst').write_text('Django readme word ' * 300)
        (root / 'docs/intro/overview.txt').write_text('overview text word ' * 600)
        for f in range(80):
            pkg = root / 'django' / f'mod{f:02d}'
            pkg.mkdir(parents=True)
            body = ''.join(f'def func_{f}_{k}(x):\n' + ''.join(f'    v{j} = x + {j}  # line {f} {k} {j}\n' for j in range(12)) + '    return x\n\n' for k in range(60))
            (pkg / 'core.py').write_text(body)
        (root / 'django/tests').mkdir()
        (root / 'django/tests/test_x.py').write_text('def test_skip():\n    pass\n' * 50)
        tarball = Path(d) / 'src.tar.gz'
        with tarfile.open(tarball, 'w:gz') as tf:
            tf.add(root, arcname='django-5.1.4')
        man = build(FakeTok(), tarball, Path(d) / 'out', 'fake')
        lines = {}
        for name, n in SPLITS:
            rows = [json.loads(x)['prompt'] for x in (Path(d) / 'out' / name).read_text().splitlines()]
            assert len(rows) == n, name
            for r in rows:
                assert r not in lines, 'prompt reused across files'
                lines[r] = name
        assert man['shared_prefix_tokens_min'] >= PREFIX_TOKENS, man['shared_prefix_tokens_min']
        assert TARGET - TOL <= man['token_count']['min'] and man['token_count']['max'] <= TARGET + TOL
        assert not any('tests' in f for m in man['prompts'] for f in m['files']), 'tests/ not skipped'
        # no source line appears in two prompts
        seen = {}
        for name in lines:
            for ln in name.split('=== SOURCE ===')[1].splitlines():
                if '# line' in ln:
                    assert ln not in seen, f'source line reused: {ln}'
                    seen[ln] = 1
    print('make_code_prompts self-test passed: 152 prompts in 5 files, no reuse, '
          f'shared prefix >= {PREFIX_TOKENS} tokens, lengths in range, tests/ skipped')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--self-test', action='store_true')
    ap.add_argument('--repo-tarball', default=os.environ.get('CODE_REPO_TARBALL',
                    'https://codeload.github.com/django/django/tar.gz/refs/tags/5.1.4'))
    ap.add_argument('--output-dir', default='results/prompts')
    ap.add_argument('--tokenizer', default='Qwen/Qwen3-Coder-30B-A3B-Instruct')
    a = ap.parse_args()
    if a.self_test:
        self_test()
        return
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.tokenizer, local_files_only=True)
    rev = None
    try:
        from huggingface_hub import try_to_load_from_cache
        path = try_to_load_from_cache(a.tokenizer, 'tokenizer.json')
        rev = Path(path).parent.name if isinstance(path, str) else None
    except Exception:
        pass
    out = Path(a.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    tarball = out / 'django-5.1.4.tar.gz'
    if not tarball.exists():
        urllib.request.urlretrieve(a.repo_tarball, tarball)
    man = build(tok, tarball, out, rev)
    print(json.dumps({k: v for k, v in man.items() if k != 'prompts'}, indent=2))


if __name__ == '__main__':
    main()
