# Session 1 report

- Completed all plan steps P0.1 through P6.1; no steps were blocked.
- P2.3 completed all six BF16 L1 lengths. The successful 1024 run is preserved as `L1-M1-bf16kv-in1024-retry1`; the earlier failed attempt remains preserved separately.
- P3.1 M1 FP8 KV capacity: 1,995,536 tokens; maximum concurrency 7.61.
- P4.1 M4 auto-KV capacity: 2,252,362 tokens; maximum concurrency 17.18. Four M4 needle lengths each returned 9/9 correct.
- M6 decision table: attempt A (`131072 auto 0.92`) failed KV sizing with 23.08 GiB available; attempt B (`131072 auto 0.95`) failed with 28.83 GiB available; attempt C (`131072 fp8 0.92`) served. Attempt C was used for M6 data.
- M6 FP8 KV capacity: 151,504 tokens; maximum concurrency 1.16. M6 L1 and L2 planned runs completed with status `ok`; needle runs scored 9/9 at 8192, 32768, and 65536, and 0/9 at 126976.
- Droplet elapsed time at W4: 5.4364 GPU hours.
- Estimated GPU charge: $10.82 at $1.99/GPU-hour. Estimated remaining credits: approximately $83.18 from the plan's approximately $94 starting balance.
- Final elapsed droplet time at destruction: 5.4422 GPU hours; estimated GPU charge: $10.83; estimated remaining credits: approximately $83.17.
- Droplet 607427599 was destroyed; `doctl compute droplet list` confirmed it absent.
