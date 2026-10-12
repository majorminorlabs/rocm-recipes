# Where the defaults cost you on MI300X (mostly, they don't)

This study takes the two best setups from [004-engine-shootout](../004-engine-shootout/), SGLang with defaults and vLLM with `--attention-backend ROCM_AITER_UNIFIED_ATTN`, and tests three documented tuning knobs per engine on one AMD Instinct MI300X with Qwen3-Coder-30B. Only prefix caching, which both engines turn on by default, made a measurable difference: 11% more throughput on SGLang and 8% on vLLM for 16 agents sharing a system prompt, and about 23% faster first tokens. Long prompts queued but never failed.

## Knobs

| | vLLM | SGLang |
|---|---|---|
| K1 | `VLLM_ROCM_USE_AITER=1` | `--mem-fraction-static 0.79` |
| K2 | `--max-num-batched-tokens 16384` | `--chunked-prefill-size 32768` |
| K3 | Prefix caching on | Radix cache on, `--schedule-policy lpm` |
| T | All three | All three |

## Folder map

- `METHOD.md`: how the setups were chosen and the study was run.
- `scripts/`: serving, load generation, metrics sampling, summarizing.
- `results/summary.csv`: one row per run. `results/deltas.csv`: every knob compared with its baseline.
- `results/raw/`: per-run output, metadata and once-per-second samples. `results/droplet_logs/`: server logs.
- `inputs/from-004/`: the 004 results used to pick the setups, with checksums.
- `notes/`: kernel selection, knob values and where they came from, partition check, friction log, session reports.
- `config.env.example`: public configuration template.

## Reproduce

Install `doctl`, prepare an SSH key, and obtain an AMD Developer Cloud account. From this folder:

```sh
cp config.env.example config.env
```

Fill in the droplet fields, then follow `METHOD.md` and use the scripts in `scripts/`. Two sessions used 7.30 GPU-hours, $14.54 at AMD's $1.99/GPU-hour list price.
