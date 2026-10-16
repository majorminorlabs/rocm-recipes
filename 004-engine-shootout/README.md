# SGLang's defaults beat tuned vLLM on MI300X, until 128 users

This study serves Qwen3-Coder-30B on one AMD Instinct MI300X with vLLM, SGLang and llama.cpp, using the same prompts, load generator and 128K context window. SGLang with no flags led through 64 users; vLLM with AITER led at 128 users, while default vLLM struggled under long prompts.

## The recipe

Tested on one AMD Instinct MI300X (192 GB).

**Use the tested images**

- vLLM: `rocm/vllm@sha256:e0ea9a10b729573ea8598bdc073bda0ea382fe1037eec7c0761b6fa7f46baaf4`.
- SGLang: `lmsysorg/sglang@sha256:4420a7e492fce623285c635b9a6a7e09ccf77a3c812006494e4414655d46662d`.

**Download the exact model revision**

- BF16: [Qwen/Qwen3-Coder-30B-A3B-Instruct, revision `b2cff646eb4bb1d68355c01b18ae02e7cf42d120`](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct/tree/b2cff646eb4bb1d68355c01b18ae02e7cf42d120).

**Verification gap:** these revisions are recorded in the measured-run metadata, but an exact download invocation with `--revision` is not preserved in the available logs. No revision-pinned download command is reconstructed here.

**SD: SGLang with its default AITER backend**

The server arguments are copied from the measured run in [L0/L0-M1-SD](https://github.com/majorminorlabs/rocm-recipes/blob/main/004-engine-shootout/results/raw/L0/L0-M1-SD/meta.json); run inside the pinned sglang image.

```sh
python3 -m sglang.launch_server --model-path Qwen/Qwen3-Coder-30B-A3B-Instruct --served-model-name Qwen/Qwen3-Coder-30B-A3B-Instruct --host 0.0.0.0 --port 8000 --context-length 131072 --disable-radix-cache
```

**VT: vLLM with AITER attention**

The server arguments are copied from the measured run in [L0/L0-M1-VT](https://github.com/majorminorlabs/rocm-recipes/blob/main/004-engine-shootout/results/raw/L0/L0-M1-VT/meta.json); run inside the pinned vllm image.

```sh
vllm serve Qwen/Qwen3-Coder-30B-A3B-Instruct --host 0.0.0.0 --port 8000 --max-model-len 131072 --gpu-memory-utilization 0.92 --no-enable-prefix-caching --kv-cache-dtype auto --attention-backend ROCM_AITER_UNIFIED_ATTN
```

SD led through 64 users; VT led at 128 users. The recorded 32K single-user decode rates were 173.09 tok/s for SD and 163.94 for VT; SD allocated a 914,643-token KV pool. The measured SD command includes `--disable-radix-cache`; “defaults” refers to backend selection, not the absence of all server flags.

On another AMD GPU, check image/backend compatibility, lower context if memory is tight, and rerun the concurrency sweep for your workload.

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

- `METHOD.md`: how the study was designed and run.
- `scripts/`: server setup, benchmarking, cleanup and result tools.
- `results/raw/`: per-run output, metadata and logs.
- `results/summary.csv`: summarized measurements.
- `results/env/`: environment records.
- `results/droplet_logs/`: preserved server logs.
- `notes/`: kernel selection per config, image digests, friction log and session report.
- `config.env.example`: public configuration template; fill in credentials locally.

## Reproduce

Install `doctl`, prepare an SSH key, and obtain an AMD Developer Cloud account. From this folder:

```sh
cp config.env.example config.env
```

Fill in the private droplet settings in `config.env`, then follow `METHOD.md` and use the scripts in `scripts/` to set up, run and tear down the experiment. The public container digests and llama.cpp commit are pinned in the example configuration.
