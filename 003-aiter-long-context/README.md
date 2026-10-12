# One flag made 256K decoding 73× faster on MI300X

On one AMD Instinct MI300X, adding `--attention-backend ROCM_AITER_UNIFIED_ATTN` took Qwen3-Coder-30B decoding at 256K from 1.1 to 80 tokens per second and nearly halved time to first token, with no accuracy change. Setting `VLLM_ROCM_USE_AITER=1` alone did not change attention. This study compares five server configurations using the same model, GPU, container and prompts.

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
