# Session 2 report — ROCm Recipes 003

- Session start: 2026-10-10T04:48:00-05:00
- Session end: 2026-10-10T13:05:55Z (droplet confirmed absent)
- Steps done: P7.0–P11.4; W1–W4.
- Steps blocked: none.
- Model: Qwen/Qwen3-Coder-30B-A3B-Instruct; image digest `sha256:e0ea9a10b729573ea8598bdc073bda0ea382fe1037eec7c0761b6fa7f46baaf4`.
- Haystack SHA-256: `2d5bb2ad5f422765e714617e21fa31bbaf8958aa79682c86fca6660fcc5d1b2b` (matches Session 1).

| Config | Needle run | Correct / total | Distractor hits | Errors |
|---|---|---:|---:|---:|
| C | L3H-M1-C-s2-258048 | 26 / 30 | 4 | 0 |
| E | L3H-M1-E-s2-258048 | 23 / 30 | 7 | 0 |
| A | L3H-M1-A-s2-258048 | 27 / 30 | 3 | 0 |
| B | L3H-M1-B-s2-126976 | 30 / 30 | 0 | 0 |

| Config | Speed run | Decode tok/s (`1000 / median_itl_ms`) | Median TTFT (ms) |
|---|---|---:|---:|
| C | L1-M1-C-s2-in32768 | 150.40 | 1789.02 |
| C | L1-M1-C-s2-in258048 | 80.36 | 70395.87 |
| E | L1-M1-E-s2-in32768 | 160.50 | 1398.52 |
| E | L1-M1-E-s2-in258048 | 106.15 | 48271.36 |

| Config | KV cache tokens | Maximum concurrency at max length | Backend evidence |
|---|---:|---:|---|
| C | 997888 | 3.81 | ROCM_AITER_UNIFIED_ATTN; TritonExperts MoE |
| E | 1997184 | 7.62 | ROCM_AITER_UNIFIED_ATTN; TritonExperts MoE |
| A | 997888 | 3.81 | ROCM_ATTN; TritonExperts MoE; custom paged attention fell back to Triton |
| B | 952960 | 7.27 | ROCM_ATTN; TritonExperts MoE |

- Session GPU hours used through confirmed destruction: 3.299. At $1.99/GPU-hour, session cost: $6.56; estimated credits remaining from the $68.87 Session 1 balance: $62.31.
- Session 1 cumulative GPU hours before this session: 3.583.
- Droplet <droplet-id> destroyed and confirmed absent at 2026-10-10T13:05:55Z.
