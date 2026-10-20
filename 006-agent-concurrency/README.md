# ROCm Recipes 006: Eight coding agents per MI300X

I ran real coding agents on 30 frozen tasks with Qwen3.8-27B BF16 and vLLM on one AMD MI300X. Eight concurrent agents produced 7 strict solves in 2.838535 active GPU-hours: **2.47 solved/hour, $0.81 per solve** at the $1.99/hour list price. This is the best observed point in a small single-run study, not a statistically established optimum.

[Article and charts](https://majorminor.xyz/research/rocm-recipes-006) · [Results](results/final_analysis.json) · [Engine input totals](results/analysis/engine_input_totals.json) · [Sensitivity](results/analysis/symlink_sensitivity.json)

| Concurrency | Strict solved / graded | Active GPU-hours | Solved/hour | Active GPU $/solve |
|---|---:|---:|---:|---:|
| 16 | 3/29 | 1.938197222 | 1.55 | 1.29 |
| 8 | 7/29 | 2.838535000 | 2.47 | 0.81 |
| 4 | 6/29 | 4.063533056 | 1.48 | 1.35 |

c1 remains dropped by the budget guard; its three historical attempts are anecdotal (0 strict solves). Active windows include infrastructure retries and intervening gaps, and exclude setup and failed-session overhead. Recorded whole-study usage was 15.5049 GPU-hours, about $30.85.

## Package

- [Final exports](results/atlas/scored/final/): all 104 attempts, including infrastructure failures and anecdotal c1; operational identities and evidence paths removed.
- [Summary CSV](results/summary.csv), [attempt CSV](results/runs.csv), and [matched-ten view](results/matched_summary.csv).
- [Seeded manifests](manifests/seeded/) and [executed manifests](manifests/executed/), including retries. c1's manifest is retained as planned work, not a completed queue.
- [Sampler records](results/raw/): engine TTFT/cache/KV metrics and host utilization.
- [Analysis JSON](results/analysis/), [token coverage](results/token_coverage.json), [007 numerical inputs](007-inputs/).
- [Method](METHOD.md), [runtime/export/summary scripts](scripts/), [validation](validate.py), [publication scope](EXCLUSIONS.md).

The frozen ATLAS tasks-v1 harness is **not public and is not included here**. Execution/export scripts require an authorized local checkout at `279889b8f42c607344781766503602a8c462f5df` and its frozen task data. No task prompts, hidden tests, source workspaces, agent transcripts or model weights are distributed. Public data validation and summary reconstruction do not require the harness.

## Recompute locally, without hardware

Python 3.11 or newer, standard library only:

```sh
python3 validate.py
python3 scripts/summarize_006.py results/atlas/scored/final/c16/runs.json results/atlas/scored/final/c8/runs.json results/atlas/scored/final/c4/runs.json results/atlas/scored/final/c1/runs.json --samples results/raw/*/samples.jsonl --strict --output-dir /tmp/rocm006-recomputed
```

`SHA256SUMS` covers the public projection. `PUBLICATION.json` also retains original private-export hashes so public redactions are explicit. Full output token totals remain unavailable; absent usage is never zero.

## Run on separately supplied hardware

The runtime scripts are preserved for inspection and authorized reproduction with the private frozen harness. Set `ATLAS_SOURCE` to that checkout; use `config.env.example` for a fresh private configuration. The controller's historical resume DBs, lifecycle state and host records are deliberately not distributed: do not treat this as a ready-to-resume cloud session. A fresh campaign needs fresh state and an empty DB. Never reuse the published executed attempt IDs against an old DB. The published scripts do not provision hardware.

The frozen run configuration is [007-inputs/run-config.ts](007-inputs/run-config.ts); its original import path is relative to the private harness's `config/run-configs/`. Copy it there only with the matching pinned source. [Served engine metadata](007-inputs/served_engine.json) retains the exact image digest, model revision and flags. Keep wall/turn/token limits and strict grading unchanged when comparing results.

Code: MIT; results/data: CC BY 4.0, as licensed at the repository root.
