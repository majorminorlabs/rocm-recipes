# Where the defaults cost you on MI300X (mostly, they don't)

This study takes the two leading setups from ROCm Recipes 004—SGLang with its defaults and vLLM with AITER attention—and tests three documented tuning knobs on each. Prefix caching, already on by default in both engines, was the only change with a measurable throughput gain for the agent-style workload. Long prompts queued but did not fail.

## Configurations

| Config | Engine | Setting |
|---|---|---|
| Baseline | SGLang | Defaults from 004, with prefix caching off for the benchmark |
| Baseline | vLLM | AITER attention from 004, with prefix caching off for the benchmark |
| K1 | vLLM | `VLLM_ROCM_USE_AITER=1` |
| K1 | SGLang | `--mem-fraction-static 0.79` |
| K2 | vLLM | `--max-num-batched-tokens 16384` |
| K2 | SGLang | `--chunked-prefill-size 32768` |
| K3 | vLLM | Prefix caching on |
| K3 | SGLang | Radix cache on with `--schedule-policy lpm` |
| All three | Both | K1, K2 and K3 together |

At 16 users, prefix caching raised measured throughput by 11% for SGLang and 8% for vLLM. The other knobs stayed within the observed noise band.

## Folder map

- `PLAN.md`, `PLAN-005b.md`: study protocol and follow-up session.
- `scripts/`: setup, prompt generation, serving, benchmarking and cleanup tools.
- `results/raw/`: per-run logs and metadata.
- `results/summary.csv`, `results/deltas.csv`: measurements and knob comparisons.
- `results/env/`: environment records.
- `results/droplet_logs/`: preserved server logs.
- `notes/`: configuration selection, knob notes, reports and saved help output.
- `inputs/from-004/`: copied source data and provenance from study 004.
- `config.env.example`: public configuration template; fill in credentials locally.

## Reproduce

Install `doctl`, prepare an SSH key, and obtain an AMD Developer Cloud account. From this folder:

```sh
cp config.env.example config.env
```

Fill in the private droplet settings in `config.env`, then follow `PLAN.md` and `PLAN-005b.md` and use the scripts in `scripts/` to set up, run and tear down the experiment. Public image digests and the pinned llama.cpp commit are recorded in the configuration example.
