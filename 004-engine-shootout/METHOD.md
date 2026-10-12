# Method: engine shootout on one MI300X

## Question

On one MI300X, which engine and which settings serve Qwen3-Coder fastest: vLLM, SGLang or llama.cpp, each with its defaults and with one AMD-specific change?

## Setup

- **GPU:** 1× AMD Instinct MI300X (192 GB), AMD Developer Cloud
- **Model:** Qwen/Qwen3-Coder-30B-A3B-Instruct, BF16 (llama.cpp: the BF16 GGUF from unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF)
- **Window:** 131,072 tokens on every engine
- **Pinned builds** (see `config.env.example`):
  - vLLM 0.29.1, `rocm/vllm@sha256:e0ea9a10…` (same as 003)
  - SGLang 0.5.21, `lmsysorg/sglang:v0.5.21-rocm10-mi30x` by digest
  - llama.cpp commit `06cad0b9e77315bd2930bd4f70a6d7b37b2a01c1`, built with HIP for gfx942

| Config | Engine | Setting |
|---|---|---|
| VD | vLLM | Defaults |
| VT | vLLM | `--attention-backend ROCM_AITER_UNIFIED_ATTN` |
| SD | SGLang | Image defaults (the image sets `SGLANG_USE_AITER=1`) |
| SX | SGLang | `SGLANG_USE_AITER=0` |
| LC1 | llama.cpp | `-np 1 -c 131072` |
| LC4 | llama.cpp | `-np 4 -c 139264` (34,816 per slot) |

## Fairness rules

- **One load generator for every engine:** `vllm bench serve` from the vLLM image, in its own container, against each engine's OpenAI-compatible endpoint on the same port.
- **Prefix caching off** everywhere (`--no-enable-prefix-caching`, `--disable-radix-cache`).
- **Same prompts per test cell on every engine, different prompts for every other cell.** The random seed is a hash of the run ID with the config removed, so no engine can reuse cached work from an earlier run.
- **Full-length replies enforced:** a run whose replies average under 95% of the requested length is marked `short_output` and excluded.

## What was measured

| Recipe | What |
|---|---|
| L0 | KV capacity, VRAM, and the attention and MoE kernels actually selected (`backend.txt`) |
| L1 | One user at 1K, 32K and 126,976 tokens, 256 out |
| L2 | 1K prompts with 1 to 128 users; 32K prompts with 1 to 16 users (llama.cpp: up to its slot count) |
| L3H | The hard needle test from 003 at 32K. Prompts were built once and replayed byte-for-byte on every engine |

Extras: SGLang with its full 262K window (1 user, 32K and 258K), and a dense model check (Qwen/Qwen3-32B, VT vs SD). Repeats of two cells per config.

## How the study ran

1. **Plan first.** A written plan fixed the question, the configurations, every command, the stop rules and the budget before any GPU time.
2. **Scripts reviewed before GPU time.** An AI agent wrote and dry-ran the scripts locally, and a second reviewer checked them before a server was created.
3. **Unattended execution.** The agent ran the plan on a fresh AMD Developer Cloud MI300X droplet, recorded every step, and synced results back after each one.
4. **Hard cost limits.** A deterministic watchdog on a separate machine destroyed the droplet at a fixed deadline, whatever state the run was in. The agent also destroyed the droplet as soon as no work remained.
5. **Provenance on every run.** Each `meta.json` records the container digest (or llama.cpp commit), engine version, model revision, ROCm version and full server arguments.
6. **Failures kept.** Failed runs keep their metadata and logs. Problems hit along the way are in `notes/friction.md`.

One session, 4.09 GPU-hours, $8.15 at $1.99/GPU-hour.

## Known deviations

- `SGLANG_USE_AITER=0` did not switch SGLang's attention off AITER; only the MoE layers moved to Triton. SX is reported as observed.
- llama.cpp at 126,976 tokens: the load generator recorded 0 of 2 requests, though the server log shows both completed. The write-up uses the server's own timings for that cell, labeled as such.
