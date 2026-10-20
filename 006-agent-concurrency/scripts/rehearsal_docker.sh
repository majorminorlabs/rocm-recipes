#!/usr/bin/env bash
# rocm006-rehearsal-docker-v1: installed only on a dedicated CPU rehearsal host.
# The installer replaces this placeholder with the validated study root.
set -Eeuo pipefail
REHEARSAL_STUDY_ROOT='@REHEARSAL_STUDY_ROOT@'
if [[ ${REHEARSAL:-0} == 1 && ${1:-} == buildx && ${2:-} == bake && $(pwd -P) == "$REHEARSAL_STUDY_ROOT/atlas" ]]; then
    # data/ is deliberately a symlink outside cwd. Grant only this input tree.
    exec /usr/bin/docker buildx bake "--allow=fs.read=$REHEARSAL_STUDY_ROOT/results/rehearsal/atlas/data" "${@:3}"
fi
exec /usr/bin/docker "$@"
