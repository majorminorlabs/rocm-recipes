
## 2026-10-08 18:05 CDT — `vllm serve --help` device inference

The first help invocation used `docker run --rm rocm/vllm:latest vllm serve --help` without the server's ROCm device flags. vLLM exited with `RuntimeError: Failed to infer device type`. Retrying with the server's `/dev/kfd`, `/dev/dri`, video group, IPC, and security flags. Time lost: about 1 minute.

## 2026-10-08 18:11 CDT — P2.3 tmux wrapper quoting

The first detached L1 sweep wrapper escaped `$len` and `$?` incorrectly. It exited before producing benchmark output or result files. Retrying with a runner script transferred to the droplet. Time lost: about 2 minutes.

## 2026-10-08 18:13 CDT — vLLM benchmark help flags

P2.3 first benchmark failed validation because `bench_long.sh` checked a short `vllm bench serve --help` summary that omits individual flags. `--help=all` confirms `--model`, `--backend`, random dataset/length flags, concurrency, prompts, seed, and result-save options. Updated the script to capture and validate full help before running benchmarks. Time lost: about 2 minutes.

## 2026-10-08 19:10 CDT — result inspection grep options

Two ad hoc status-inspection commands initially passed a pattern beginning with `--` to grep without the `--` end-of-options marker. Corrected the inspection commands; benchmark scripts and run data were unaffected. Time lost: under 1 minute.

## 2026-10-08 21:20 CDT — P4.3 status inspection quoting

An ad hoc remote status command had a local zsh unmatched-quote error due nested Python quoting. No remote command ran and no benchmark data was affected; reran status inspection with simpler quoting. Time lost: under 1 minute.

## 2026-10-08 21:33 CDT — M6 attempt A KV cache limit

M6 `131072 auto 0.92` loaded 131.45 GiB of model weights but failed KV cache initialization: 40.0 GiB was required and 23.08 GiB was available, for an estimated 75,632-token maximum model length. Captured the final 60 server-log lines and proceeded to decision-table attempt B. Time lost: about 3 minutes.

## 2026-10-08 21:36 CDT — M6 attempt B KV cache limit

M6 `131072 auto 0.95` failed KV cache initialization: 40.0 GiB was required and 28.83 GiB was available, for an estimated 94,480-token maximum model length. Captured the final 60 server-log lines and proceeded to decision-table attempt C. Time lost: about 2 minutes.

- 2026-10-09T13:17:13.865952+00:00 Session 2: BF16 attempt D1 served; (EngineCore pid=182) INFO 10-09 13:15:55 [kv_cache_utils.py:2032] GPU KV cache size: 134,336 tokens, Maximum concurrency for 131,072 tokens per request: 1.02x
