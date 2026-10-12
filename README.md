# ROCm Recipes

Reproducible inference tests on AMD Instinct GPUs, by MAJOR//MINOR.

Each folder is one study: the reproduction scripts, raw results, environment records, and a summary of findings.

| Study | Question | Headline |
|---|---|---|
| [001-fp8-vs-bf16](001-fp8-vs-bf16/) | Is FP8 faster than BF16 on one MI300X? | For one user, FP8 was 31% slower. At 64 concurrent requests it was 35% faster, and it scored 2.4 points lower on GSM8K. |
| [002-long-context](002-long-context/) | How much context fits on one MI300X? | Qwen3-Coder fit 256K tokens for about 3.8 users and found the target in 9/9 hard retrieval trials, but decoded at 1.1 tokens/s on the tested kernel. |
| [003-aiter-long-context](003-aiter-long-context/) | Can AITER fix long-context decode on MI300X? | One attention-backend flag took 256K decoding from 1.1 to 80 tok/s with no accuracy change; `VLLM_ROCM_USE_AITER=1` alone did not fix attention. |
| [004-engine-shootout](004-engine-shootout/) | Which engine settings work best on one MI300X? | SGLang defaults led through 64 users; tuned vLLM led at 128, while default vLLM struggled with long prompts. |

## How these are run

Every study runs on a fresh cloud GPU and records its container digest, model revision and engine version. The scripts document setup, measurement, synchronization, and teardown.

## License

Code: MIT. Results and data: CC BY 4.0.
