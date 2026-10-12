# Section 4 knob values

## CFG_A=SD, derived from B startup (P2.B)

B server: `L0-M1-SD-B`. Source: `results/raw/L0/L0-M1-SD-B/backend.txt` and `capacity_raw.txt`.

- B startup args excerpt: `mem_fraction_static': 0.7361`; `chunked_prefill_size': 16384`; `schedule_policy': 'fcfs'`.
- B capacity excerpt: `max_total_num_tokens=914643, chunked_prefill_size=16384, max_prefill_tokens=16384, max_running_requests=3572, context_len=131072, available_gpu_mem=18.97 GB`.
- GPU memory at worker startup: `avail mem=191.18 GB` before weight load.
- K1 target: raise mem fraction by `(18.97 - 8.00) / 191.18 = 0.05738`; `0.7361 + 0.05738 = 0.79348`, rounded down to the nearest 0.01 gives **0.79**. Estimated remaining memory is about 8.66 GB.
- K2: **32768** (`2 × B chunked_prefill_size 16384`).
- K3: `KNOB_PREFIX_CACHE=1` plus `--schedule-policy lpm`.

Source for K1/K2/K3: [SGLang hyperparameter tuning](https://docs.sglang.io/docs/advanced_features/hyperparameter_tuning) and [SGLang server arguments](https://docs.sglang.io/docs/advanced_features/server_arguments), per `PLAN.md`.

### K1 observed outcome

- Run ID: `L0-M1-SD-K1`.
- Server log reports `mem_fraction_static=0.79`; capacity log reports `max_total_num_tokens=779723` and `available_gpu_mem=35.79 GB` after startup (KV allocation 35.69 GB per K/V tensor).
- This differs from the estimate (about 8.66 GB remaining): the server used less KV capacity than B and reported more remaining memory. Preserve the measured values; no follow-up adjustment was made.

### K2 observed outcome

- Run ID: `L0-M1-SD-K2`.
- Server log confirms `chunked_prefill_size=32768`; capacity log reports `max_total_num_tokens=692734` and `available_gpu_mem=46.53 GB` after startup (KV allocation 31.71 GB per K/V tensor).

### K3 observed outcome

- Run ID: `L0-M1-SD-K3`.
- Prefix caching was enabled (no `--disable-radix-cache` in the captured server args) with `--schedule-policy lpm`; capacity matched B at 914,643 KV tokens and 18.97 GB available.
- W1's recorded prefix-cache hit rates ranged 0.333–0.375.

## CFG_B=VT (vLLM)

### K1 observed outcome

- Run ID: `L0-M1-VT-K1`.
- Set `VLLM_ROCM_USE_AITER=1`; the recorded server args retain `--attention-backend ROCM_AITER_UNIFIED_ATTN`.
- Capacity log reports 1,221,952 KV tokens (maximum concurrency 9.32 at 131,072 tokens/request); source: `results/raw/L0/L0-M1-VT-K1/capacity_raw.txt`.
