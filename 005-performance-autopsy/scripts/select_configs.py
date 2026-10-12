#!/usr/bin/env python3
"""Deterministically select the two 004 configs for study 005."""
import csv
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "inputs/from-004/results/summary.csv"
OUTPUT = ROOT / "notes/config_selection.md"


def num(row, key):
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return None


def main():
    with SUMMARY.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cfgs = sorted({r.get("cfg", "") for r in rows if r.get("cfg")})
    table = []
    eligible = []
    for cfg in cfgs:
        m1 = [r for r in rows if r.get("cfg") == cfg and "-M1-" in r.get("run_id", "")]
        l12 = [r for r in m1 if r.get("recipe") in {"L1", "L2"}]
        good = bool(l12) and all(r.get("status") == "ok" for r in l12)
        has_short16 = any(r.get("recipe") == "L2" and r.get("input_len") == "1024" and r.get("concurrency") == "16" and r.get("status") == "ok" for r in l12)
        has_long16 = any(r.get("recipe") == "L2" and r.get("input_len") == "32768" and r.get("concurrency") == "16" and r.get("status") == "ok" for r in l12)
        needle = [r for r in m1 if r.get("recipe") == "L3H" and r.get("status") == "ok"]
        needle_score = max((num(r, "needle_correct") / num(r, "needle_total") * 9 for r in needle if num(r, "needle_correct") is not None and num(r, "needle_total") not in (None, 0)), default=None)
        l1 = [r for r in m1 if r.get("recipe") == "L1" and r.get("input_len") == "32768" and r.get("concurrency") == "1" and r.get("status") == "ok" and r.get("run_id", "").endswith("-in32768")]
        s16 = [r for r in m1 if r.get("recipe") == "L2" and r.get("input_len") == "1024" and r.get("concurrency") == "16" and r.get("status") == "ok"]
        l16 = [r for r in m1 if r.get("recipe") == "L2" and r.get("input_len") == "32768" and r.get("concurrency") == "16" and r.get("status") == "ok"]
        a = num(l1[0], "decode_tok_per_s") if len(l1) == 1 else None
        b = num(s16[0], "output_tok_per_s") if len(s16) == 1 else None
        c = num(l16[0], "output_tok_per_s") if len(l16) == 1 else None
        score = math.prod([a, b, c]) ** (1 / 3) if all(x is not None and x > 0 for x in (a, b, c)) else None
        ok = good and has_short16 and has_long16 and needle_score is not None and needle_score >= 7 and score is not None
        engine = next((r.get("engine", "") for r in m1 if r.get("engine")), "")
        nondefault = {"VD": 0, "VT": 1, "SD": 0, "SX": 1}.get(cfg, 0)
        entry = {"cfg": cfg, "engine": engine, "score": score, "eligible": ok, "needle": needle_score, "a": a, "b": b, "c": c, "nondefault": nondefault}
        table.append(entry)
        if ok:
            eligible.append(entry)
    # Best eligible config per engine; if scores are within 3%, fewer non-default settings wins.
    by_engine = {}
    for engine in sorted({e["engine"] for e in eligible}):
        same = sorted((e for e in eligible if e["engine"] == engine), key=lambda e: e["score"], reverse=True)
        if len(same) > 1 and same[0]["score"] <= same[1]["score"] * 1.03 and same[0]["nondefault"] != same[1]["nondefault"]:
            same.sort(key=lambda e: (e["nondefault"], -e["score"]))
        by_engine[engine] = same[0]
    picks = sorted(by_engine.values(), key=lambda e: e["score"], reverse=True)[:2]
    if len(picks) != 2:
        raise SystemExit(f"Expected eligible configs from two engines; found {len(picks)}")
    text = ["# Config selection from 004", "", "Eligibility: L2 short and long at c16, all M1 L1/L2 rows status `ok`, needle at least 7/9.", "Score: geometric mean of L1 32K decode tok/s, L2 short c16 output tok/s, and L2 long c16 output tok/s.", "", "| Config | Engine | L1 32K decode tok/s | L2 short c16 output tok/s | L2 long c16 output tok/s | Needle /9 | Score | Eligible |", "|---|---|---:|---:|---:|---:|---:|---|"]
    for e in table:
        f = lambda v: "—" if v is None else f"{v:.2f}"
        text.append(f"| {e['cfg']} | {e['engine']} | {f(e['a'])} | {f(e['b'])} | {f(e['c'])} | {f(e['needle'])} | {f(e['score'])} | {'yes' if e['eligible'] else 'no'} |".replace("| |---", "|---"))
    text += ["", f"**CFG_A = {picks[0]['cfg']}** ({picks[0]['engine']}, score {picks[0]['score']:.2f}).", f"**CFG_B = {picks[1]['cfg']}** ({picks[1]['engine']}, score {picks[1]['score']:.2f}).", ""]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(text), encoding="utf-8")
    print(f"CFG_A={picks[0]['cfg']} CFG_B={picks[1]['cfg']}")


if __name__ == "__main__":
    main()
