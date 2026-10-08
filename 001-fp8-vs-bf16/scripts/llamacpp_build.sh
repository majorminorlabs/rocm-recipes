#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs
LOG_FILE="logs/llamacpp_build_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
if [[ $# -ne 1 ]]; then echo "Usage: $0 <checkout_dir>" >&2; exit 2; fi
CHECKOUT_DIR="$1"
command -v hipconfig >/dev/null || { echo "hipconfig not found on host" >&2; exit 1; }
if [[ ! -d "$CHECKOUT_DIR/.git" ]]; then git clone https://github.com/ggml-org/llama.cpp "$CHECKOUT_DIR"; fi
HIPCXX="$(hipconfig -l)/clang" HIP_PATH="$(hipconfig -R)" cmake -S "$CHECKOUT_DIR" -B "$CHECKOUT_DIR/build" -DGGML_HIP=ON -DGPU_TARGETS=gfx942 -DCMAKE_BUILD_TYPE=Release
cmake --build "$CHECKOUT_DIR/build" --config Release -j "$(getconf _NPROCESSORS_ONLN)"
mkdir -p results/raw/R4
git -C "$CHECKOUT_DIR" rev-parse HEAD | tee results/raw/R4/llama_cpp_commit.txt
