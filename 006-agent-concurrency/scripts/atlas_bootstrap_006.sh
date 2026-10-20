#!/usr/bin/env bash
# Existing Ubuntu/Debian droplet only. Invoked through the existing SSH transport.
set -Eeuo pipefail
[[ $# == 1 && $1 =~ ^/[A-Za-z0-9_/-]+$ && $1 != / ]] || exit 2
ROOT_DIR=$1
[[ $(id -u) == 0 && $(uname -m) == x86_64 ]] || { echo 'Bootstrap requires root on Linux x86_64' >&2; exit 1; }
NODE_VERSION=24.21.0
NODE_DIR=/opt/atlas-node-$NODE_VERSION
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl xz-utils tmux git python3 rsync
if ! command -v docker >/dev/null; then
    # A plain Ubuntu CPU rehearsal host may not have the quick-start Docker daemon.
    [[ ${REHEARSAL:-0} == 1 ]] || { echo 'Docker is required' >&2; exit 1; }
    apt-get install -y --no-install-recommends docker.io docker-buildx
    systemctl enable --now docker
fi
getent group docker >/dev/null || groupadd --system docker
id atlas >/dev/null 2>&1 || useradd --create-home --shell /bin/bash atlas
[[ $(id -u atlas) != 0 && $(getent passwd atlas | cut -d: -f6) == /home/atlas ]] || exit 1
usermod -aG docker atlas
if [[ ${SESSION4:-0} == 1 && ${REHEARSAL:-0} != 1 ]]; then
    # Dedicated HF cache must be writable by the UID used for the download container.
    install -d -o atlas -g atlas "${SCRATCH_DIR:-/mnt/scratch}/hf"
fi
chown atlas:atlas /home/atlas
LOG_DIR="$ROOT_DIR/logs"
[[ ${REHEARSAL:-0} != 1 ]] || LOG_DIR="$ROOT_DIR/results/rehearsal/logs"
mkdir -p "$LOG_DIR"
if [[ ! -x $NODE_DIR/bin/node ]]; then
    temp=$(mktemp -d)
    trap 'rm -r -- "$temp"' EXIT
    archive=node-v$NODE_VERSION-linux-x64.tar.xz
    curl --fail --silent --show-error --location "https://nodejs.org/dist/v$NODE_VERSION/SHASUMS256.txt" -o "$temp/SHASUMS256.txt"
    curl --fail --silent --show-error --location "https://nodejs.org/dist/v$NODE_VERSION/$archive" -o "$temp/$archive"
    (cd "$temp"; awk -v f="$archive" '$2 == f {print}' SHASUMS256.txt > expected.sha256; test -s expected.sha256; sha256sum -c expected.sha256)
    mkdir "$NODE_DIR"
    tar -xJf "$temp/$archive" --strip-components=1 -C "$NODE_DIR"
    cp "$temp/expected.sha256" "$LOG_DIR/node_download.sha256"
fi
export PATH="$NODE_DIR/bin:$PATH"
[[ $(node --version) == v$NODE_VERSION ]] || exit 1
bash "$ROOT_DIR/scripts/atlas_ownership_006.sh" "$ROOT_DIR"
# runuser starts a fresh login/group context; it does not depend on a new SSH key.
runuser -u atlas -- env PATH="$PATH" docker info >/dev/null
runuser -u atlas -- env PATH="$PATH" docker buildx inspect >/dev/null
python3 - "$LOG_DIR/bootstrap_versions.json" "$NODE_DIR" <<'PY' || true
import datetime,json,pathlib,subprocess,sys
out,node_dir=sys.argv[1:]
errors={}
def cmd(*a):
 try:return subprocess.check_output(a,text=True,stderr=subprocess.STDOUT,timeout=30).strip()
 except Exception as error:
  errors[' '.join(a)]=f'{type(error).__name__}: {error}'
  return None
versions=dict(recorded_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    node=cmd('node','--version'),npm=cmd('npm','--version'),tmux=cmd('tmux','-V'),
    node_dir=node_dir,user='atlas',groups=cmd('id','atlas'),docker=cmd('docker','--version'),
    buildx=cmd('docker','buildx','version'),python=cmd('python3','--version'))
versions['provenance_errors']=errors
try:pathlib.Path(out).write_text(json.dumps(versions,indent=2)+'\n')
except Exception as error:print('Non-fatal bootstrap provenance write error: '+str(error),file=sys.stderr)
PY
if [[ -f $LOG_DIR/bootstrap_versions.json ]]; then chown atlas:atlas "$LOG_DIR/bootstrap_versions.json" || echo "Non-fatal bootstrap provenance ownership error" >&2; fi
