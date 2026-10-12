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

- Public and private addresses were assigned to the wrong config fields; correcting the address and droplet ID restored access.
- SSH refused checksum verification after a transfer; retries failed and work stopped.
- The scratch filesystem was unmounted; mounting the existing filesystem restored scratch storage.
- A new SSH host key was unknown; enrolling it restored access.
- Result sync ran before setup created the remote results directory and failed.
- Remote setup failed on the unmounted scratch filesystem; mounting it allowed setup to proceed.
- A readiness probe received a connection reset during server initialization; a later poll succeeded.
- The BF16 readiness probe received a connection reset; waiting allowed benchmarking to proceed.
- The gpt-oss readiness probe received connection resets during initialization and graph capture; later polls succeeded.
- Quality evaluation failed because transformers lacked AutoModelForVision2Seq; retries produced no score.
- The quality dependency failure left later quality and follow-up steps pending; the session ended with server destruction.
- A later setup again found scratch storage unmounted; mounting the existing filesystem restored it.
- Sync on a fresh server failed before setup created the results directory.
- A Docker image inspection template was invalid; correcting the template recorded the digest.
- gpt-oss evaluation completed requests but failed while extracting a None response; it was retried.
- The first gpt-oss retry failed on another None response; one retry remained.
- The final gpt-oss retry also failed during extraction; the failure was escalated.
- Readiness probes returned resets or empty replies while models initialized; polling eventually succeeded.
- A local here-document expanded a literal curl token; the log entry was corrected.
- A tmux build wrapper created no session or log; running the build command directly succeeded.
- The deprecated huggingface-cli download command downloaded no GGUF file; the failure was escalated.
- Repetition-run readiness probes received resets while models loaded; subsequent polls succeeded.
- Sync checksums matched, but local and remote file counts differed because local results retained earlier sessions.
- A later SSH check failed host-key verification; refreshing the host-key entry restored access.
- Sync again ran before setup created the results directory and failed.
- The final session again found scratch storage unmounted; mounting it allowed setup to proceed.
- The container image pull took several minutes as planned.
- Quality evaluation installed dependencies at startup and warned about a missing chat-template option; evaluation completed.

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
