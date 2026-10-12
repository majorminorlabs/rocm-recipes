# Method: FP8 vs BF16 on one MI300X

## Question

Is FP8 faster than BF16 for serving a 30B coding model on one AMD Instinct MI300X, and what does it cost in accuracy?

## Setup

- **GPU:** 1× AMD Instinct MI300X (192 GB), AMD Developer Cloud
- **Engine:** vLLM in the `rocm/vllm` container (digest recorded in `results/env/`); llama.cpp built from source with HIP for gfx942 for one comparison
- **Server:** `--max-model-len 16384`

| Key | Model | Used in |
|---|---|---|
| M1 | Qwen/Qwen3-Coder-30B-A3B-Instruct (BF16) | R2, R3 |
| M2 | Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8 | R2, R3 |
| M3 | Qwen/Qwen2.5-72B-Instruct | R2 |
| M4 | openai/gpt-oss-120b | R2, R3 |
| M5 | unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF, Q4_K_M | R4 |

## What was measured

| Recipe | What | How |
|---|---|---|
| R1 | Setup time | Minutes from a fresh droplet to the first answer |
| R2 | Serving throughput | `vllm bench serve`, random prompts, 1,024 tokens in, 256 out, concurrency 1, 8, 32, 64, `num_prompts = max(32, 8 × concurrency)` |
| R3 | Accuracy | lm-eval `gsm8k`, 250 questions, against the running server |
| R4 | llama.cpp comparison | `llama-bench`, all layers on GPU, prompt 512, generation 128, 3 repetitions |

Repeats: concurrency 8 three extra times for M1 and M2, and three warm single-user runs each, after the first single-user runs showed a cold-start effect.

## How the study ran

1. **Plan first.** A written plan fixed the question, the configurations, every command, the stop rules and the budget before any GPU time.
2. **Scripts reviewed before GPU time.** An AI agent wrote and dry-ran the scripts locally, and a second reviewer checked them before a server was created.
3. **Unattended execution.** The agent ran the plan on a fresh AMD Developer Cloud MI300X droplet, recorded every step, and synced results back after each one.
4. **Hard cost limits.** A deterministic watchdog on a separate machine destroyed the droplet at a fixed deadline, whatever state the run was in. The agent also destroyed the droplet as soon as no work remained.
5. **Provenance on every run.** Each `meta.json` records the container digest (or llama.cpp commit), engine version, model revision, ROCm version and full server arguments.
6. **Failures kept.** Failed runs keep their metadata and logs. Problems hit along the way are in `notes/friction.md`.

Three sessions, 2.88 GPU-hours, about $5.73 at $1.99/GPU-hour.

## Known deviations

- The container was pulled as `rocm/vllm:latest`; the digest actually used is recorded per session in `results/env/`.
- lm-eval ran in a separate `python:3.12-slim` container because it would not import inside the vLLM container.
- gpt-oss-120b sometimes returned no final answer; empty answers were scored as wrong.
