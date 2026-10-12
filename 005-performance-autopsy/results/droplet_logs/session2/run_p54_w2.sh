#!/usr/bin/env bash
set -Eeuo pipefail
cd /root/rocm-recipes-005
run() {
  local id="$1" len="$2" conc="$3" prompts="$4"
  echo "$(date -Iseconds) START $id"
  scripts/bench_engine.sh "$id" L2 "$len" 256 "$conc" "$prompts"
  echo "$(date -Iseconds) DONE $id"
}
run L2-M1-VT-B-w2-32k-c1-s2 32768 1 4
run L2-M1-VT-B-w2-64k-c1-s2 65536 1 4
run L2-M1-VT-B-w2-127k-c1-s2 126976 1 2
run L2-M1-VT-B-w2-64k-c4-s2 65536 4 8
run L2-M1-VT-B-w2-64k-c8-s2 65536 8 16
run L2-M1-VT-B-w2-64k-c16-s2 65536 16 32
run L2-M1-VT-B-w2-127k-c2-s2 126976 2 4
run L2-M1-VT-B-w2-127k-c4-s2 126976 4 8
run L2-M1-VT-B-w2-127k-c8-s2 126976 8 16
