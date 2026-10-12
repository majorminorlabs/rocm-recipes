# Session 2 report

Recorded: 2026-10-09T16:21:03.622614+00:00

Stop reason: All Session 2 work completed

M6 BF16 serving attempt: D1.

Session droplet elapsed GPU hours: 3.3843.
Accumulated GPU hours: 8.8265.
Credit estimate remaining: $76.27 (approximately $83 at start minus elapsed hours × $1.99).

Droplet <droplet-id>: destroyed; independent doctl list confirmed absent.

| Step | Status | Note |
|---|---|---|
| P7.0 | DONE | Sole MI300X droplet <droplet-id> / <droplet-ip> matches config.env; batch SSH succeeded. |
| P7.1 | DONE | Session start 2026-10-09T13:04:57Z. Scratch mounted without formatting; session2_start snapshot synced with 0 differing files. |
| P7.2 | DONE | Pulled rocm/vllm:latest; rocm/vllm@sha256:e0ea9a10b729573ea8598bdc073bda0ea382fe1037eec7c0761b6fa7f46baaf4 |
| P7.3 | DONE | Haystack /mnt/scratch/haystack/pg2600.txt; detached sequential M6/M1/M4 downloads running. |
| P8.1 | DONE | BF16 served with attempt D1 |
| P8.2 | DONE | Completed: scripts/kv_capacity.sh L0-M6-bf16kv-D1 && test -f results/raw/L0/L0-M6-bf16kv-D1/backend.txt |
| P8.3 | DONE | Completed: python3 scripts/needle.py --run-id L3-M6-bf16kv-126976 --target-tokens 126976 --max-tokens 256 |
| P8.4 | DONE | Completed: python3 scripts/needle.py --run-id L3-M6-bf16kv-90112 --target-tokens 90112 --max-tokens 256 |
| P8.5 | DONE | Completed: python3 scripts/needle.py --run-id L3H-M6-bf16kv-32768 --target-tokens 32768 --max-tokens 256 --hard --haystack-file /mnt/scratch/haystack/pg2600.txt && python3 scripts/needle.py --run-id L3H-M6-bf16kv-126976 --target-tokens 126976 --max-tokens 256 --hard --haystack-file /mnt/scratch/haystack/pg2600.txt |
| P8.6 | DONE | Completed: scripts/stop_vllm.sh |
| P9.1 | DONE | Completed: scripts/serve_long.sh unsloth/Llama-3.3-70B-Instruct 131072 fp8 0.92 |
| P9.2 | DONE | Completed: scripts/kv_capacity.sh L0-M6-fp8kv-s2 |
| P9.3 | DONE | Completed: python3 scripts/needle.py --run-id L3-M6-fp8kv-90112 --target-tokens 90112 --max-tokens 256 |
| P9.4 | DONE | Completed: python3 scripts/needle.py --run-id L3-M6-fp8kv-110592 --target-tokens 110592 --max-tokens 256 |
| P9.5 | DONE | Completed: python3 scripts/needle.py --run-id L3H-M6-fp8kv-32768 --target-tokens 32768 --max-tokens 256 --hard --haystack-file /mnt/scratch/haystack/pg2600.txt && python3 scripts/needle.py --run-id L3H-M6-fp8kv-126976 --target-tokens 126976 --max-tokens 256 --hard --haystack-file /mnt/scratch/haystack/pg2600.txt |
| P9.6 | DONE | Completed: scripts/stop_vllm.sh && scripts/delete_weights.sh unsloth/Llama-3.3-70B-Instruct |
| P10.1 | DONE | Completed: scripts/serve_long.sh Qwen/Qwen3-Coder-30B-A3B-Instruct 262144 auto 0.92 |
| P10.2 | DONE | Completed: scripts/kv_capacity.sh L0-M1-bf16kv-s2 |
| P10.3 | DONE | Completed: python3 scripts/needle.py --run-id L3H-M1-bf16kv-32768 --target-tokens 32768 --max-tokens 256 --hard --haystack-file /mnt/scratch/haystack/pg2600.txt && python3 scripts/needle.py --run-id L3H-M1-bf16kv-258048 --target-tokens 258048 --max-tokens 256 --hard --haystack-file /mnt/scratch/haystack/pg2600.txt |
| P10.4 | DONE | Completed: scripts/stop_vllm.sh |
| P11.1 | DONE | Completed: scripts/serve_long.sh Qwen/Qwen3-Coder-30B-A3B-Instruct 262144 fp8 0.92 |
| P11.2 | DONE | Completed: scripts/kv_capacity.sh L0-M1-fp8kv-s2 |
| P11.3 | DONE | Completed: python3 scripts/needle.py --run-id L3H-M1-fp8kv-258048 --target-tokens 258048 --max-tokens 256 --hard --haystack-file /mnt/scratch/haystack/pg2600.txt |
| P11.4 | DONE | Completed: scripts/stop_vllm.sh && scripts/delete_weights.sh Qwen/Qwen3-Coder-30B-A3B-Instruct |
| P12.1 | DONE | Completed: scripts/serve_long.sh openai/gpt-oss-120b 131072 auto 0.92 |
| P12.2 | DONE | Completed: scripts/kv_capacity.sh L0-M4-autokv-s2 |
| P12.3 | DONE | Completed: python3 scripts/needle.py --run-id L3H-M4-autokv-32768 --target-tokens 32768 --max-tokens 2048 --hard --haystack-file /mnt/scratch/haystack/pg2600.txt --reasoning-effort low && python3 scripts/needle.py --run-id L3H-M4-autokv-126976 --target-tokens 126976 --max-tokens 2048 --hard --haystack-file /mnt/scratch/haystack/pg2600.txt --reasoning-effort low |
| P12.4 | DONE | Completed: scripts/stop_vllm.sh && scripts/delete_weights.sh openai/gpt-oss-120b |
| W1 | DONE | Stopped all containers and tmux jobs. |
| W2 | DONE | Collected session2_end snapshot. |
| W3 | DONE | Sync verified: 0 files differ. |
| W4 | DONE | Summary rebuilt; accumulated GPU hours updated. |
| W5 | DONE | Wrote factual notes/session_2_report.md. |
| W6 | DONE | Independent doctl check confirms droplet <droplet-id> absent. |
| W7 | DONE | Session 2 results and teardown committed on codex/session-2. |

| Hard needle run | needle_correct | distractor_hits | needle_errors |
|---|---|---|---|
| L3H-M1-bf16kv-258048 | 9/9 | 0 | 0 |
| L3H-M1-bf16kv-32768 | 9/9 | 0 | 0 |
| L3H-M1-fp8kv-258048 | 9/9 | 0 | 0 |
| L3H-M4-autokv-126976 | 5/9 | 3 | 0 |
| L3H-M4-autokv-32768 | 9/9 | 0 | 0 |
| L3H-M6-bf16kv-126976 | 7/9 | 2 | 0 |
| L3H-M6-bf16kv-32768 | 9/9 | 0 | 0 |
| L3H-M6-fp8kv-126976 | 7/9 | 1 | 0 |
| L3H-M6-fp8kv-32768 | 9/9 | 0 | 0 |
