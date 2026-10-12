#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT_DIR"; mkdir -p logs
LOG="logs/mount_scratch_$(date +%Y%m%d_%H%M%S).log"; exec > >(tee -a "$LOG") 2>&1
DRY=0; [[ "${1:-}" == --dry-run ]] && { DRY=1; shift; }; [[ $# == 0 ]] || { echo 'Usage: mount_scratch.sh [--dry-run]' >&2; exit 2; }
if (( DRY )); then printf '%s\n' 'mountpoint -q /mnt/scratch || mount DOSCRATCH-device /mnt/scratch after confirming ext4; df -hT /mnt/scratch'; exit 0; fi
if mountpoint -q /mnt/scratch; then mountpoint /mnt/scratch; exit 0; fi
dev="$(blkid -L DOSCRATCH)" || { echo 'DOSCRATCH device not found' >&2; exit 1; }
[[ -n "$dev" ]] || { echo 'DOSCRATCH device not found' >&2; exit 1; }
type="$(blkid -o value -s TYPE "$dev")"; [[ "$type" == ext4 ]] || { echo "Refusing filesystem type: $type" >&2; exit 1; }
mkdir -p /mnt/scratch; mount "$dev" /mnt/scratch; df -hT /mnt/scratch
