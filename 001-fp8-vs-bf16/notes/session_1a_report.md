# Session 1 report

Report time: 2026-10-07T13:23:33-05:00

## Steps

- Done: P1.1, P1.2, W1, W2, W3, W4.
- Blocked: P1.3, P1.4, P1.5, P2.1, P2.2, P2.3, P3.1, P3.2, P3.3, P3.4. SSH refused connections during result synchronization; ESC-002 was opened under section 13. Connectivity recovered during wrap-up, and W3 later completed. No Session 1 model benchmark or quality evaluation was run.

## Data and wrap-up

- `results/env/session1_start/` and `results/env/session1_end/` were collected.
- W3 sync verification passed. The `results/env/` and `results/raw/` trees each contained 14 files on both the Mac and droplet.
- `scripts/summarize.py` completed. No raw benchmark result JSON files were present.
- W1 stopped container `b96dda9f6de0`; no tmux jobs were listed.
- Scratch volume `/dev/vdc1` (label `DOSCRATCH`) was mounted at `/mnt/scratch`; `df -hT` reported 4.8T available.

## GPU time and credit estimate

- `CREATED_AT`: 2026-10-07T13:15:00-05:00
- GPU hours used through confirmed destruction (2026-10-07T13:23:59-05:00): 0.1498
- Estimated credits remaining from approximately $100 at $1.99/GPU-hour: $99.70

W6: `destroy.sh` confirmed droplet ID 607031393 absent; `doctl compute droplet list` also confirmed absence.
