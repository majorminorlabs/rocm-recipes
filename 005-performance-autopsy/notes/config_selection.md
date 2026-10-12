# Config selection from 004

Eligibility: L2 short and long at c16, all M1 L1/L2 rows status `ok`, needle at least 7/9.
Score: geometric mean of L1 32K decode tok/s, L2 short c16 output tok/s, and L2 long c16 output tok/s.

| Config | Engine | L1 32K decode tok/s | L2 short c16 output tok/s | L2 long c16 output tok/s | Needle /9 | Score | Eligible |
|---|---|---:|---:|---:|---:|---:|---|
| LC1 | llamacpp | 107.86 | — | — | 9.00 | — | no |
| LC4 | llamacpp | — | — | — | — | — | no |
| SD | sglang | 173.09 | 1282.71 | 132.55 | 9.00 | 308.74 | yes |
| SD256 | sglang | 171.47 | — | — | — | — | no |
| SX | sglang | 71.56 | 808.04 | 99.64 | 9.00 | 179.28 | yes |
| VD | vllm | 161.25 | 1014.52 | 27.28 | 9.00 | 164.64 | yes |
| VT | vllm | 163.94 | 923.78 | 119.82 | 9.00 | 262.78 | yes |

**CFG_A = SD** (sglang, score 308.74).
**CFG_B = VT** (vllm, score 262.78).
