#!/usr/bin/env bash
set -Eeuo pipefail
cd /root/rocm-recipes-005
run() {
  local c="$1" prompts="$2"
  local id="L2-M1-VT-K3-w1-c${c}-s2"
  echo "$(date -Iseconds) START $id"
  scripts/bench_engine.sh --dataset "custom:results/prompts/w1-c${c}.jsonl" "$id" L2 4096 512 "$c" "$prompts"
  echo "$(date -Iseconds) DONE $id"
}
run 1 8
run 4 16
run 8 32
run 16 64
