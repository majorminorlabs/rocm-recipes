# 005 Session 1 Report

## Scope and completion

- Selected configs from 004: CFG_A = SD (SGLang, score 308.74); CFG_B = VT (vLLM, score 262.78).
- Completed P0.1–P0.6, P1.0–P1.6, all Phase 2 knob blocks for SD, and Phase 3 VT B, K1, and K2.
- Phase 2 completed before 2.9 hours, so VT B and T were assigned W2r by the plan. At 5.5 hours, VT K2 was the active knob block; its W1 and W2r cells were completed, then wrap-up began. VT K3 and T were not started.
- The required VT B W1 c8-r2 repeat was omitted by the runner. The VT B noise band is unavailable. SD B's c8 repeat differed by 0.14% in output throughput and 0.62% in TTFT p95.
- P1.4 found the client lacked `--custom-skip-chat-template`; all W1 runs therefore used the documented random shared-prefix fallback (1536 shared-prefix tokens plus 2560 random input tokens), with 512 output tokens. W1 did not use Django code text.
- An initial Phase 3 attempt incorrectly started SD and was interrupted before any request completed. Its failed metadata remains preserved as `L2-M1-SD-B-P3-w1-c1`; it is excluded from workload analysis. Phase 3 data below is VT only.
- No accepted W1/W2 workload cell had failed requests or preemptions.

## W1 and W2 results

W2 thresholds below use the plan's first-ramp-step rule. For single-knob blocks, only W2r was run; those entries identify the first threshold observed in the reduced cells and are not a full W2 ramp.

| Config | Knob | W1 c16 output tok/s | W1 c16 TTFT p95 (ms) | W2 127K c1 TTFT p95 (ms) | W2 127K c1 decode tok/s | W2 threshold observed | Peak KV usage |
|---|---|---:|---:|---:|---:|---|---:|
| SD | B | 1143.05 | 1338.27 | 17908.43 | 115.55 | Full W2: 64K c4 | 0.97 |
| SD | K1 | 1130.30 | 1338.13 | 17836.55 | 116.18 | W2r: 127K c4 | 0.67 |
| SD | K2 | 1132.36 | 1333.18 | 17259.30 | 116.02 | W2r: 127K c4 | 0.76 |
| SD | K3 | 1268.62 | 1043.41 | — | — | No W2 run | 0.05 |
| SD | T | 1253.87 | 1026.59 | 17202.70 | 115.21 | Full W2: 64K c4 | 0.98 |
| VT | B | 1005.60 | 1849.13 | 18766.30 | 113.37 | W2r: 127K c4 | 0.527 |
| VT | K1 | 1022.47 | 1681.55 | 18350.12 | 112.45 | W2r: 127K c4 | 0.431 |
| VT | K2 | 1010.16 | 1880.46 | 18811.51 | 112.54 | W2r: 127K c4 | 0.527 |
| VT | K3 | — | — | — | — | Not run | — |
| VT | T | — | — | — | — | Not run | — |

VT B/K1/K2 W2r c4 TTFT p95 values were 74.46 s, 72.74 s, and 74.52 s respectively; their 127K c1 values were 18.77 s, 18.35 s, and 18.81 s. All were more than 3× the c1 value. Each VT knob block's listed cells completed with zero failed requests and zero preemptions.

## Capacity and environment

- VT B capacity: 997,888 KV tokens.
- VT K1 capacity: 1,221,952 KV tokens. It used `VLLM_ROCM_USE_AITER=1` while retaining `--attention-backend ROCM_AITER_UNIFIED_ATTN`.
- VT K2 capacity: 997,888 KV tokens, with `--max-num-batched-tokens 16384` and the same VT attention backend.
- Partition check: SPX compute / NPS1 memory; no partition mode was changed.
- The final environment snapshot is `results/env/session1_end/`; droplet logs are in `results/droplet_logs/`.

## Time and cost

- Droplet created: 2026-10-11 13:30:00 UTC.
- Droplet deletion confirmed: 2026-10-11 19:14:51 UTC; ID 608140700 was absent from the droplet list.
- Total billed duration: 5.7475 GPU-hours (5 h 44 m 51 s).
- Estimated cost at $1.99/GPU-hour: $11.44.
- Using the plan's approximate $54.16 pre-session credit balance, estimated remaining credits are $42.72.

## Artifacts

- `results/summary.csv`: 85 rows.
- `results/deltas.csv`: 585 deltas.
- Final result sync verified with zero differing files.
