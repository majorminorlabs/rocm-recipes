# ROCm Recipes

Reproducible inference tests on AMD Instinct GPUs, by MAJOR//MINOR.

Each folder is one study: a plan, the scripts that ran it, the raw results, and a log of everything that went wrong.

| Study | Question | Headline |
|---|---|---|
| [001-fp8-vs-bf16](001-fp8-vs-bf16/) | Is FP8 faster than BF16 on one MI300X? | For one user, FP8 was 31% slower. At 64 concurrent requests it was 35% faster, and it scored 2.4 points lower on GSM8K. |

## How these are run

Every study runs on a fresh cloud GPU. An AI agent executes the plan unattended, a second agent fixes broken scripts, and a watchdog destroys the server at a hard deadline. Every run records its container digest, model revision and engine version.

## License

Code: MIT. Results and data: CC BY 4.0.
