#!/usr/bin/env bash
# REH-001 environment preparation. Never used by production atlas_remote.sh.
set -Eeuo pipefail
ENGINE_VERSION=29.8.2
ENGINE_APT='5:29.8.2-1~ubuntu.24.04~noble'
BUILDX_APT='0.37.1-1~ubuntu.24.04~noble'
BUILDX_VERSION='github.com/docker/buildx v0.37.1 0b265a9f62db554fa9aba6dd19e1bd5704bc7d8a'
fail() { echo "rehearsal_prep: $*" >&2; exit 1; }

verify_versions() {
    local root=$1
    python3 - "$root" "$ENGINE_APT" "$BUILDX_APT" "$BUILDX_VERSION" <<'PY'
import datetime,json,os,pathlib,subprocess,sys,tempfile
root,engine_apt,buildx_apt,buildx_expected=sys.argv[1:]
def cmd(*args):return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT,timeout=60).strip()
record=dict(recorded_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),rehearsal=True,verified=False,
    baseline='results/droplet_logs/session2_attempt3/bootstrap_versions.json',
    baseline_engine_note='GPU record captures Docker CLI 29.8.2; daemon version was not independently captured. Rehearsal explicitly pins/verifies both client and daemon 29.8.2.',
    fs_read_grant=root+'/results/rehearsal/atlas/data',provenance_errors={})
path=pathlib.Path(root)/'results/rehearsal/logs/rehearsal_prep_versions.json'
path.parent.mkdir(parents=True,exist_ok=True)
try:
    record['docker']=json.loads(cmd('/usr/bin/docker','version','--format','{{json .}}'))
    record['buildx']=cmd('docker','buildx','version')
    record['docker_launcher']=cmd('sh','-c','command -v docker')
    record['packages']={p:cmd('dpkg-query','-W','-f=${Version}',p) for p in ('docker-ce','docker-ce-cli','docker-buildx-plugin')}
    for p,expected in [('docker-ce',engine_apt),('docker-ce-cli',engine_apt),('docker-buildx-plugin',buildx_apt)]:
        if record['packages'][p]!=expected:raise ValueError(p+' package mismatch: '+record['packages'][p])
    for side in ('Client','Server'):
        actual=record['docker'][side]
        if actual['Version']!='29.8.2' or actual['Os']!='linux' or actual['Arch']!='amd64':raise ValueError(side+' Docker version/platform mismatch: '+json.dumps(actual))
    if record['docker']['Client']['GitCommit']!='7fc2dff':raise ValueError('Docker CLI build differs from GPU baseline')
    if record['buildx']!=buildx_expected:raise ValueError('Selected root buildx differs from GPU baseline: '+record['buildx'])
    if record['docker_launcher']!='/usr/local/bin/docker':raise ValueError('Rehearsal Docker launcher is shadowed')
    if subprocess.run(['id','atlas'],capture_output=True).returncode==0:
        record['atlas_buildx']=cmd('runuser','-u','atlas','--','env','HOME=/home/atlas','PATH='+os.environ['PATH'],'docker','buildx','version')
        if record['atlas_buildx']!=buildx_expected:raise ValueError('atlas user buildx differs from GPU baseline')
    record['verified']=True
except Exception as error:
    record['provenance_errors']['verification']=str(error)
finally:
    with tempfile.NamedTemporaryFile('w',dir=path.parent,delete=False) as f:
        json.dump(record,f,indent=2);f.write('\n');temp=f.name
    os.replace(temp,path)
if not record['verified']:raise SystemExit('Pinned Docker verification failed: '+record['provenance_errors']['verification'])
print('Verified Docker client/daemon 29.8.2 and '+buildx_expected)
PY
}

install_versions() {
    apt-get update
    apt-get install -y --no-remove --allow-downgrades --allow-change-held-packages --no-install-recommends \
        "docker-ce=$ENGINE_APT" "docker-ce-cli=$ENGINE_APT" "docker-buildx-plugin=$BUILDX_APT"
    apt-mark hold docker-ce docker-ce-cli docker-buildx-plugin
    systemctl enable --now docker
    # A downgrade must actually restart the daemon before server-version verification.
    systemctl restart docker
}

configure_repository() {
    # Reuse an existing Docker-repo definition: duplicate URIs with different
    # Signed-By key paths make apt fail, even when the key bytes are identical.
    if python3 - <<'PY'
from pathlib import Path
files=[Path('/etc/apt/sources.list'),*Path('/etc/apt/sources.list.d').glob('*.list'),*Path('/etc/apt/sources.list.d').glob('*.sources')]
present=any('https://download.docker.com/linux/ubuntu' in line for p in files if p.is_file() for line in p.read_text().splitlines() if not line.lstrip().startswith('#'))
raise SystemExit(0 if present else 1)
PY
    then
        echo 'Reusing configured Docker apt repository (exact versions still required)'
        return
    fi
    install -d -m 0755 /etc/apt/keyrings
    curl --fail --silent --show-error --location https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/rocm006-rehearsal-docker.asc
    chmod 0644 /etc/apt/keyrings/rocm006-rehearsal-docker.asc
    cat > /etc/apt/sources.list.d/rocm006-rehearsal-docker.sources <<'REPO'
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/rocm006-rehearsal-docker.asc
REPO
}

[[ ${REHEARSAL:-0} == 1 ]] || fail 'REHEARSAL=1 is required'
if [[ ${1:-} == --remote ]]; then
    [[ $# == 2 && $2 =~ ^/home/atlas/[A-Za-z0-9_-]+-rehearsal$ && ! -L $2 ]] || fail 'unsafe rehearsal root'
    root=$2
    [[ $(realpath -m "$root") == "$root" ]] || fail 'rehearsal root parents must not be symlinks'
    [[ $(id -u) == 0 && $(uname -s) == Linux && $(uname -m) == x86_64 ]] || fail 'requires root on Linux x86_64'
    [[ ! -e /dev/kfd && ! -e /dev/nvidia0 ]] || fail 'refuse to replace Docker on a GPU host'
    # shellcheck disable=SC1091
    source /etc/os-release
    [[ $ID == ubuntu && $VERSION_ID == 24.04 && $(dpkg --print-architecture) == amd64 ]] || fail 'requires Ubuntu 24.04 amd64'
    # Refuse to replace another launcher's file or restart somebody's running work.
    if [[ -e /usr/local/bin/docker || -L /usr/local/bin/docker ]]; then
        if [[ -L /usr/local/bin/docker ]] || ! grep -q '^# rocm006-rehearsal-docker-v1:' /usr/local/bin/docker; then
            fail '/usr/local/bin/docker belongs to another installation'
        fi
    fi
    export DOCKER_HOST=unix:///var/run/docker.sock
    unset DOCKER_CONTEXT
    if [[ -x /usr/bin/docker ]]; then
        running=$(/usr/bin/docker ps -q) || fail 'cannot inspect existing Docker daemon'
        [[ -z $running ]] || fail 'running containers exist; use an idle dedicated CPU host'
    fi
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends ca-certificates curl python3
    configure_repository
    install_versions
    temp=$(mktemp)
    trap 'rm -f -- "$temp"' EXIT
    sed "s|@REHEARSAL_STUDY_ROOT@|$root|g" "$root/scripts/rehearsal_docker.sh" > "$temp"
    install -m 0755 "$temp" /usr/local/bin/docker
    verify_versions "$root"
    # Existing hosts already have atlas; new hosts are chowned by normal bootstrap.
    if id atlas >/dev/null 2>&1; then
        bash "$root/scripts/atlas_ownership_006.sh" "$root"
    fi
    exit 0
fi
[[ $# == 0 || ( $# == 1 && $1 == --dry-run ) ]] || fail 'usage: rehearsal_prep.sh [--dry-run]'
root=${ATLAS_REMOTE_ROOT:-}; target=${ATLAS_SSH_TARGET:-}
[[ $root =~ ^/home/atlas/[A-Za-z0-9_-]+-rehearsal$ && $target =~ ^root@[A-Za-z0-9.-]+$ ]] || fail 'set explicit root SSH target and dedicated rehearsal root'
if [[ ${1:-} == --dry-run ]]; then
    echo "Rehearsal prep FIRST on $target: Docker Engine/CLI $ENGINE_VERSION ($ENGINE_APT); buildx $BUILDX_APT; Docker signed apt repo; apt holds; verify client, daemon and plugin versions/builds."
    echo "Scoped rehearsal launcher: buildx bake from $root/atlas adds only --allow=fs.read=$root/results/rehearsal/atlas/data; other calls pass through."
    echo 'Record local/remote results/rehearsal/logs/rehearsal_prep_versions.json; no SSH/SCP/apt/Docker action.'
    exit 0
fi
local_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ssh_args=(-o BatchMode=yes -o ConnectTimeout=10)
# shellcheck disable=SC2029 # Validated dedicated path; no host is created here.
ssh "${ssh_args[@]}" "$target" "test ! -e '$root/atlas' && mkdir -p '$root/scripts' '$root/results/rehearsal/logs'"
scp "${ssh_args[@]}" "$local_root/scripts/rehearsal_prep.sh" "$local_root/scripts/rehearsal_docker.sh" "$local_root/scripts/atlas_ownership_006.sh" "$target:$root/scripts/"
printf -v remote_cmd '%q ' env REHEARSAL=1 bash "$root/scripts/rehearsal_prep.sh" --remote "$root"
rc=0
# shellcheck disable=SC2029 # printf-%q escaped arguments.
ssh "${ssh_args[@]}" "$target" "$remote_cmd" || rc=$?
mkdir -p "$local_root/results/rehearsal/logs"
# Preserve a failed-verification record too; never continue setup after any failure.
scp "${ssh_args[@]}" "$target:$root/results/rehearsal/logs/rehearsal_prep_versions.json" "$local_root/results/rehearsal/logs/" || rc=1
exit "$rc"
