# ROCm Recipes

Reproducible inference tests on AMD Instinct GPUs, by MAJOR//MINOR.

Each folder is one study: a plan, the scripts that ran it, the raw results, and a log of everything that went wrong.

| Study | Question | Headline |
|---|---|---|
| [001-fp8-vs-bf16](001-fp8-vs-bf16/) | Is FP8 faster than BF16 on one MI300X? | For one user, FP8 was 31% slower. At 64 concurrent requests it was 35% faster, and it scored 2.4 points lower on GSM8K. |
| [002-long-context](002-long-context/) | How much context fits on one MI300X? | Qwen3-Coder fit 256K tokens for about 3.8 users and found the target in 9/9 hard retrieval trials, but decoded at 1.1 tokens/s on the tested kernel. |
| [003-aiter-long-context](003-aiter-long-context/) | Can AITER fix long-context decode on MI300X? | One attention-backend flag took 256K decoding from 1.1 to 80 tok/s with no accuracy change; `VLLM_ROCM_USE_AITER=1` alone did not fix attention. |

## How these are run

Every study runs on a fresh cloud GPU. An AI agent executes the plan unattended, a second agent fixes broken scripts, and a watchdog destroys the server at a hard deadline. Every run records its container digest, model revision and engine version.

## License

Code: MIT. Results and data: CC BY 4.0.
