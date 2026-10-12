# Recorded environment versions

Only recorded values are listed here. Existing run metadata has not been amended.

| Item | Recorded value | Source |
|---|---|---|
| AMD Dev Cloud image label | ROCm 10.1 quick-start, Ubuntu 24.04; droplet name `rocm-10-1-gpu-mi300x1-192gb-devcloud-atl1` | AMD Dev Cloud console label; droplet name corroborated by [session1_start/uname.txt](session1_start/uname.txt) |
| Kernel and uname | `Linux rocm-10-1-gpu-mi300x1-192gb-devcloud-atl1 6.8.0-146-generic #146-Ubuntu SMP PREEMPT_DYNAMIC Thu Sep  3 16:12:30 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux` | [session1_start/uname.txt](session1_start/uname.txt) |
| AMDGPU/ROCk driver | `6.19.14.31400000` | `ROCk module version` line in [session1_start/rocminfo.txt](session1_start/rocminfo.txt) |
| HSA runtime | `1.21` | `Runtime Version` line in [session1_start/rocminfo.txt](session1_start/rocminfo.txt) |
| vLLM | `0.29.1.dev0+g98dff2a81.d20261002` | `engine_version` in [R3-M1/meta.json](../raw/R3/R3-M1/meta.json) |
| vLLM container, exact image pin | `rocm/vllm@sha256:e0ea9a10b729573ea8598bdc073bda0ea382fe1037eec7c0761b6fa7f46baaf4` | `image_digest` in [R3-M1/meta.json](../raw/R3/R3-M1/meta.json); this full digest can be pulled to inspect the container versions |
| llama.cpp, Session 2 | `bd4eeaa047006cb1fe71999fbd11134b5836e167` | `results/raw/R4/llama_cpp_commit.txt` at committed Session 2 snapshot `dd26271`: `git show dd26271:results/raw/R4/llama_cpp_commit.txt` (the current [commit file](../raw/R4/llama_cpp_commit.txt) was replaced by Session 3's build) |
| llama.cpp, Session 3 | `06cad0b9e77315bd2930bd4f70a6d7b37b2a01c1` | [llama_cpp_commit.txt](../raw/R4/llama_cpp_commit.txt), also `engine_version` in [R4-M5-q4km/meta.json](../raw/R4/R4-M5-q4km/meta.json) |

Container HIP/ROCm version: not recorded; to be read from the pinned image on the next droplet.

Source for that absence: blank `rocm_version` in [R3-M1/meta.json](../raw/R3/R3-M1/meta.json) and [session1_start/rocm-version.txt](session1_start/rocm-version.txt). The console image label, driver version, and HSA runtime above are retained as separate facts and are not substituted for an unrecorded runtime version.
