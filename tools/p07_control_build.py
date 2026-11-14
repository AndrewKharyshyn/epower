#!/usr/bin/env python3
"""M651 (P-07): no-new-drive CONTROL BUILD of the arrays, exactly as ingest_core.step4_arrays calls the builder, written to an OUTPUT path (never to summary_arrays.json), followed by the leaf
comparison against the committed payload. Reports which previous leaves the builder does not produce (grouped by top-level key and by declared leaf_guard rule), i.e. the class that the
ingestion used to restore stage by stage. Read-only for the repository except content-keyed caches the builder already writes (raw_cache).
Usage: XT_RAW_DIR=raw_only python tools/p07_control_build.py --out "$TEMP/p07_control_arrays.json" --report analyses/M651_control_report.json"""
import argparse, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
os.chdir(ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--raw-stage", default=os.path.join(ROOT, "raw_only"))
    ap.add_argument("--from-arrays", help="skip the build and compare an existing control build output (the fresh payload before any carry)")
    a = ap.parse_args()
    import pandas as pd
    import compute_summary_arrays as csa
    import drive_raw_cache as drc
    import leaf_guard as LG
    import ingest_core as IC
    t0 = time.time()
    if a.from_arrays:
        prev = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
        arrays = json.load(open(a.from_arrays, encoding="utf-8"))
        return finish(a, arrays, prev, t0, LG, IC, built=False)
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    cfg = json.load(open(os.path.join(ROOT, "summary_config.json"), encoding="utf-8"))
    prev = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
    drc.add_missing(list(dm["file"].astype(str)), a.raw_stage, verbose=False)
    arrays = csa.build_summary_arrays(
        dm, lambda fn: open(os.path.join(a.raw_stage, fn), "rb").read(), with_raw=True, odometer_km=cfg.get("vehicle", {}).get("odometerKm"),
        seasonal_cfg=cfg.get("seasonalAssumptions"), ambient_by_drive=cfg.get("ambientByDrive"),
        frame_loader=drc.make_frame_loader(raw_dir=a.raw_stage), session_cfg=cfg, raw_dir=a.raw_stage,
        recompute_m119v2=False, prev_arrays=prev, recompute_energy_mc=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(arrays, f, ensure_ascii=False)
    return finish(a, arrays, prev, t0, LG, IC, built=True)


def finish(a, arrays, prev, t0, LG, IC, built):
    import copy
    rules = json.load(open(os.path.join(ROOT, "analyses", "leaf_guard_rules.json"), encoding="utf-8"))
    raw_rep = LG.guard(prev, arrays, rules)                                  # the builder output as it is
    IC.carry_forward(arrays, prev)                                           # what ingest_core did before M651 (top-level keys and the NESTED_CARRIED allow-list)
    before = LG.guard(prev, arrays, rules)
    carried = IC.carry_lost_leaves(arrays, prev, rules)                      # M651 generic carry (deny-list)
    rep = LG.guard(prev, arrays, rules)
    by_top = {}
    for u in rep["unexpected"]:
        by_top[u.split("/")[0]] = by_top.get(u.split("/")[0], 0) + 1
    topk_lost = sorted(k for k in prev if k not in arrays)
    out = {"built": built, "nLostBuilderOutputAsIs": raw_rep["nLost"], "nLostAfterOldCarry": before["nLost"], "nLostAfterGenericCarry": rep["nLost"], "carriedNodes": carried,
           "builtSeconds": (round(time.time() - t0, 1) if built else None), "nPreviousLeaves": rep["nPreviousLeaves"], "nLost": rep["nLost"], "expectedByRule": rep["expectedByRule"], "nUnexpected": rep["nUnexpected"],
           "unexpectedByTopLevelKey": dict(sorted(by_top.items())), "topLevelKeysAbsentFromFreshBuild": topk_lost, "unexpectedFirst200": rep["unexpected"][:200]}
    with open(a.report, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: out[k] for k in ("builtSeconds", "nPreviousLeaves", "nLost", "nUnexpected", "unexpectedByTopLevelKey")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
