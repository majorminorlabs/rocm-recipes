#!/usr/bin/env bash
# Root must repair its dedicated study tree BEFORE invoking any atlas process.
set -Eeuo pipefail
[[ $# == 1 && $1 =~ ^/home/atlas/[A-Za-z0-9_-]+$ && ! -L $1 ]] || exit 2
[[ $(id -u) == 0 ]] || exit 2
mkdir -p "$1"
# -h does not follow symlinks into shared caches or other checkouts.
chown -hR atlas:atlas "$1"
