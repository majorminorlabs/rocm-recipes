#!/usr/bin/env bash
# Best-effort version capture: stdout is always one JSON object, even without tools.
if ! python3 - 2>/dev/null <<'PY'
import json
import re
import subprocess


def read(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                errors="replace", timeout=10)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def clean(value):
    return re.sub(r"\x1b\[[0-9;]*m", "", value)


versions = dict(host_rocm="", host_driver="", container_hip="", container_torch="")
versions["host_rocm"] = read(["dpkg-query", "-W", "-f=${Version}", "rocm-core"])
if not versions["host_rocm"]:
    output = clean(read(["amd-smi", "version"]))
    # Accept the ROCm field in either text or JSON output, without using SMI's version.
    match = re.search(r'\bROCm(?:[ _-]+version)?["\s]*[:=]\s*"?([^\s",}]+)',
                      output, re.IGNORECASE)
    if match and match.group(1) not in ("None", "null", "N/A"):
        versions["host_rocm"] = match.group(1)
if not versions["host_rocm"]:
    for path in read(["sh", "-c", "ls -d /opt/rocm-*"]).splitlines():
        match = re.fullmatch(r"/opt/rocm-(\d[^/\s]*)", path.strip())
        if match:
            versions["host_rocm"] = match.group(1)
            break
versions["host_driver"] = read(["cat", "/sys/module/amdgpu/version"])
if not versions["host_driver"]:
    output = clean(read(["rocminfo"]))
    match = re.search(r"ROCk module version\s+(\S+)", output)
    if match:
        versions["host_driver"] = match.group(1)
if read(["docker", "inspect", "-f", "{{.State.Running}}", "vllm-server"]) == "true":
    for key, expression in (("container_hip", "torch.version.hip"),
                            ("container_torch", "torch.__version__")):
        value = read(["docker", "exec", "vllm-server", "python", "-c",
                      f"import torch; print({expression})"])
        versions[key] = "" if value in ("None", "null") else value
print(json.dumps(versions))
PY
then
  printf '%s\n' '{"host_rocm":"","host_driver":"","container_hip":"","container_torch":""}'
fi
