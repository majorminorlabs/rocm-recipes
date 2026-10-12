# Session 2 report

## Steps

- Completed: P4.0–P4.3; P3.1, P3.2, P3.4; P5.1; P6.1; P7.1–P7.2; W1, W2, W4.
- P3.3 escalated as ESC-004: all three R3-M4 evaluations completed 250 requests, then failed in lm-eval extraction on a `None` response.
- P6.2 escalated as ESC-005: the specified `huggingface-cli` command reports it is deprecated and no longer works; no GGUF file downloaded. P6.3–P6.4 remain TODO because they depend on P6.2.
- W3 is BLOCKED: checksum verification passed for 39 remote result files, but local results had 82 files because they include Session 1 outputs and locally generated setup data.
- `summarize.py` completed and wrote `results/summary.csv`; it reported no result JSON for failed R3-M4.

## GPU time and cost

- Session 2 elapsed at report: 1.3289 hours
- Total across Sessions 1 and 2: 2.1551 hours
- Estimated cost at $1.99/hour: $4.29
- Approximate remaining from $100: $95.71

## Droplet

- ID: 607088426
- Droplet 607088426 was destroyed; `doctl compute droplet list` confirmed it absent.
