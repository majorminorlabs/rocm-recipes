# Session 3 report

## Steps

- Completed: P8.0–P8.6; W1–W5.
- P8.3: six warm c1 runs completed with status ok (M1 BF16 warm1/warm2/warm3; M2 FP8 warm1/warm2/warm3). Both servers were stopped and weights deleted.
- P8.4: R3-M4 completed 250 gsm8k examples; strict-match exact_match=0.80 and flexible-extract exact_match=0.96. P3.3 is DONE.
- P8.5: P6.1–P6.4 completed. llama.cpp build commit `06cad0b9e77315bd2930bd4f70a6d7b37b2a01c`, build duration 130 seconds; R4-M5-q4km benchmark metadata and JSON are present and valid.
- P8.6 and W4: `summarize.py` rebuilt `results/summary.csv`.
- W3: `sync_results.sh` printed `Sync verified: 0 files differ`.

## GPU time and cost

- Session 3 elapsed through destruction: 0.7234 hours
- Total across Sessions 1–3: 2.8785 hours
- Estimated cost at $1.99/hour: $5.73
- Approximate remaining from $100: $94.27

## Droplet

- ID: <droplet-id>
- Droplet <droplet-id> was destroyed; `doctl compute droplet list` confirmed it absent.
