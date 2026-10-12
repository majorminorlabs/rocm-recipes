# Session 1 report — ROCm Recipes 003

- Session started: 2026-10-09T17:51:00-05:00
- Steps done: P0.1–P6.5; W1–W4.
- Steps blocked: none.
- M1 served: Qwen/Qwen3-Coder-30B-A3B-Instruct in all five configurations. No M6 attempt was part of study 003.
- GPU hours used at destroy time: 3.583.
- Estimated credits remaining at $1.99/GPU-hour from a $76 starting balance: $68.87.

| Config | Requested kernel / cache | Attention backend selected | Fallback warning | 32K output tok/s | Longest length output tok/s | Needle |
|---|---|---|---|---:|---:|---|
| A | Default kernels | ROCM_ATTN | Yes | 7.91 | 0.72 at 258048 | Not run in 003; 002 prior result was 9/9 |
| B | Default kernels, 128K window | ROCM_ATTN | No | 60.38 | 7.36 at 126976 | 9/9 |
| C | AITER attention only | ROCM_AITER_UNIFIED_ATTN | No | 75.89 | 3.48 at 258048 | 9/9 |
| D | VLLM_ROCM_USE_AITER=1 | ROCM_ATTN | Yes | 7.93 | 0.72 at 258048 | 8/9 |
| E | AITER attention + FP8 KV cache | ROCM_AITER_UNIFIED_ATTN | No | 89.95 | 5.05 at 258048 | 7/9 |

Fallback warning refers to `Cannot use ROCm custom paged attention kernel, falling back to Triton implementation.` The backend values and warning presence are from each config’s `backend.txt`. Output tok/s is `output_throughput` from the L1 result JSON.
