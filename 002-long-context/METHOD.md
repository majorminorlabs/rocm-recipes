# Method: long context on one MI300X

## Question

How much context fits on one 192 GB MI300X, how fast does it answer at long lengths, and can the model still find a fact far into the prompt?

## Setup

- **GPU:** 1× AMD Instinct MI300X (192 GB), AMD Developer Cloud
- **Engine:** vLLM in the `rocm/vllm` container (digest recorded in `results/env/`), prefix caching off
- **Models, each at its native context:**

| Key | Model | Window |
|---|---|---|
| M1 | Qwen/Qwen3-Coder-30B-A3B-Instruct | 262,144 |
| M4 | openai/gpt-oss-120b | 131,072 |
| M6 | Llama-3.3-70B-Instruct (BF16, ungated mirror) | 131,072 |

Each model ran with a BF16 KV cache and, where it fit the session, an FP8 KV cache.

## What was measured

| Recipe | What | How |
|---|---|---|
| L0 | Capacity | KV cache size in tokens and maximum concurrent users at full length, from the server log |
| L1 | Single-user speed by length | `vllm bench serve`, random prompts from 1K up to the window minus 4,096, 256 tokens out |
| L2 | Sharing | 32K prompts with 1, 4, 8 and 16 users |
| L3 | Retrieval, simple | One hidden number in a repeated-sentence haystack, at 10%, 50% and 90% depth |
| L3H | Retrieval, hard | One hidden number plus three decoys in real text (*War and Peace*, Project Gutenberg, sha256 in `notes/haystack_sha256.txt`) |

Every benchmark ran a warmup first. Retrieval used a small script modeled on RULER's single and multi-key tasks, not the RULER harness.

## How the study ran

1. **Plan first.** A written plan fixed the question, the configurations, every command, the stop rules and the budget before any GPU time.
2. **Scripts reviewed before GPU time.** An AI agent wrote and dry-ran the scripts locally, and a second reviewer checked them before a server was created.
3. **Unattended execution.** The agent ran the plan on a fresh AMD Developer Cloud MI300X droplet, recorded every step, and synced results back after each one.
4. **Hard cost limits.** A deterministic watchdog on a separate machine destroyed the droplet at a fixed deadline, whatever state the run was in. The agent also destroyed the droplet as soon as no work remained.
5. **Provenance on every run.** Each `meta.json` records the container digest (or llama.cpp commit), engine version, model revision, ROCm version and full server arguments.
6. **Failures kept.** Failed runs keep their metadata and logs. Problems hit along the way are in `notes/friction.md`.

Two sessions, 8.8 GPU-hours, $17.56 at $1.99/GPU-hour.

## Known deviations

- The container was pulled as `rocm/vllm:latest`; digests per session are in `results/env/`.
- The second session added the hard retrieval test and FP8 cache runs that didn't fit the first.
