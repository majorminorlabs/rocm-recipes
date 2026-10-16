# One flag made 256K decoding 73× faster on MI300X

On one AMD Instinct MI300X, adding `--attention-backend ROCM_AITER_UNIFIED_ATTN` took Qwen3-Coder-30B decoding at 256K from 1.1 to 80 tokens per second and nearly halved time to first token, with no accuracy change. Setting `VLLM_ROCM_USE_AITER=1` alone did not change attention. This study compares five server configurations using the same model, GPU, container and prompts.

## The recipe

Tested on one AMD Instinct MI300X (192 GB).

**Use the tested image**

- vLLM: `rocm/vllm@sha256:e0ea9a10b729573ea8598bdc073bda0ea382fe1037eec7c0761b6fa7f46baaf4`.

**Download the exact model revision**

- BF16: [Qwen/Qwen3-Coder-30B-A3B-Instruct, revision `b2cff646eb4bb1d68355c01b18ae02e7cf42d120`](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct/tree/b2cff646eb4bb1d68355c01b18ae02e7cf42d120).

**Verification gap:** these revisions are recorded in the measured-run metadata, but an exact download invocation with `--revision` is not preserved in the available logs. No revision-pinned download command is reconstructed here.

**Config C: AITER attention, BF16 KV cache**

The server arguments are copied from the measured run in [L3H/L3H-M1-C-s2-258048](https://github.com/majorminorlabs/rocm-recipes/blob/main/003-aiter-long-context/results/raw/L3H/L3H-M1-C-s2-258048/meta.json); run inside the pinned vllm image.

```sh
vllm serve Qwen/Qwen3-Coder-30B-A3B-Instruct --host 0.0.0.0 --port 8000 --max-model-len 262144 --gpu-memory-utilization 0.92 --no-enable-prefix-caching --kv-cache-dtype auto --attention-backend ROCM_AITER_UNIFIED_ATTN
```

**Config E: AITER attention, FP8 KV cache**

The server arguments are copied from the measured run in [L3H/L3H-M1-E-s2-258048](https://github.com/majorminorlabs/rocm-recipes/blob/main/003-aiter-long-context/results/raw/L3H/L3H-M1-E-s2-258048/meta.json); run inside the pinned vllm image.

```sh
vllm serve Qwen/Qwen3-Coder-30B-A3B-Instruct --host 0.0.0.0 --port 8000 --max-model-len 262144 --gpu-memory-utilization 0.92 --no-enable-prefix-caching --kv-cache-dtype fp8 --attention-backend ROCM_AITER_UNIFIED_ATTN
```

At 256K, C decoded at about 80 tok/s and E at 110 tok/s (106 on the repeat); hard retrieval scored 26/30 for C and 23/30 for E. `VLLM_ROCM_USE_AITER=1` alone did not select the fast attention backend.

On another AMD GPU, check that this image and AITER backend support the device, then reduce context if needed and verify the selected backend in the startup log.

## Method

See [METHOD.md](METHOD.md) for how the study was designed and run.

## The five configurations

| Config | Setting | Attention backend |
|---|---|---|
| A | 256K window, defaults | ROCM_ATTN, falling back to Triton |
| B | 128K window | ROCM_ATTN custom kernel |
| C | `--attention-backend ROCM_AITER_UNIFIED_ATTN` | AITER unified attention |
| D | `VLLM_ROCM_USE_AITER=1` | ROCM_ATTN, falling back to Triton |
| E | Config C with FP8 KV cache | AITER unified attention |

At 256K, Config C decoded at 80 tokens per second and Config E at 110. Thirty hard retrieval trials scored 27/30 for A, 26/30 for C, and 23/30 for E. At a 127K window, B scored 30/30.

## Folder map

- `scripts/`: server setup, benchmarking, retrieval, cleanup and result tools.
- `results/raw/`: per-run logs, metadata, benchmark output and retrieval results.
- `results/summary.csv`: summarized measurements.
- `results/env/`: environment snapshots from both sessions.
- `config.env.example`: public configuration template; fill in credentials locally.

## Reproduce

Install `doctl`, prepare an SSH key, and obtain an AMD Developer Cloud account. From this folder:

```sh
cp config.env.example config.env
```

Fill in the droplet fields in `config.env`, then use the scripts in `scripts/` to set up, run, and tear down the experiment. The server image is pinned to the public digest in the configuration template. The study used two sessions and 6.9 GPU-hours, or $13.70 at AMD's $1.99/GPU-hour list price.
