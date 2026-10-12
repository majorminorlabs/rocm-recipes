# Method: performance autopsy on MI300X

## Question

For the two best setups from study 004, how much speed do the documented tuning knobs still leave on the table, for agent-style traffic and for long prompts?

## Which setups

A script scored every 004 setup by the geometric mean of three 004 results: single-user decode at 32K, 16 users with 1K prompts, and 16 users with 32K prompts. It took the best setup from each of the two highest-scoring engines. Eligibility required the 16-user runs, all runs passing, and at least 7/9 on the needle test. Result: SGLang with defaults (SD) and vLLM with AITER attention (VT). The 004 inputs it used are copied, with checksums, in `inputs/from-004/`.

## Setup

- **GPU:** 1× AMD Instinct MI300X (192 GB), AMD Developer Cloud
- **Model:** Qwen/Qwen3-Coder-30B-A3B-Instruct, BF16, 131,072-token window
- **Builds:** the same pinned vLLM and SGLang images as 004
- **Load generator:** `vllm bench serve` in its own container, as in 004, with 50th, 95th and 99th percentiles recorded
- **Sampling during each run, once per second:** VRAM, KV cache usage, preemptions or retractions, and prefix-cache hit rate from each engine's `/metrics`

## Workloads

| | What | How |
|---|---|---|
| W1 | Agent traffic | 1, 4, 8 and 16 users. Each request: 1,536 shared tokens plus 2,560 unique tokens, 512 tokens out. Random tokens (see deviations) |
| W2 | Long prompts | One user at 32K, 64K and 128K; then 4, 8, 16 users at 64K and 2, 4, 8 users at 128K. 256 tokens out |

## Knobs

Each knob was tested alone, then all three together. The baseline (B) is the 004 setup unchanged, with prefix caching off.

| | vLLM (VT) | SGLang (SD) | Source |
|---|---|---|---|
| K1 | `VLLM_ROCM_USE_AITER=1` | `--mem-fraction-static 0.79` (computed from the baseline log: leave ~8 GB free) | AMD ROCm vLLM V1 optimization guide; SGLang hyperparameter tuning docs |
| K2 | `--max-num-batched-tokens 16384` | `--chunked-prefill-size 32768` (2× baseline) | Same |
| K3 | Prefix caching on | Radix cache on, `--schedule-policy lpm` | vLLM automatic prefix caching docs; SGLang docs |
| T | K1 + K2 + K3 | K1 + K2 + K3 | |

A repeat of the baseline 8-user run gives the noise band. `results/deltas.csv` holds every knob-vs-baseline comparison.

## How the study ran

1. **Plan first.** A written plan fixed the question, the configurations, every command, the stop rules and the budget before any GPU time.
2. **Scripts reviewed before GPU time.** An AI agent wrote and dry-ran the scripts locally, and a second reviewer checked them before a server was created.
3. **Unattended execution.** The agent ran the plan on a fresh AMD Developer Cloud MI300X droplet, recorded every step, and synced results back after each one.
4. **Hard cost limits.** A deterministic watchdog on a separate machine destroyed the droplet at a fixed deadline, whatever state the run was in. The agent also destroyed the droplet as soon as no work remained.
5. **Provenance on every run.** Each `meta.json` records the container digest (or llama.cpp commit), engine version, model revision, ROCm version and full server arguments.
6. **Failures kept.** Failed runs keep their metadata and logs. Problems hit along the way are in `notes/friction.md`.

Two sessions, 7.30 GPU-hours, $14.54 at $1.99/GPU-hour. The second session reran vLLM's baseline in full on a new server and ran vLLM's K3 and T. vLLM's K1 and K2 are compared with the first session's baseline, K3 and T with the second's. The two baselines agreed within about 2%.

## Known deviations

- **W1 used random tokens, not code.** The plan built prompts from Django 5.1.4's source, but this build of the load generator lacked the option to send pre-formatted prompts, so W1 used its documented fallback: random tokens with the same 1,536-token shared prefix.
- About 1h45 of the first session went to building those prompts, because of a bug in the prompt builder. They were not used.
- vLLM's first-token percentiles were noisy at 4 to 8 users (two identical runs: 2.0 s and 0.8 s at the 95th percentile), so the write-up uses its throughput and single-user times.
- GPU partitioning was checked, not changed: the VM reports a single compute partition (SPX) and one memory domain (NPS1).
