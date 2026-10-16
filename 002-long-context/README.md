# Long context on one MI300X

How much context fits on one 192 GB MI300X, how fast does it answer, and can it still find a fact at the far end? Qwen3-Coder 30B fit a 256K-token window for about 3.8 simultaneous users with BF16 KV cache (7.6 with FP8), and found the target in all nine hard retrieval trials at 256K. On the tested vLLM stack, its decode slowed to 1.1 tokens/s at that length after the attention kernel fell back to Triton. Two sessions used 8.8 GPU-hours, costing $17.56 at $1.99/hour.

## The recipe

Tested on one AMD Instinct MI300X (192 GB).

**Use the tested image**

- vLLM: `rocm/vllm@sha256:e0ea9a10b729573ea8598bdc073bda0ea382fe1037eec7c0761b6fa7f46baaf4`.

**Download the exact model revision**

- BF16: [Qwen/Qwen3-Coder-30B-A3B-Instruct, revision `b2cff646eb4bb1d68355c01b18ae02e7cf42d120`](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct/tree/b2cff646eb4bb1d68355c01b18ae02e7cf42d120).

**Verification gap:** these revisions are recorded in the measured-run metadata, but an exact download invocation with `--revision` is not preserved in the available logs. No revision-pinned download command is reconstructed here.

**BF16 weights and BF16 KV cache at 256K**

The server arguments are copied from the measured run in [L3H/L3H-M1-bf16kv-258048](https://github.com/majorminorlabs/rocm-recipes/blob/main/002-long-context/results/raw/L3H/L3H-M1-bf16kv-258048/meta.json); run inside the pinned vllm image.

```sh
vllm serve Qwen/Qwen3-Coder-30B-A3B-Instruct --host 0.0.0.0 --port 8000 --max-model-len 262144 --gpu-memory-utilization 0.92 --no-enable-prefix-caching --kv-cache-dtype auto
```

**BF16 weights and FP8 KV cache at 256K**

The server arguments are copied from the measured run in [L3H/L3H-M1-fp8kv-258048](https://github.com/majorminorlabs/rocm-recipes/blob/main/002-long-context/results/raw/L3H/L3H-M1-fp8kv-258048/meta.json); run inside the pinned vllm image.

```sh
vllm serve Qwen/Qwen3-Coder-30B-A3B-Instruct --host 0.0.0.0 --port 8000 --max-model-len 262144 --gpu-memory-utilization 0.92 --no-enable-prefix-caching --kv-cache-dtype fp8
```

The 256K window held about 3.8 simultaneous requests with BF16 KV cache, or 7.6 with FP8; BF16 KV retrieval scored 9/9, while decode fell to 1.1 tok/s on the Triton fallback.

On a GPU with less memory, reduce the context window and remeasure KV capacity; verify the attention backend selected at startup.

## Method

See [METHOD.md](METHOD.md) for how the study was designed and run.

## Folder map

- [scripts/](scripts/): setup, serving, benchmarking, retrieval, sync, teardown, and summarization commands.
- [results/](results/): raw measurements, [summary.csv](results/summary.csv), and recorded environment details.

## Rerun

Install `doctl`, prepare an SSH key and AMD Developer Cloud access, then copy [config.env.example](config.env.example) to `config.env` and fill in the blank values. Use the scripts in `scripts/` to set up, run, sync, and tear down the experiment. The scripts use the configured deadline and teardown commands so the GPU is not left running after the work ends.
