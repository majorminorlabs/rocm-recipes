#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs
LOG_FILE="logs/quality_eval_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
if [[ $# -ne 2 ]]; then echo "Usage: $0 <model> <run_id>" >&2; exit 2; fi
MODEL="$1"; RUN_ID="$2"
[[ "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "invalid run_id" >&2; exit 2; }
if [[ -f config.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source config.env
  set +a
fi
SCRATCH_DIR="${SCRATCH_DIR:-/mnt/scratch}"
RESULT_DIR="results/raw/R3/$RUN_ID"
MAX_GEN_TOKS=2048
if [[ "$MODEL" == "openai/gpt-oss-120b" ]]; then MAX_GEN_TOKS=8192; fi
mkdir -p "$RESULT_DIR"
mkdir -p "$SCRATCH_DIR/pip-cache"
eval_container() {
  local command_args=("$@") quoted_command patch_code quoted_patch
  printf -v quoted_command '%q ' "${command_args[@]}"
  patch_code="$(cat <<'PY'
import ast
import importlib.util
from pathlib import Path

path = Path(importlib.util.find_spec("lm_eval").origin).parent / "filters/extraction.py"
source = path.read_text()
tree = ast.parse(source)
regex_class = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "RegexFilter")
filter_set = next(node for node in ast.walk(regex_class)
                  if isinstance(node, ast.FunctionDef) and node.name == "filter_set")
loop = next(node for node in ast.walk(filter_set)
            if isinstance(node, ast.For) and isinstance(node.target, ast.Name)
            and node.target.id == "resp")
statement = loop.body[0]
lines = source.splitlines(keepends=True)
if ast.unparse(statement) != "resp = resp or ''":
    if ast.unparse(statement) != "match = self.regex.findall(resp)":
        raise RuntimeError("Unexpected RegexFilter response loop; refusing to patch")
    lines.insert(statement.lineno - 1, " " * statement.col_offset + 'resp = resp or ""\n')
    patched = "".join(lines)
    compile(patched, str(path), "exec")
    path.write_text(patched)
PY
)"
  printf -v quoted_patch '%q' "$patch_code"
  docker run --rm --network host \
    -v "$ROOT_DIR/results:/workspace/results" \
    -v "$SCRATCH_DIR/hf:/root/.cache/huggingface" \
    -v "$SCRATCH_DIR/pip-cache:/root/.cache/pip" \
    python:3.12-slim bash -c \
    "pip install -q \"lm-eval[api]==0.4.9\" \"transformers>=4.45,<5\" && python -c $quoted_patch && $quoted_command"
}
help_flag() {
  local flag="$1" candidate
  for candidate in "$flag" "${flag//_/-}"; do
    if grep -Eq "(^|[[:space:],])${candidate}([=[:space:],]|$)" "$LOG_FILE.help"; then
      printf '%s\n' "$candidate"; return 0
    fi
  done
  echo "Required flag $flag not found in captured lm_eval --help ($LOG_FILE.help)" >&2
  return 2
}
run_eval() {
  eval_container lm_eval --help >"$LOG_FILE.help" 2>&1 || { cat "$LOG_FILE.help"; return 1; }
  local model_flag args_flag tasks_flag limit_flag output_flag template_flag gen_flag samples_flag
  model_flag="$(help_flag --model)" || return $?
  args_flag="$(help_flag --model_args)" || return $?
  tasks_flag="$(help_flag --tasks)" || return $?
  limit_flag="$(help_flag --limit)" || return $?
  output_flag="$(help_flag --output_path)" || return $?
  template_flag="$(help_flag --apply_chat_template)" || return $?
  gen_flag="$(help_flag --gen_kwargs)" || return $?
  local eval_args=(lm_eval "$model_flag" local-chat-completions \
    "$args_flag" "model=$MODEL,base_url=http://localhost:8000/v1/chat/completions,tokenized_requests=False,num_concurrent=32,max_retries=3" \
    "$tasks_flag" gsm8k "$limit_flag" 250 "$output_flag" "/workspace/$RESULT_DIR" \
    "$template_flag" "$gen_flag" "max_gen_toks=$MAX_GEN_TOKS")
  if samples_flag="$(help_flag --log_samples 2>/dev/null)"; then eval_args+=("$samples_flag"); fi
  eval_container "${eval_args[@]}"
}
STARTED_AT="$(date -Iseconds)"
set +e
run_eval 2>&1 | tee "$LOG_FILE.output"
EXIT_CODE=${PIPESTATUS[0]}
set -e
FINISHED_AT="$(date -Iseconds)"
LM_EVAL_VERSION="$(eval_container pip show lm-eval 2>/dev/null | awk '$1 == "Version:" {print $2}' || true)"
ENGINE_VERSION="$(docker exec vllm-server python -c 'import vllm; print(vllm.__version__)' 2>/dev/null || true)"
IMAGE_DIGEST="$(docker inspect --format '{{index .RepoDigests 0}}' "${VLLM_IMAGE:-}" 2>/dev/null || true)"
ROCM_JSON="$("$ROOT_DIR/scripts/rocm_version.sh")"
MODEL_REVISION="$(cat "$SCRATCH_DIR/hf/hub/models--${MODEL//\//--}/refs/main" 2>/dev/null || true)"
case "$MODEL" in
  Qwen/Qwen3-Coder-30B-A3B-Instruct) PRECISION=bf16 ;;
  Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8) PRECISION=fp8 ;;
  openai/gpt-oss-120b) PRECISION=mxfp4 ;;
  *) PRECISION="" ;;
esac
ERROR=""
if (( EXIT_CODE != 0 )); then ERROR="$(tail -20 "$LOG_FILE.output")"; fi
export RUN_ID MODEL PRECISION STARTED_AT FINISHED_AT ENGINE_VERSION IMAGE_DIGEST ROCM_JSON MODEL_REVISION LM_EVAL_VERSION MAX_GEN_TOKS ERROR EXIT_CODE
python3 - "$RESULT_DIR/meta.json" <<'PY'
import json, os, sys
from pathlib import Path
e = os.environ
meta = {key.lower(): e[key] for key in (
    "RUN_ID", "MODEL", "MODEL_REVISION", "PRECISION", "ENGINE_VERSION",
    "IMAGE_DIGEST", "STARTED_AT", "FINISHED_AT", "ERROR", "LM_EVAL_VERSION")}
rocm = json.loads(e["ROCM_JSON"])
meta.update(rocm=rocm, rocm_version=rocm["host_rocm"] or rocm["container_hip"])
meta.update(recipe="R3", engine="vllm", concurrency=32, input_len=None,
            output_len=int(e["MAX_GEN_TOKS"]), num_prompts=250,
            status="ok" if e["EXIT_CODE"] == "0" else "failed")
metadata_exit = 0
if meta["status"] == "ok":
    try:
        samples = list(Path(sys.argv[1]).parent.rglob("samples_gsm8k_*.jsonl"))
        if not samples:
            raise ValueError("gsm8k sample output not found; cannot count empty responses")
        # A retry can leave older timestamped sample files in the same run folder.
        latest = max(samples, key=lambda path: path.name)
        seen = set()
        empty_responses = 0
        with latest.open() as source:
            for line in source:
                sample = json.loads(line)
                for request_index, responses in enumerate(sample["resps"]):
                    for response_index, response in enumerate(responses):
                        # Each raw response is logged once per extraction filter.
                        key = (sample["doc_id"], request_index, response_index)
                        if key in seen:
                            continue
                        seen.add(key)
                        # lm-eval 0.4.9 sanitize_list serializes None as "None".
                        if response is None or response in ("", "None"):
                            empty_responses += 1
        meta["empty_responses"] = empty_responses
    except (OSError, ValueError, KeyError, TypeError) as error:
        meta.update(status="failed", error=f"empty response counting failed: {error}")
        metadata_exit = 1
with open(sys.argv[1], "w") as f:
    json.dump(meta, f, indent=2)
    f.write("\n")
sys.exit(metadata_exit)
PY
exit "$EXIT_CODE"
