#!/usr/bin/env bash
# 006 P0.6. Local controller; --remote is the uploaded Linux worker entry point.
# Never provisions hardware. See notes/p08_fixes.md before first GPU use.
set -Eeuo pipefail
PIN=279889b8f42c607344781766503602a8c462f5df
TASK_COMMIT=019e10a72e37bf78c1ec52f335b3d4d3eec69e3d
MODEL=Qwen/Qwen3.8-27B
CONFIG=qwen38-27b-mi300x
CAMPAIGN=campaigns/rocm-recipes-006/manifests
usage() {
    cat <<'EOF'
Usage: atlas_remote.sh [--dry-run] session4|setup|probe|phase3b|sync-grading|run <c1|c4|c8|c16|c32>|serve <vllm|sglang>|status
Session 4: SESSION4=1 setup, then session4 (vLLM only, descending queues, budget guard).
SESSION4=1 disables probe, SGLang, c32 and 5b. Legacy actions remain for prior-session diagnostics.
Local config.env: ATLAS_SSH_TARGET=<root@host> (existing SSH transport), ATLAS_REMOTE_ROOT=/home/atlas/rocm-recipes-006
Optional ATLAS_SOURCE=../atlas; image/scratch settings as in 005.
setup copies ONLY the pinned tracked source, installs npm lock, builds native amd64
base/OpenCode/proxy images and all frozen native dependencies with 1x checks/map.
probe runs both engines sequentially: stop, serve, one-task ATLAS smoke, exactly eight tasks at c8, stop.
run starts one continuous manifest queue; no automatic retries or next-level launch.
REHEARSAL=1: dedicated remote root ending in -rehearsal; fake engines, native queues,
smoke 1 + probe 8 + two per c1/c4/c8/c16 + Kx-0 and c4 pair; all outputs results/rehearsal.
Use scripts/rehearse_006.py to run and wait for the entire sequence.
Jobs run in tmux; worker PID/log/exit code live in STATE.json under atlas.jobs.
--dry-run prints actions, never connects, builds, serves or runs inference.
EOF
}
fail() { echo "atlas_remote: $*" >&2; exit 1; }
REMOTE=0 DRY=0
if [[ ${1:-} == --remote ]]; then
    REMOTE=1; ROOT_DIR=$2; shift 2
else
    ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
fi
[[ ${1:-} != --dry-run ]] || { DRY=1; shift; }
[[ ${1:-} != --help && ${1:-} != -h ]] || { usage; exit 0; }
action=${1:-}; shift || true
case $action in
    setup|probe|phase3b|session4|status|sync-grading) [[ $# == 0 ]] || fail 'unexpected arguments';;
    run) [[ $# == 1 && $1 =~ ^c(1|4|8|16|32)$ ]] || fail 'expected concurrency level';;
    serve) [[ $# == 1 && $1 =~ ^(vllm|sglang)$ ]] || fail 'expected engine';;
    _s4-level) (( REMOTE )) && [[ $# == 1 && $1 =~ ^c(1|4|8|16)$ ]] || fail 'internal session-4 level';;
    _stop) (( REMOTE )) || fail 'internal stop entry point';;
    _job) (( REMOTE )) || fail 'internal entry point';;
    _kx-serve) (( REMOTE )) && [[ $# == 1 && $1 =~ ^(fcfs|lpm)$ ]] || fail 'internal Kx serve entry point';;
    *) usage >&2; exit 2;;
esac
cd "$ROOT_DIR"
# Explicit controller/worker environment wins over a saved production config.
overrides=()
for key in REHEARSAL SESSION4 ATLAS_SSH_TARGET ATLAS_REMOTE_ROOT SCRATCH_DIR CREATED_AT HARD_DEADLINE SESSION_CAP_HOURS; do
    if declare -p "$key" >/dev/null 2>&1; then overrides+=("$key=${!key}"); fi
done
if [[ -f config.env ]]; then
    set -a
    # shellcheck source=/dev/null
    source config.env
    set +a
fi
if (( ${#overrides[@]} )); then
    for override in "${overrides[@]}"; do export "${override?}"; done
fi
REHEARSAL=${REHEARSAL:-0}
[[ $REHEARSAL == 0 || $REHEARSAL == 1 ]] || fail 'REHEARSAL must be 0 or 1'
SESSION4=${SESSION4:-0}
[[ $action != session4 ]] || SESSION4=1
[[ $SESSION4 == 0 || $SESSION4 == 1 ]] || fail 'SESSION4 must be 0 or 1'
if [[ $SESSION4 == 1 ]]; then
    [[ $action != probe && $action != phase3b && $action != _kx-serve ]] || fail 'Amendment A disables probe and 5b'
    [[ $action != serve || ${1:-} == vllm ]] || fail 'Amendment A is vLLM only'
    [[ $action != run ]] || fail 'Use session4 for ordered queues and between-level budget guard'
fi
export REHEARSAL SESSION4
RESULTS_DIR="$ROOT_DIR/results"
CONTEXT_DIR="$ROOT_DIR"
PROBE_CAMPAIGN=data/rocm-recipes-006-probe
if [[ $REHEARSAL == 1 ]]; then
    RESULTS_DIR="$ROOT_DIR/results/rehearsal"; CONTEXT_DIR=$RESULTS_DIR
    CAMPAIGN=data/rocm-recipes-006-rehearsal
    PROBE_CAMPAIGN=data/rocm-recipes-006-rehearsal-probe
    [[ $action != run || ${1:-} != c32 ]] || fail 'no c32 in CPU rehearsal'
fi
LOG_DIR="$CONTEXT_DIR/logs"; NOTES_DIR="$CONTEXT_DIR/notes"; STATE_FILE="$CONTEXT_DIR/STATE.json"
ATLAS_SOURCE=${ATLAS_SOURCE:-../atlas}
ATLAS_REMOTE_ROOT=${ATLAS_REMOTE_ROOT:-/home/atlas/rocm-recipes-006}
ATLAS="$ROOT_DIR/atlas"
DB="$ATLAS/data/rocm-recipes-006/atlas.db"
[[ $REHEARSAL != 1 ]] || DB="$ATLAS/$CAMPAIGN/atlas.db"
IMAGE_MAP="$ATLAS/data/rocm-recipes-006-native/image-map.json"
if [[ $SESSION4 == 1 ]]; then
    CAMPAIGN=data/rocm-recipes-006-session4
    [[ $REHEARSAL != 1 ]] || CAMPAIGN=data/rocm-recipes-006-rehearsal-session4
    IMAGE_MAP="$ATLAS/data/rocm-recipes-006-native-session4/image-map.json"
fi
export PATH="/opt/atlas-node-24.21.0/bin:$PATH"
VLLM_IMAGE=${VLLM_IMAGE:-rocm/vllm@sha256:e0ea9a10b729573ea8598bdc073bda0ea382fe1037eec7c0761b6fa7f46baaf4}
SGLANG_IMAGE=${SGLANG_IMAGE:-lmsysorg/sglang@sha256:4420a7e492fce623285c635b9a6a7e09ccf77a3c812006494e4414655d46662d}
export VLLM_IMAGE SGLANG_IMAGE
# Root bootstrap provisions atlas:docker; all runtime work remains non-root.
state_job() {
    python3 - "$STATE_FILE" "$@" <<'PY'
import json,os,sys,tempfile
from datetime import datetime,timezone
path,job,phase,pid,*extra=sys.argv[1:]
d=json.load(open(path));a=d.setdefault('atlas',{});jobs=a.setdefault('jobs',{})
r=jobs.setdefault(job,{})
r.update(status=phase,pid=int(pid),updated_at=datetime.now(timezone.utc).isoformat())
if extra:r['exit_code']=int(extra[0])
r['log']='logs/atlas_'+job+'.log'
a['commit']='279889b8f42c607344781766503602a8c462f5df'
f=tempfile.NamedTemporaryFile('w',dir=os.path.dirname(path),delete=False)
json.dump(d,f,indent=2);f.write('\n');f.close();os.replace(f.name,path)
PY
}
record_setup_step() {
    [[ $SESSION4 == 1 ]] || return 0
    local args=(); [[ $REHEARSAL != 1 ]] || args+=(--rehearsal)
    python3 "$ROOT_DIR/scripts/session4_setup_006.py" --root "$ROOT_DIR" --atlas "$ATLAS" "${args[@]}" --record-step "$1" --seconds "$2" || true
}
check_pin() {
    [[ $(git -C "$ATLAS" rev-parse HEAD) == "$PIN" ]] || fail 'ATLAS checkout differs from 279889b'
    [[ -z $(git -C "$ATLAS" status --porcelain --untracked-files=no) ]] || fail 'tracked ATLAS source changed'
}
preflight() {
    check_pin
    if [[ $REHEARSAL == 1 ]]; then
        [[ -L $ATLAS/data && $(readlink "$ATLAS/data") == "$RESULTS_DIR/atlas/data" ]] || fail 'rehearsal data must resolve inside results/rehearsal'
    fi
    [[ $(uname -m) == x86_64 && $(id -u) != 0 ]] || fail 'requires native x86_64 Linux and non-root Docker user'
    python3 - "$ATLAS/data" "$RESULTS_DIR" "$LOG_DIR" "$NOTES_DIR" "$STATE_FILE" <<'PYOWN'
import os,sys
from pathlib import Path
for name in sys.argv[1:]:
 p=Path(name)
 if p.exists() and p.stat().st_uid!=os.getuid():
  raise SystemExit('atlas must own writable path before handoff: '+name)
PYOWN
    (cd "$ATLAS"; sha256sum -c tasks/CHECKSUMS > "$LOG_DIR/tasks_checksums.log")
    (cd "$ATLAS"; node runner/cli.ts check-host "$IMAGE_MAP")
}
stop_server() {
    if [[ $REHEARSAL == 1 ]]; then
        python3 "$ROOT_DIR/scripts/fake_engine_006.py" stop --root "$ROOT_DIR"
    else
        "$ROOT_DIR/scripts/stop_engine.sh"
    fi
}
serve() {
    local engine=$1 policy=${2:-lpm}
    stop_server || return
    if [[ $REHEARSAL == 1 ]]; then
        python3 "$ROOT_DIR/scripts/fake_engine_006.py" start --root "$ROOT_DIR" --engine "$engine" --policy "$policy"
        return
    fi
    # 005 best observed: VT T; SD K3 (T regressed). Prefix caching stays on.
    if [[ $engine == vllm ]]; then
        KNOB_SET=T KNOB_PREFIX_CACHE=1 SERVE_ENV=VLLM_ROCM_USE_AITER=1 \
        "$ROOT_DIR/scripts/serve_engine.sh" vllm VT "$MODEL" 131072 \
            --dtype bfloat16 --enable-prefix-caching --max-num-batched-tokens 16384 \
            --enable-prompt-tokens-details --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3
    else
        KNOB_SET=K3 KNOB_PREFIX_CACHE=1 SERVE_ENV='' \
        "$ROOT_DIR/scripts/serve_engine.sh" sglang SD "$MODEL" 131072 \
            --dtype bfloat16 --enable-cache-report --schedule-policy "$policy" \
            --tool-call-parser qwen3_coder --reasoning-parser qwen3
    fi
    local serve_rc=$?
    (( serve_rc == 0 )) || return "$serve_rc"
    # Metadata/help use the ready server's exact container context. Never gate eligibility.
    python3 "$ROOT_DIR/scripts/engine_metadata_006.py" --root "$ROOT_DIR" --engine "$engine" \
        --scratch "${SCRATCH_DIR:-/mnt/scratch}" --model "$MODEL" \
        2>> "$LOG_DIR/${engine}_provenance_errors.log" || true
    # Exact args/images are retained by serve_engine; no thinking/template overrides.
}
queue() {
    local manifest=$1 db=$2 sampler rc=0 engine sample_key level export_manifest
    export_manifest=${3:-$manifest}
    [[ $db == /* ]] || db="$ATLAS/$db"
    level=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["study"]["level"])' "$ATLAS/$manifest") || return
    engine=$(python3 -c 'import json; print(json.load(open(__import__("os").environ["ATLAS_CURRENT_SERVER"]))["engine"])') || return
    sample_key=$(basename "$manifest" .json)
    # Finished queues resume export only; do not add duplicate TTFT boundaries.
    if [[ -f $db ]] && (cd "$ATLAS"; node --input-type=module - "$manifest" "$db" <<'JSDONE'
import {loadManifest} from './runner/manifest.ts';
import {Store} from './runner/store.ts';
const loaded=await loadManifest(process.argv[2]),store=new Store(process.argv[3]);
try{process.exitCode=loaded.runs.every(r=>store.db.prepare('SELECT state FROM runs WHERE run_id=?').get(r.runId)?.state==='finished')?0:1;}finally{store.close();}
JSDONE
    ); then
        (cd "$ATLAS"; node "$ROOT_DIR/scripts/atlas_export_006.ts" "$export_manifest" "$db")
        return $?
    fi
    if [[ ${SESSION4_LEVEL_SAMPLING:-0} != 1 ]]; then
        python3 "$ROOT_DIR/scripts/sample_006.py" "$RESULTS_DIR/raw/$sample_key/samples.jsonl" "$engine" "$level" before || return
    fi
    python3 "$ROOT_DIR/scripts/sample_006.py" "$RESULTS_DIR/raw/$sample_key/samples.jsonl" "$engine" "$level" &
    sampler=$!; SAMPLER_PID=$sampler
    (cd "$ATLAS"; node runner/cli.ts run-manifest "$manifest" --db "$db" --image-map "$IMAGE_MAP") || rc=$?
    kill "$sampler" 2>/dev/null || true
    wait "$sampler" || true
    SAMPLER_PID=''
    if [[ ${SESSION4_LEVEL_SAMPLING:-0} != 1 ]]; then
        python3 "$ROOT_DIR/scripts/sample_006.py" "$RESULTS_DIR/raw/$sample_key/samples.jsonl" "$engine" "$level" after || return
    fi
    (( rc == 0 )) || return "$rc"
    mkdir -p "$RESULTS_DIR/grading/returned"
    # Live grading/export. Missing-STATUS semantic audits are deferred to the Mac.
    (cd "$ATLAS"; node "$ROOT_DIR/scripts/atlas_export_006.ts" "$export_manifest" "$db")
}
probe() {
    preflight
    python3 "$ROOT_DIR/scripts/probe_006.py" "$ATLAS"
    local engine stage
    PROBE_ACTIVE=1
    for engine in vllm sglang; do
        # Capture engine failure and continue to the other candidate; no fallback tuning.
        if ! (set -e; serve "$engine"); then
            echo "$engine startup failed" > "$LOG_DIR/probe_$engine.failure"
            stop_server
            continue
        fi
        for stage in smoke c8; do
            local stage_rc=0
            (set -e; queue "$PROBE_CAMPAIGN/$engine-$stage.json" \
                "$PROBE_CAMPAIGN/$engine-$stage.db") || stage_rc=$?
            if (( stage_rc != 0 )); then
                echo "$engine $stage failed" > "$LOG_DIR/probe_$engine.failure"
                break
            fi
        done
        stop_server
    done
    (cd "$ATLAS"; node "$ROOT_DIR/scripts/atlas_export_006.ts" --choose "$NOTES_DIR/engine_choice.md")
    PROBE_ACTIVE=0
}
start_job() {
    local job=$1; shift
    # One session for ALL wrapper work prevents overlapping queues/engine changes.
    tmux has-session -t rocm006-atlas 2>/dev/null && fail 'rocm006-atlas job already active'
    local cmd
    printf -v cmd '%q ' env REHEARSAL="$REHEARSAL" SESSION4="$SESSION4" bash "$ROOT_DIR/scripts/atlas_remote.sh" --remote "$ROOT_DIR" _job "$job" "$@"
    tmux new-session -d -s rocm006-atlas "$cmd"
    echo "Started $job in tmux rocm006-atlas; log $LOG_DIR/atlas_$job.log"
}
if (( DRY )); then
    if [[ $REHEARSAL == 1 ]]; then
        echo "REHEARSAL=1; results/rehearsal only; fake engine :8000; GPU samples null; production native prepare/check-host/proxy/grading/export."
        [[ $SESSION4 == 1 ]] || echo 'Queues: smoke=1, probe=8 at c8, main=2 each c1/c4/c8/c16; Kx-0=8 then FCFS/LPM=20 each at c4; solved-count tie forces SGLang, recorded.'
    fi
    printf 'ATLAS pin: %s\nConfig: %s\nEngine: http://localhost:8000/v1 (proxy container: http://host.docker.internal:8000/v1, pinned host-gateway mapping)\n' "$PIN" "$CONFIG"
    if [[ $SESSION4 == 1 ]]; then
        echo 'Amendment A / session 4: use unchanged session-3 vLLM choice; no probe, SGLang pull, c32 or 5b.'
        echo 'Restore checkpointed session-3 DB; retain c18/c28/c09 native verdicts; c22 infra reruns. c1 first ten seeded tasks, only seven new runs.'
        echo 'Setup: vLLM pull only; weights download parallel with native prepare/check-host; record setup_timings.json.'
        echo 'Sequence: c16 (30 x 1) -> c8 (30) -> c4 (30) -> c1 (10 total, 7 new); rehearsal uses 2/2/2/7 new tasks, no engine pull or weights.'
        echo 'After each finished level: elapsed + observed wall*concurrency/count * remaining count/concurrency + 1h buffer; >10.5h drops c1 then c4 and reprojects; if c8 cannot fit, wrap. Never interrupt a level for projection.'
        echo 'SESSION_CAP_HOURS=10; HARD_DEADLINE=CREATED_AT+10.5h. Live export, pending Mac handoff counts, matched ten-task summary; normal wrap-up.'
        exit 0
    fi
    case $action in
    setup) echo 'Local: pack ONLY pinned Git history; upload pack + 006 scripts to existing SSH target; bootstrap as root creates atlas:docker, installs Node 24.21.0 + tmux, records versions.'
        echo 'Remote as atlas, detached: checkout 279889b; npm ci; atlas prepare-host data/rocm-recipes-006-native --prefix atlas-rocm006-native; 30 native 1x base/reference pairs; atlas check-host image-map.json; native proxy build.';;
    serve|probe)
        engines=("${1:-vllm}"); [[ $action != probe ]] || engines=(vllm sglang)
        for engine in "${engines[@]}"; do
            if [[ $REHEARSAL != 1 ]]; then echo "stop_engine.sh; serve $engine (005 best config, BF16, context 131072); collect metadata/help after readiness via docker exec, non-fatal null + error"; fi
            if [[ $REHEARSAL == 1 ]]; then
                echo "fake_engine_006.py start --engine $engine; no GPU server or GPU image pull"
            elif [[ $engine == vllm ]]; then
                KNOB_SET=T KNOB_PREFIX_CACHE=1 SERVE_ENV=VLLM_ROCM_USE_AITER=1 scripts/serve_engine.sh --dry-run vllm VT "$MODEL" 131072 --dtype bfloat16 --enable-prefix-caching --max-num-batched-tokens 16384 --enable-prompt-tokens-details --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3
            else
                KNOB_SET=K3 KNOB_PREFIX_CACHE=1 SERVE_ENV='' scripts/serve_engine.sh --dry-run sglang SD "$MODEL" 131072 --dtype bfloat16 --enable-cache-report --schedule-policy lpm --tool-call-parser qwen3_coder --reasoning-parser qwen3
            fi
            [[ $action != probe ]] || echo 'One-task ATLAS smoke; exactly eight seeded c8 tasks including C13/C18/C45; no c1 stage; smoke requires nonzero proxy cached tokens after the first request; grade/export; stop_engine.sh'
        done
        [[ $action != probe ]] || echo 'Write notes/engine_choice.md: record reporting-only cache flags; reject broken tools/cache reporting; compare c8 solved/hour, tie on solved count by output tok/s.';;
    run) echo "Detached: atlas run-manifest $CAMPAIGN/$1.json --db ${DB#"$ATLAS"/} --image-map data/rocm-recipes-006-native/image-map.json; bracket engine-side TTFT histograms; live hidden-test metrics, defer missing STATUS without pausing; PID to local and remote STATE.json"
        if [[ $REHEARSAL == 1 ]]; then echo 'CPU rehearsal gate: same served choice, two completed tasks per earlier level; no GPU projection or scored dispatch.';
        else echo 'Require completed P0.3-P0.8, engine_choice, budget/scaling gates; no automatic next level.'; fi;;
    sync-grading) echo 'Post-session sync of live results, native grading requests/evidence and samples; Mac audits then finalize_006.py; no queue waits.';;
    phase3b)
        if [[ $REHEARSAL == 1 ]]; then
            echo 'CPU rehearsal: verify four completed 2-task native levels; pinned SGLang CPU tokenizer only (no weights); Kx builder --user atlas UID:GID, HF_HOME=/hf; Kx-0 8 then fresh FCFS/LPM 20 each at c4.'
            echo 'Record all requests, per-group TTFT/hit rate/failures, Kx notes and scoped state under results/rehearsal; no GPU budget projection.'
            exit 0
        fi
        echo 'Check P3 complete, P0.9/P0.8 reviewed, c1 projection without 5b <=9.5h, >=60 minutes to HARD_DEADLINE, and KX_SKIP.'
        echo 'Build W-MP inside pinned SGLang image: G1/G2/G3/G4 p25/p50/p75/p95 cached prefixes (fallback 2048/4096/8192/16384), 40/30/20/10 shares, fixed seeds + SHA-256.'
        echo 'Kx-0: fresh SGLang fcfs; 8 requests, 2/group; metric exists/changes + tags; restart lpm and confirm readiness. Any failure skips 5b.'
        echo 'Fresh SGLang for each run, both policies use reporting-only --enable-cache-report; policy is the only flag changed: FCFS then LPM; 256 requests at c16 (c32 if it ran), optional 128 requests at c8.'
        echo 'Use a separate SGLang server if main probe picked vLLM; stop_engine.sh between runs; write notes/kx_metrics.md, notes/kx_report.md; drop reasons to friction.md.';;
    status) echo 'Read remote STATE.json and refresh only local atlas job metadata.';;
    esac
    exit 0
fi
if (( ! REMOTE )) && [[ $SESSION4 == 1 && $REHEARSAL == 0 && ( $action == setup || $action == session4 ) ]]; then
    bash "$ROOT_DIR/scripts/preflight_006.sh"
fi
if (( REMOTE )); then
    if [[ $REHEARSAL == 1 ]]; then
        [[ $ROOT_DIR =~ ^/home/atlas/[A-Za-z0-9_-]+-rehearsal$ ]] || fail 'rehearsal requires a dedicated remote root ending in -rehearsal'
    fi
    if [[ $action == setup && $(id -u) != 0 && ! -f $LOG_DIR/bootstrap_versions.json ]]; then
        sudo -n bash "$ROOT_DIR/scripts/atlas_bootstrap_006.sh" "$ROOT_DIR"
    fi
    if [[ $(id -u) == 0 ]]; then
        if [[ $action == setup ]]; then
            bootstrap_started=$SECONDS
            bash "$ROOT_DIR/scripts/atlas_bootstrap_006.sh" "$ROOT_DIR"
            record_setup_step bootstrap "$((SECONDS-bootstrap_started))"
        fi
        bash "$ROOT_DIR/scripts/atlas_ownership_006.sh" "$ROOT_DIR"
        exec runuser -u atlas -- env REHEARSAL="$REHEARSAL" SESSION4="$SESSION4" HOME=/home/atlas PATH="$PATH" bash "$ROOT_DIR/scripts/atlas_remote.sh" --remote "$ROOT_DIR" "$action" "$@"
    fi
    [[ $(id -un) == atlas ]] || fail 'remote work must run as the bootstrap-created atlas user'
    mkdir -p "$LOG_DIR" "$NOTES_DIR" "$RESULTS_DIR/grading/pending" "$RESULTS_DIR/grading/returned" "$RESULTS_DIR/grading/counts" "$RESULTS_DIR/raw" "$RESULTS_DIR/live" "$RESULTS_DIR/atlas"
    if [[ $REHEARSAL == 1 && ! -f $STATE_FILE ]]; then
        python3 - "$ROOT_DIR/STATE.json" "$STATE_FILE" <<'PYSTATE'
import json,sys
s=json.load(open(sys.argv[1]));s['atlas']={'jobs':{}};s['rehearsal']=True
open(sys.argv[2],'w').write(json.dumps(s,indent=2)+'\n')
PYSTATE
    fi
    export ATLAS_CURRENT_SERVER="$LOG_DIR/current_server.json"
    if [[ $action == _job ]]; then
        job=$1; shift
        exec > >(tee -a "$LOG_DIR/atlas_$job.log") 2>&1
        state_job "$job" RUNNING "$$"
        # shellcheck disable=SC2329 # Invoked by EXIT trap.
        finish_job() {
            local rc=$?
            trap - EXIT
            if [[ -n ${SAMPLER_PID:-} ]]; then kill "$SAMPLER_PID" 2>/dev/null || true; wait "$SAMPLER_PID" || true; fi
            if [[ ${PROBE_ACTIVE:-0} == 1 || ${KX_ACTIVE:-0} == 1 || ${SESSION4_ACTIVE:-0} == 1 ]]; then stop_server || true; fi
            state_job "$job" "$([[ $rc == 0 ]] && echo DONE || echo FAILED)" "$$" "$rc"
            exit "$rc"
        }
        trap finish_job EXIT
        case $job in
        setup)
            checkout_started=$SECONDS
            [[ ! -e $ATLAS ]] || fail 'setup destination exists; retain it and inspect before retry'
            mkdir "$ATLAS"
            git -C "$ATLAS" init -q
            git -C "$ATLAS" unpack-objects < "$ROOT_DIR/atlas.pack"
            git -C "$ATLAS" update-ref refs/tags/tasks-v1 "$TASK_COMMIT"
            git -C "$ATLAS" -c advice.detachedHead=false checkout --detach "$PIN"
            check_pin
            record_setup_step checkout "$((SECONDS-checkout_started))"
            if [[ $REHEARSAL == 1 ]]; then
                [[ ! -e $ATLAS/data ]] || fail 'rehearsal requires fresh data'
                mkdir -p "$RESULTS_DIR/atlas/data"
                ln -s "$RESULTS_DIR/atlas/data" "$ATLAS/data"
                python3 "$ROOT_DIR/scripts/rehearsal_006.py" "$ATLAS"
            fi
            [[ $(uname -m) == x86_64 ]] || fail 'native x86_64 host required'
            if [[ $SESSION4 == 1 ]]; then
                local_args=(); [[ $REHEARSAL != 1 ]] || local_args+=(--rehearsal)
                restore_started=$SECONDS
                if [[ $REHEARSAL != 1 && -f $ROOT_DIR/results/session4/resume.json ]]; then
                    python3 "$ROOT_DIR/scripts/session4_recover_006.py" restore --root "$ROOT_DIR" --atlas "$ATLAS"
                fi
                python3 "$ROOT_DIR/scripts/session4_006.py" prepare --root "$ROOT_DIR" --atlas "$ATLAS" "${local_args[@]}"
                record_setup_step resume_and_manifests "$((SECONDS-restore_started))"
                python3 "$ROOT_DIR/scripts/session4_setup_006.py" --root "$ROOT_DIR" --atlas "$ATLAS" "${local_args[@]}"
                cp "$ROOT_DIR/inputs/session4/engine_choice.json" "$NOTES_DIR/engine_choice.json"
            else
                (cd "$ATLAS"; npm ci
                    node runner/cli.ts prepare-host data/rocm-recipes-006-native --prefix atlas-rocm006-native
                    node runner/cli.ts check-host "$IMAGE_MAP"
                    node proxy/build.ts --platform linux/amd64)
            fi
            preflight;;
        session4)
            preflight
            python3 -c "import sys;sys.path.insert(0,'$ROOT_DIR/scripts');from session4_006 import lifecycle;lifecycle()"
            SESSION4_ACTIVE=1
            serve vllm
            python3 "$ROOT_DIR/scripts/session4_flow_006.py" --root "$ROOT_DIR"
            stop_server
            SESSION4_ACTIVE=0;;
        probe) probe;;
        phase3b)
            KX_ACTIVE=1
            python3 "$ROOT_DIR/scripts/kx_006.py" --root "$ROOT_DIR"
            KX_ACTIVE=0;;
        serve-*) serve "$1";;
        run-*)
            preflight
            if [[ $REHEARSAL == 1 ]]; then
                python3 - "$ROOT_DIR" "$1" <<'PYGATE'
import sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'scripts'))
from rehearsal_006 import gate
gate(Path(sys.argv[1]),sys.argv[2])
PYGATE
            else
                python3 "$ROOT_DIR/scripts/atlas_gate_006.py" "$ROOT_DIR" "$1"
            fi
            queue "$CAMPAIGN/$1.json" "$DB"
            if [[ $1 == c1 && $REHEARSAL != 1 ]]; then python3 "$ROOT_DIR/scripts/atlas_gate_006.py" "$ROOT_DIR" c4; fi;;
        *) fail 'unknown job';;
        esac
    elif [[ $action == _s4-level ]]; then
        [[ $SESSION4 == 1 ]] || fail 'session-4 context required'
        preflight
        # One histogram delta covers the complete level, including infra retries.
        export SESSION4_LEVEL_SAMPLING=1
        boundary=before
        if ! python3 - "$RESULTS_DIR/raw/$1/samples.jsonl" "$boundary" <<'PYBOUND'
import json,sys
from pathlib import Path
p=Path(sys.argv[1])
sys.exit(0 if p.exists() and any(json.loads(s).get('boundary')==sys.argv[2] for s in p.read_text().splitlines()) else 1)
PYBOUND
        then python3 "$ROOT_DIR/scripts/sample_006.py" "$RESULTS_DIR/raw/$1/samples.jsonl" vllm "$1" "$boundary"; fi
        queue "$CAMPAIGN/$1.json" "$DB"
        for retry_round in 1 2; do
            retry_manifest=$(python3 "$ROOT_DIR/scripts/session4_retry_006.py" "$ATLAS/$CAMPAIGN" "$DB" "$1" "$retry_round")
            [[ -n $retry_manifest ]] || break
            queue "${retry_manifest#"$ATLAS/"}" "$DB" "$CAMPAIGN/$1.json"
        done
        if ! python3 - "$RESULTS_DIR/raw/$1/samples.jsonl" <<'PYBOUND'
import json,sys
from pathlib import Path
sys.exit(0 if any(json.loads(s).get('boundary')=='after' for s in Path(sys.argv[1]).read_text().splitlines()) else 1)
PYBOUND
        then python3 "$ROOT_DIR/scripts/sample_006.py" "$RESULTS_DIR/raw/$1/samples.jsonl" vllm "$1" after; fi
        (cd "$ATLAS"; node "$ROOT_DIR/scripts/atlas_export_006.ts" "$CAMPAIGN/$1.json" "$DB")
    elif [[ $action == _stop ]]; then stop_server
    elif [[ $action == _kx-serve ]]; then serve sglang "$1"
    elif [[ $action == status ]]; then cat "$STATE_FILE"
    elif [[ $action == run ]]; then start_job "run-$1" "$1"
    elif [[ $action == serve ]]; then start_job "serve-$1" "$1"
    else start_job "$action"
    fi
    exit 0
fi
# Local controller. --dry-run exits above, before any SSH/SCP command.
[[ -n ${ATLAS_SSH_TARGET:-} && $ATLAS_SSH_TARGET =~ ^[a-z_][a-z0-9_-]*@[A-Za-z0-9.-]+$ ]] || fail 'set ATLAS_SSH_TARGET to root@existing-host or the atlas user'
[[ $ATLAS_REMOTE_ROOT =~ ^/home/atlas/[A-Za-z0-9_-]+$ ]] || fail 'unsafe ATLAS_REMOTE_ROOT'
ssh_args=(-o BatchMode=yes -o ConnectTimeout=10)
REMOTE_RESULTS="$ATLAS_REMOTE_ROOT/results"
REMOTE_STATE="$ATLAS_REMOTE_ROOT/STATE.json"
if [[ $REHEARSAL == 1 ]]; then
    [[ $ATLAS_REMOTE_ROOT == *-rehearsal ]] || fail 'rehearsal remote root must end in -rehearsal'
    REMOTE_RESULTS="$REMOTE_RESULTS/rehearsal"; REMOTE_STATE="$REMOTE_RESULTS/STATE.json"
    mkdir -p "$RESULTS_DIR"
    [[ -f $STATE_FILE ]] || cp STATE.json "$STATE_FILE"
fi
if [[ $action == sync-grading ]]; then
    mkdir -p "$RESULTS_DIR/grading/pending" "$RESULTS_DIR/grading/returned" "$RESULTS_DIR/atlas" "$RESULTS_DIR/live" "$RESULTS_DIR/raw"
    for part in atlas live raw grading/pending grading/counts; do
        mkdir -p "$RESULTS_DIR/$part"
        rsync -a -e ssh "$ATLAS_SSH_TARGET:$REMOTE_RESULTS/$part/" "$RESULTS_DIR/$part/"
    done
    rsync -a -e ssh "$RESULTS_DIR/grading/returned/" "$ATLAS_SSH_TARGET:$REMOTE_RESULTS/grading/returned/"
    if [[ $ATLAS_SSH_TARGET == root@* ]]; then
        # shellcheck disable=SC2029 # Validated dedicated study path.
        ssh "${ssh_args[@]}" "$ATLAS_SSH_TARGET" "bash '$ATLAS_REMOTE_ROOT/scripts/atlas_ownership_006.sh' '$ATLAS_REMOTE_ROOT'"
    fi
    if [[ $SESSION4 == 1 ]]; then
        mkdir -p "$RESULTS_DIR/session4"
        rsync -a -e ssh "$ATLAS_SSH_TARGET:$REMOTE_RESULTS/session4/" "$RESULTS_DIR/session4/"
        for note in budget_check.md budget_check.jsonl; do
            [[ ! -f $RESULTS_DIR/session4/$note ]] || cp "$RESULTS_DIR/session4/$note" "$NOTES_DIR/$note"
        done
    fi
    echo 'Native requests/tests synced to Mac; audited responses returned. Classify/audit each pending request explicitly with atlas_mac_grade_006.ts, then finalize_006.py on the Mac after the session; queued work never waits.'
    exit 0
fi
if [[ $action == setup ]]; then
    if [[ $SESSION4 == 1 ]]; then python3 scripts/session4_006.py bundle --atlas "$ATLAS_SOURCE"; fi
    [[ $(git -C "$ATLAS_SOURCE" rev-parse "$PIN") == "$PIN" ]] || fail 'missing pinned ATLAS commit'
    temp=$(mktemp -d)
    trap 'rm -r -- "$temp"' EXIT
    # Read-only source: pack reachable objects, never working-tree files, data or credentials.
    printf '%s\n' "$PIN" | git -C "$ATLAS_SOURCE" pack-objects --revs --stdout > "$temp/atlas.pack"
    # shellcheck disable=SC2029 # Validated paths intentionally expand on the controller.
    ssh "${ssh_args[@]}" "$ATLAS_SSH_TARGET" "test ! -e '$ATLAS_REMOTE_ROOT/atlas' && mkdir -p '$ATLAS_REMOTE_ROOT/scripts' '$ATLAS_REMOTE_ROOT/logs'"
    cp STATE.json "$temp/STATE.json"
    # Send only serving settings, never cloud credentials or lifecycle configuration.
    { printf 'VLLM_IMAGE=%q\nSGLANG_IMAGE=%q\nSCRATCH_DIR=%q\n' "$VLLM_IMAGE" "$SGLANG_IMAGE" "${SCRATCH_DIR:-/mnt/scratch}"
      for key in CREATED_AT HARD_DEADLINE SESSION_CAP_HOURS KX_SKIP REHEARSAL SESSION4; do
          [[ -z ${!key:-} ]] || printf '%s=%q\n' "$key" "${!key}"
      done; } > "$temp/config.env"
    scp "${ssh_args[@]}" "$temp/atlas.pack" "$temp/STATE.json" "$temp/config.env" "$ATLAS_SSH_TARGET:$ATLAS_REMOTE_ROOT/"
    scp "${ssh_args[@]}" scripts/atlas_remote.sh scripts/atlas_export_006.ts scripts/atlas_gate_006.py scripts/summarize_006.py scripts/serve_engine.sh scripts/stop_engine.sh scripts/gpu_sampler.py scripts/sample_006.py scripts/ttft_006.py scripts/probe_006.py scripts/atlas_bootstrap_006.sh scripts/atlas_mac_grade_006.ts scripts/prefix_sched.py scripts/build_wmp.py scripts/kx_006.py scripts/finalize_006.py scripts/engine_metadata_006.py scripts/atlas_ownership_006.sh scripts/rehearsal_006.py scripts/fake_engine_006.py scripts/session4_006.py scripts/session4_setup_006.py scripts/session4_flow_006.py scripts/session4_retry_006.py scripts/export_support_006.ts scripts/session4_recover_006.py scripts/session4_retained_006.ts "$ATLAS_SSH_TARGET:$ATLAS_REMOTE_ROOT/scripts/"
    if [[ $SESSION4 == 1 ]]; then
        # Root-created upload paths are handed to atlas by the existing ownership repair.
        scp -r "${ssh_args[@]}" inputs/session4 "$ATLAS_SSH_TARGET:$ATLAS_REMOTE_ROOT/inputs-session4"
        # shellcheck disable=SC2029 # Validated dedicated root; inputs contain no credentials.
        ssh "${ssh_args[@]}" "$ATLAS_SSH_TARGET" "mkdir -p '$ATLAS_REMOTE_ROOT/inputs' '$ATLAS_REMOTE_ROOT/notes' && mv '$ATLAS_REMOTE_ROOT/inputs-session4' '$ATLAS_REMOTE_ROOT/inputs/session4'"
        if [[ $REHEARSAL != 1 ]]; then scp "${ssh_args[@]}" notes/budget_check.md "$ATLAS_SSH_TARGET:$ATLAS_REMOTE_ROOT/notes/budget_check.md"; fi
        if [[ $REHEARSAL != 1 && -f results/session4/resume.json ]]; then
            # This archive contains execution evidence only. Fresh native builds
            # and check-host run before pending grading, then the c8 queue.
            # shellcheck disable=SC2029 # Validated dedicated root expands locally.
            ssh "${ssh_args[@]}" "$ATLAS_SSH_TARGET" "mkdir -p '$ATLAS_REMOTE_ROOT/results/session4'"
            resume_files=(results/session4/resume.json)
            while IFS= read -r resume_name; do resume_files+=("results/session4/$resume_name"); done < <(python3 - <<'PYRESUME'
import json
from pathlib import Path
for name in json.load(open('results/session4/resume.json'))['files']:
    if Path(name).name != name:raise ValueError('Unsafe resume checkpoint filename')
    print(name)
PYRESUME
            )
            scp "${ssh_args[@]}" "${resume_files[@]}" "$ATLAS_SSH_TARGET:$ATLAS_REMOTE_ROOT/results/session4/"
        fi
    fi
fi
printf -v remote_cmd '%q ' env REHEARSAL="$REHEARSAL" SESSION4="$SESSION4" bash "$ATLAS_REMOTE_ROOT/scripts/atlas_remote.sh" --remote "$ATLAS_REMOTE_ROOT" "$action" "$@"
# shellcheck disable=SC2029 # remote_cmd contains individually printf-%q escaped arguments.
ssh "${ssh_args[@]}" "$ATLAS_SSH_TARGET" "$remote_cmd"
# Worker records its actual PID, not the SSH/tmux launcher PID. Poll startup briefly.
expected_job=$action
[[ $action != run && $action != serve ]] || expected_job="$action-$1"
synced=0
for _ in 1 2 3 4 5; do
    # shellcheck disable=SC2029 # Validated remote path.
    snapshot=$(ssh "${ssh_args[@]}" "$ATLAS_SSH_TARGET" "cat '$REMOTE_STATE'")
    if python3 - "$snapshot" "$STATE_FILE" "$expected_job" <<'PY'
import json,os,sys,tempfile
remote=json.loads(sys.argv[1]);path=sys.argv[2];local=json.load(open(path))
if 'atlas' not in remote:sys.exit(1)
action=sys.argv[3]
if action!='status' and not remote['atlas'].get('jobs',{}).get(action,{}).get('pid'):sys.exit(1)
local['atlas']=remote['atlas']
f=tempfile.NamedTemporaryFile('w',dir=os.path.dirname(path),delete=False)
json.dump(local,f,indent=2);f.write('\n');f.close();os.replace(f.name,path)
print(json.dumps(remote['atlas'],indent=2))
PY
    then synced=1; break; fi
    sleep 1
done
(( synced )) || fail 'job PID not observed; inspect remote tmux/log before retrying'
