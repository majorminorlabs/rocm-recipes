# SGLang's defaults beat tuned vLLM on MI300X, until 128 users

This study serves Qwen3-Coder-30B on one AMD Instinct MI300X with vLLM, SGLang and llama.cpp, using the same prompts, load generator and 128K context window. SGLang with no flags led through 64 users; vLLM with AITER led at 128 users, while default vLLM struggled under long prompts.

## Configurations

| Config | Engine | Setting |
|---|---|---|
| VD | vLLM | Defaults |
| VT | vLLM | `--attention-backend ROCM_AITER_UNIFIED_ATTN` |
| SD | SGLang | Image defaults (`SGLANG_USE_AITER=1`) |
| SX | SGLang | `SGLANG_USE_AITER=0` |
| LC1 | llama.cpp | 1 slot |
| LC4 | llama.cpp | 4 slots, 34K context per slot |

## Folder map

- `PLAN.md`: study protocol and execution record.
- `scripts/`: server setup, benchmarking, cleanup and result tools.
- `results/raw/`: per-run output, metadata and logs.
- `results/summary.csv`: summarized measurements.
- `results/env/`: environment records.
- `results/droplet_logs/`: preserved server logs.
- `notes/`: engine help, environment details and run notes.
- `config.env.example`: public configuration template; fill in credentials locally.

## Reproduce

Install `doctl`, prepare an SSH key, and obtain an AMD Developer Cloud account. From this folder:

```sh
cp config.env.example config.env
```

Fill in the private droplet settings in `config.env`, then follow `PLAN.md` and use the scripts in `scripts/` to set up, run and tear down the experiment. The public container digests and llama.cpp commit are pinned in the example configuration.
