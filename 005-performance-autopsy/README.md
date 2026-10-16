# Where the defaults cost you on MI300X (mostly, they don't)

This study takes the two best setups from [004-engine-shootout](../004-engine-shootout/), SGLang with defaults and vLLM with `--attention-backend ROCM_AITER_UNIFIED_ATTN`, and tests three documented tuning knobs per engine on one AMD Instinct MI300X with Qwen3-Coder-30B. Only prefix caching, which both engines turn on by default, made a measurable difference: 11% more throughput on SGLang and 8% on vLLM for 16 agents sharing a system prompt, and about 23% faster first tokens. Long prompts queued but never failed.

## The recipe

Tested on one AMD Instinct MI300X (192 GB).

**Use the tested images**

- vLLM: `rocm/vllm@sha256:e0ea9a10b729573ea8598bdc073bda0ea382fe1037eec7c0761b6fa7f46baaf4`.
- SGLang: `lmsysorg/sglang@sha256:4420a7e492fce623285c635b9a6a7e09ccf77a3c812006494e4414655d46662d`.

**Download the exact model revision**

- BF16: [Qwen/Qwen3-Coder-30B-A3B-Instruct, revision `b2cff646eb4bb1d68355c01b18ae02e7cf42d120`](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct/tree/b2cff646eb4bb1d68355c01b18ae02e7cf42d120).

**Verification gap:** these revisions are recorded in the measured-run metadata, but an exact download invocation with `--revision` is not preserved in the available logs. No revision-pinned download command is reconstructed here.

**SD K3: radix cache enabled, LPM scheduling**

The server arguments are copied from the measured run in [L0/L0-M1-SD-K3](https://github.com/majorminorlabs/rocm-recipes/blob/main/005-performance-autopsy/results/raw/L0/L0-M1-SD-K3/meta.json); run inside the pinned sglang image.

```sh
python3 -m sglang.launch_server --model-path Qwen/Qwen3-Coder-30B-A3B-Instruct --served-model-name Qwen/Qwen3-Coder-30B-A3B-Instruct --host 0.0.0.0 --port 8000 --context-length 131072 --enable-metrics --schedule-policy lpm
```

**VT K3: prefix cache enabled, AITER attention**

The server arguments are copied from the measured run in [L0/L0-M1-VT-K3-s2](https://github.com/majorminorlabs/rocm-recipes/blob/main/005-performance-autopsy/results/raw/L0/L0-M1-VT-K3-s2/meta.json); run inside the pinned vllm image.

```sh
vllm serve Qwen/Qwen3-Coder-30B-A3B-Instruct --host 0.0.0.0 --port 8000 --max-model-len 131072 --gpu-memory-utilization 0.92 --kv-cache-dtype auto --attention-backend ROCM_AITER_UNIFIED_ATTN
```

Neither command disables prefix caching. With 16 agents sharing a system prompt, caching improved throughput by 11% on SGLang and 8% on vLLM and made first tokens about 23% faster; the memory and batching knobs did not improve speed.

On another GPU, start with the engine defaults, check available memory and backend support, and measure caching with your actual shared-prefix workload.

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
