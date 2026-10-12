# FP8 vs BF16 on one MI300X

## Question

Is FP8 faster than BF16 for serving a 30B coding model on one MI300X?

## Headline

For one user, FP8 was 31% slower. At 64 concurrent requests it was 35% faster, and it scored 2.4 points lower on GSM8K.

## Throughput

| Concurrent requests | Qwen3-Coder BF16 output tok/s | Qwen3-Coder FP8 output tok/s |
|---|---|---|
| 1 | 196.22 | 136.17 |
| 8 | 830.94 | 765.59 |
| 32 | 1994.68 | 2128.54 |
| 64 | 2554.74 | 3442.16 |

Concurrency 1 uses the median of the three warm runs. Concurrency 8 uses the median of the original run and its three repetitions. Concurrency 32 and 64 use a single run each. Values are rounded to two decimal places.

## Accuracy

GSM8K exact-match scores from R3, shown as fractions.

| Model | Strict | Flexible |
|---|---|---|
| Qwen3-Coder BF16 | 0.964 | 0.964 |
| Qwen3-Coder FP8 | 0.936 | 0.94 |
| gpt-oss-120b | 0.8 | 0.96 |

gpt-oss returned 4 empty responses at 8,192 max tokens, recorded in [R3-M4/meta.json](results/raw/R3/R3-M4/meta.json). The headline uses the flexible score difference.

## Single user across engines

| Model | Engine | Output tok/s | Run |
|---|---|---|---|
| Qwen3-Coder BF16 | vLLM | 196.22 | median of warm runs |
| Qwen3-Coder FP8 | vLLM | 136.17 | median of warm runs |
| Qwen3-Coder Q4_K_M | llama.cpp | 186.69 | R4 generation tok/s |
| gpt-oss-120b | vLLM | 71.84 | cold, single run |
| Qwen2.5-72B | vLLM | 26.18 | cold, single run |

## Large models on one GPU

| Model | Concurrent requests | Output tok/s |
|---|---|---|
| gpt-oss-120b | 1 | 71.84 |
| gpt-oss-120b | 8 | 421.40 |
| gpt-oss-120b | 32 | 962.39 |
| gpt-oss-120b | 64 | 1423.40 |
| Qwen2.5-72B | 1 | 26.18 |
| Qwen2.5-72B | 8 | 157.86 |
| Qwen2.5-72B | 32 | 421.13 |

Each row is a single run.

## What broke

These are the issues a first-time user of this setup would also encounter:

- **Capacity.** The first attempt to create a single MI300X failed with no capacity. It became available a few hours later.
- **Scratch disk.** The 5 TB scratch volume came unmounted on every new droplet and had to be mounted by hand (`mount /dev/vdc1 /mnt/scratch`).
- **Eval tooling.** lm-eval 0.4.9 will not import inside the vLLM ROCm container, because the container's Transformers release removed `AutoModelForVision2Seq`. Running lm-eval in a separate `python:3.12-slim` container fixed it.
- **Reasoning model scoring.** gpt-oss-120b sometimes returns no final answer when its reasoning uses up the token budget, and lm-eval 0.4.9 crashes on the empty response instead of scoring it. We raised the budget to 8,192 tokens and patched the filter to score empty answers as wrong.
- **Downloads.** `huggingface-cli` in the container is retired. `hf download` works.
- **Versioning.** Neither the host image nor the container has `/opt/rocm/.info/version`. See [VERSIONS.md](results/env/VERSIONS.md).
- **Warmup.** The first benchmark after a server starts showed about twice the time to first token, with throughput within 3%. The benchmark script now runs a warmup first.
- **Startup probes.** vLLM resets connections while it loads weights and captures graphs, so readiness checks should keep polling instead of treating a reset as a failure.

## Method

See [METHOD.md](METHOD.md) for how the study was designed and run.

## Reproduce

Install `doctl`, prepare an SSH key, and obtain an AMD Developer Cloud account. From this study folder:

```sh
cp config.env.example config.env
```

Fill in the configuration, then use `scripts/remote_setup.sh`, `scripts/serve_vllm.sh`, and the benchmark scripts in `scripts/` to run the experiment. Use `scripts/destroy.sh` when finished.

## Versions

See [results/env/VERSIONS.md](results/env/VERSIONS.md) for recorded versions and missing runtime information.

## Cost

2.88 GPU-hours, about $5.73 at $1.99/hr across the recorded runs.
