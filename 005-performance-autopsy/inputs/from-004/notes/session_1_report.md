# Session 1 report — amd-rocm-004

Primary M1 results. Throughput and latency values are copied from `results/summary.csv`; decode tok/s is 1000 / median ITL. LC4 uses the LC1 single-user 32K row because the plan skips LC4 L1. `N/A` denotes a metric or backend that does not apply.

| Config | Engine / version | Image digest or commit | AITER requested | Attention / MoE backend observed | KV capacity | 32K L1 decode tok/s / p50 TTFT ms | Highest short concurrency output tok/s | Needle |
|---|---|---|---|---|---:|---:|---:|---:|
| VD | vLLM 0.29.1.dev0+g98dff2a81.d20261002 | rocm/vllm@sha256:e0ea9a10b729573ea8598bdc073bda0ea382fe1037eec7c0761b6fa7f46baaf4 | No explicit attention override | ROCM_ATTN / TritonExperts | 952960 | 161.25 / 2608.59 | 3382.81 | 9/9 |
| VT | vLLM 0.29.1.dev0+g98dff2a81.d20261002 | rocm/vllm@sha256:e0ea9a10b729573ea8598bdc073bda0ea382fe1037eec7c0761b6fa7f46baaf4 | ROCM_AITER_UNIFIED_ATTN requested | ROCM_AITER_UNIFIED_ATTN / TritonExperts | 997888 | 163.94 / 1799.67 | 3818.30 | 9/9 |
| SD | SGLang 0.5.21 | lmsysorg/sglang@sha256:4420a7e492fce623285c635b9a6a7e09ccf77a3c812006494e4414655d46662d | Image default; SGLANG_USE_AITER=1 | AITER default attention / AITER fused MoE | 914643 | 173.09 / 1584.51 | 3669.35 | 9/9 |
| SX | SGLang 0.5.21 | lmsysorg/sglang@sha256:4420a7e492fce623285c635b9a6a7e09ccf77a3c812006494e4414655d46662d | SGLANG_USE_AITER=0 requested | AITER default attention / Triton MoE | 914643 | 71.56 / 2114.92 | 2437.83 | 9/9 |
| LC1 | llama.cpp 06cad0b9e77315bd2930bd4f70a6d7b37b2a01c1 | — | N/A | N/A; f16 KV cache | n_ctx_slot=131072 | 107.86 / 20533.02 | 107.19 | 9/9 |
| LC4 | llama.cpp 06cad0b9e77315bd2930bd4f70a6d7b37b2a01c1 | — | N/A | N/A; f16 KV cache | n_ctx_slot=34816, 4 slots | 107.86 / 20533.02 | 168.14 | not run (plan skips) |

## Additional completed checks

- SD256 at a 262144-token window: capacity 914622 KV tokens; prewarm, 32K L1, and 258048-token L1 all `ok`, 2/2 requests and 256 output tokens each.
- Dense M7 (`Qwen/Qwen3-32B`, 40960 window): VT and SD each completed prewarm, L1 1024/32768, and L2 short c1/c16/c64 plus long c1/c8. All 16 benchmark runs were `ok` with full output. Capacity: VT 421952 KV tokens; SD 326383.
- LC1 L1 at 126976 tokens failed 0/2 in the benchmark client with “Never received a valid chunk to calculate TTFT”. llama-server logged 126974 prompt tokens and 256 generated tokens. The failure was not retried; full artifacts are preserved.
- SX was requested with `SGLANG_USE_AITER=0`; startup still chose its default AITER attention backend, while captured MoE selection was Triton. This runtime behavior is recorded as observed.
- The accidental first VT L1 repeat attempt is preserved separately under `results/raw/L2/L1-M1-VT-in32768-r2/`; the valid L1 repeat is under `results/raw/L1/L1-M1-VT-in32768-r2/`.
- Both GGUF and M7 model cache weights were retained under the user’s preservation instruction. The droplet log tree is preserved under `results/droplet_logs/`.
