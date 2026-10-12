# Method: AITER and long-context decoding on MI300X

## Question

Study 002 found Qwen3-Coder decoding at 1.1 tok/s at 256K, with vLLM falling back from its custom attention kernel. Which change fixes it: a smaller window, AITER attention, or AMD's AITER master switch?

## Setup

- **GPU:** 1× AMD Instinct MI300X (192 GB), AMD Developer Cloud
- **Engine:** vLLM 0.29.1, `rocm/vllm@sha256:e0ea9a10b729573ea8598bdc073bda0ea382fe1037eec7c0761b6fa7f46baaf4` (the same digest as 002's last session)
- **Model:** Qwen/Qwen3-Coder-30B-A3B-Instruct, BF16, prefix caching off

| Config | Change | Window |
|---|---|---|
| A | None | 262,144 |
| B | None | 131,072 |
| C | `--attention-backend ROCM_AITER_UNIFIED_ATTN` | 262,144 |
| D | `VLLM_ROCM_USE_AITER=1` | 262,144 |
| E | Config C plus `--kv-cache-dtype fp8` | 262,144 |

## What was measured

For each config: KV capacity and the attention and MoE kernels actually selected (from the server log, saved as `backend.txt`), a discarded prewarm run, single-user speed at 1K, 32K, ~128K and 256K, 32K prompts with 1 to 16 users, and the hard retrieval test from 002.

A second session repeated the speed runs on a fresh server and ran 30 retrieval trials per key config (three depths × ten different numbers), because 9 trials could not separate the configs.

## How the study ran

1. **Plan first.** A written plan fixed the question, the configurations, every command, the stop rules and the budget before any GPU time.
2. **Scripts reviewed before GPU time.** An AI agent wrote and dry-ran the scripts locally, and a second reviewer checked them before a server was created.
3. **Unattended execution.** The agent ran the plan on a fresh AMD Developer Cloud MI300X droplet, recorded every step, and synced results back after each one.
4. **Hard cost limits.** A deterministic watchdog on a separate machine destroyed the droplet at a fixed deadline, whatever state the run was in. The agent also destroyed the droplet as soon as no work remained.
5. **Provenance on every run.** Each `meta.json` records the container digest (or llama.cpp commit), engine version, model revision, ROCm version and full server arguments.
6. **Failures kept.** Failed runs keep their metadata and logs. Problems hit along the way are in `notes/friction.md`.

Two sessions, 6.9 GPU-hours, $13.70 at $1.99/GPU-hour.
