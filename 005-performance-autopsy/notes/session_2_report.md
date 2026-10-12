# Session 2 report (005b)

## VT B, K3, and T results

W1 used the documented random shared-prefix fallback (1,536 shared prefix tokens + 2,560 random input tokens; 512 output tokens). All W1 cells used the same `dataset_mode` as Session 1 VT W1. W2 used random tokens with 256 output tokens. All measured requests completed successfully with zero failed requests and zero preemptions.

Peak KV usage is the maximum recorded across the knob set's W1 and W2 measurement cells. K3 has no W2 measurements by plan.

| Knob set | W1 c16 output tok/s | W1 c16 TTFT p95 (ms) | W1 c16 prefix-cache hit rate | W2 127K c1 TTFT p95 (ms) | W2 127K c1 decode tok/s | First W2 threshold point | Peak KV usage |
|---|---:|---:|---:|---:|---:|---|---:|
| B | 1,014.89 | 1,828.73 | Off; not measured | 18,888.23 | 113.22 | 64K c4 | 0.9888 |
| K3 | 1,097.04 | 1,395.31 | 0.3691 | N/A | N/A | N/A (W2 not run) | 0.0508 |
| T | 1,110.74 | 1,241.87 | 0.3691 | 18,384.56 | 112.45 | 64K c4 | 0.8615 |

Threshold point is the first ramp cell with failed requests, preemptions, or TTFT p95 above 3× the c1 TTFT p95 at the same input length. The full W2 set still ran after the threshold cell.

## B noise repeat

| Metric | W1 c8 B | W1 c8 B repeat | Difference (repeat vs B) |
|---|---:|---:|---:|
| Output tok/s | 688.73 | 698.84 | +1.47% |
| TTFT p95 (ms) | 2,025.86 | 795.82 | −60.72% |

## Cross-session VT B drift

Percent difference is `(Session 2 − Session 1) / Session 1 × 100`.

| Cell | Output tok/s: Session 1 → Session 2 (difference) | TTFT p50 (ms): Session 1 → Session 2 (difference) |
|---|---:|---:|
| W1 c1 | 187.29 → 188.56 (+0.68%) | 122.40 → 124.22 (+1.49%) |
| W1 c4 | 413.48 → 421.66 (+1.98%) | 406.14 → 409.24 (+0.76%) |
| W1 c8 | 692.25 → 688.73 (−0.51%) | 771.45 → 777.88 (+0.83%) |
| W1 c16 | 1,005.60 → 1,014.89 (+0.92%) | 1,035.76 → 1,045.41 (+0.93%) |
| W2 127K c1 | 12.23 → 12.16 (−0.64%) | 18,730.67 → 18,870.03 (+0.74%) |
| W2 127K c4 | 12.84 → 12.70 (−1.07%) | 46,866.81 → 47,375.54 (+1.09%) |
| W2 64K c8 | 40.17 → 39.67 (−1.23%) | 19,878.39 → 17,881.86 (−10.04%) |

## Session cost

Credits before 005b: $42.72. The configured droplet was confirmed absent at 2026-10-11T17:03:19-05:00. Elapsed GPU time from `CREATED_AT` was 1.5553 hours; cost at $1.99/hour was $3.10; estimated credits remaining were $39.62.
