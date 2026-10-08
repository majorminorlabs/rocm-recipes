#!/usr/bin/env python3
"""Rebuild summary.csv from recorded results, using only explicit result keys."""
import csv
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
COLUMNS = (
    "run_id", "recipe", "model", "precision", "engine", "concurrency",
    "output_tok_per_s", "total_tok_per_s", "ttft_p50_ms", "ttft_p99_ms",
    "itl_p50_ms", "itl_p99_ms", "score", "score_flexible", "status",
)
R2_KEYS = {
    "output_tok_per_s": "output_throughput",
    "total_tok_per_s": "total_token_throughput",
    "ttft_p50_ms": "median_ttft_ms",
    "ttft_p99_ms": "p99_ttft_ms",
    "itl_p50_ms": "median_itl_ms",
    "itl_p99_ms": "p99_itl_ms",
}


def read_json(path):
    with path.open() as source:
        return json.load(source)


def available_keys(path, data):
    keys = sorted(data) if isinstance(data, dict) else "result is not an object"
    print(f"{path}: available keys: {keys}", file=sys.stderr)


def result_for(folder, recipe):
    if recipe == "R4":
        path = folder / "llama_bench.json"
        return (path, read_json(path)) if path.exists() else (None, None)
    matches = []
    for path in sorted(folder.rglob("*.json")):
        if path.name == "meta.json":
            continue
        data = read_json(path)
        # lm-eval may also write sample/config files; select its results object.
        if recipe != "R3" or (isinstance(data, dict) and "results" in data):
            matches.append((path, data))
    if len(matches) != 1:
        print(f"{folder}: expected one {recipe} result JSON, found {len(matches)}", file=sys.stderr)
        return None, None
    return matches[0]


def row_for(meta_path):
    meta = read_json(meta_path)
    row = {column: meta.get(column, "") for column in COLUMNS}
    recipe = meta.get("recipe")
    if recipe not in ("R2", "R3", "R4"):
        return row
    path, data = result_for(meta_path.parent, recipe)
    if data is None:
        return row
    if recipe == "R2":
        if not isinstance(data, dict):
            available_keys(path, data)
            return row
        missing = False
        for column, key in R2_KEYS.items():
            if key in data:
                row[column] = data[key]
            else:
                missing = True
        if missing:
            available_keys(path, data)
    elif recipe == "R3":
        scores = data.get("results", {}).get("gsm8k", {})
        missing = False
        for column, key in (("score", "exact_match,strict-match"),
                            ("score_flexible", "exact_match,flexible-extract")):
            if key in scores:
                row[column] = scores[key]
            else:
                missing = True
        if missing:
            available_keys(path, scores)
    else:
        if not isinstance(data, list):
            available_keys(path, data)
            return row
        # Match the separate llama-bench generation and prompt tests explicitly.
        for column, prompt, generation in (
            ("output_tok_per_s", 0, 128),
            ("total_tok_per_s", 512, 0),
        ):
            tests = [test for test in data if isinstance(test, dict)
                     and test.get("n_prompt") == prompt and test.get("n_gen") == generation]
            if len(tests) == 1 and "avg_ts" in tests[0]:
                row[column] = tests[0]["avg_ts"]
            else:
                print(f"{path}: missing or ambiguous pp{prompt}/tg{generation} avg_ts", file=sys.stderr)
                for test in data:
                    available_keys(path, test)
    return row


def main():
    if len(sys.argv) != 1:
        sys.exit(f"Usage: {sys.argv[0]}")
    rows = [row_for(path) for path in sorted((ROOT / "results/raw").glob("*/*/meta.json"))]
    (ROOT / "logs").mkdir(exist_ok=True)
    with (ROOT / "logs/summarize.log").open("a") as log:
        log.write(f"Rebuilding summary.csv: {len(rows)} runs\n")
    (ROOT / "results").mkdir(exist_ok=True)
    with (ROOT / "results/summary.csv").open("w", newline="") as output:
        output.write("# R4: output_tok_per_s = generation tokens/sec (tg128); "
                     "total_tok_per_s = prompt tokens/sec (pp512).\n")
        writer = csv.DictWriter(output, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
