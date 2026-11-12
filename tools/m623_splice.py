#!/usr/bin/env python3
"""M623 (spec analyses/M623_spec.md Rev 1) additive leaf-level splice of the two bin-edge fixes. It recomputes ONLY
  auxLoadAmbient               (compute_summary_arrays._aux_load_ambient: right-open bins with explicit open ends, nDays, generated interpretation)
  thermalWarmupLag             (compute_summary_arrays._thermal_warmup_lag: curve samples from 900 s on not binned, per-bin drives and days)
from drive_master.csv, summary_config.json ambientByDrive and the cached raw frames, and refuses (exit 3, nothing written) unless
  * every leaf the spec pins as unchanged is reproduced exactly (Spearman, slope, intercept, bootstrap, n, ranges; time-to-threshold blocks, lag70, steady-state offset, nColdStart, counts), which also
    proves that the inputs of this recomputation equal the builder's inputs;
  * the deep diff of the whole payload lies inside the allow-list (auxLoadAmbient.byAmbientBin / interpretation / methodology; thermalWarmupLag.warmupCurves / methodology).
The per-cohort copies seasonalCharts.charts.ThermalWarmupLag.data.* are refreshed by tools/regen_seasonal_raw.py --splice --only ThermalWarmupLag (ingestion stage refresh_raw_seasonal).
Usage: python tools/m623_splice.py [--dry-run] [--json PATH]"""
import copy, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

AUX_PINNED = ("exploratory", "causalityDisclosed", "nDrives", "nDays", "ambientRangeC", "standstillDrawRangeKw", "spearmanCorr", "spearmanCorrBoot", "slopeKwPerC", "interceptKw")
TWL_PINNED = ("nColdStart", "nDrivesTotal", "nWithOil", "nDays", "coldStartMaxC", "coolantTimeToThresholdS", "oilTimeToThresholdS", "coolantOilLag70S", "coolantOilLag70Boot", "steadyStateOffsetC")
CURVE_PINNED = ("timeBinsS", "binLabels")


def walk(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            yield from walk(a.get(k), b.get(k), f"{path}/{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            yield from walk(x, y, f"{path}[{i}]")
    elif a != b:
        yield path


def stop(msg):
    print("STOP:", msg)
    sys.exit(3)


def allowed(path):
    parts = path.strip("/").split("/")
    if parts[0] == "auxLoadAmbient":
        return len(parts) > 1 and parts[1].split("[")[0] in ("byAmbientBin", "interpretation", "methodology")
    if parts[0] == "thermalWarmupLag":
        return len(parts) > 1 and (parts[1] == "methodology" or (parts[1] == "warmupCurves" and len(parts) > 2 and parts[2].split("[")[0] in ("coolantMedianC", "oilMedianC", "coolantNDrives", "coolantNDays", "oilNDrives", "oilNDays")))
    return False


def main(argv):
    import pandas as pd
    import compute_summary_arrays as C
    import drive_raw_cache as drc
    p = "summary_arrays.json"
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    B = copy.deepcopy(A)
    cfg = json.load(open("summary_config.json", encoding="utf-8"))
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    new_aux = json.loads(json.dumps(C._aux_load_ambient(dm, ambient_by_drive=cfg.get("ambientByDrive"))))
    fl = drc.make_frame_loader(raw_dir=os.path.abspath("raw_only"))
    new_twl = json.loads(json.dumps(C._thermal_warmup_lag(dm, frame_loader=fl)))
    for k in AUX_PINNED:
        if A["auxLoadAmbient"].get(k) != new_aux.get(k):
            stop(f"auxLoadAmbient.{k} changed: {A['auxLoadAmbient'].get(k)} -> {new_aux.get(k)} (pinned; inputs may differ from the builder's)")
    for k in TWL_PINNED:
        if A["thermalWarmupLag"].get(k) != new_twl.get(k):
            stop(f"thermalWarmupLag.{k} changed (pinned): {A['thermalWarmupLag'].get(k)} -> {new_twl.get(k)}")
    for k in CURVE_PINNED:
        if A["thermalWarmupLag"]["warmupCurves"].get(k) != new_twl["warmupCurves"].get(k):
            stop(f"thermalWarmupLag.warmupCurves.{k} changed (pinned)")
    B["auxLoadAmbient"], B["thermalWarmupLag"] = new_aux, new_twl
    changed = list(walk(A, B))
    bad = [d for d in changed if not allowed(d)]
    if bad:
        stop(f"deep-diff outside the allow-list: {bad[:6]}")
    res = {"changedLeaves": len(changed), "paths": changed,
           "auxByAmbientBin": new_aux["byAmbientBin"], "auxInterpretation": new_aux["interpretation"],
           "warmupCurves": {k: new_twl["warmupCurves"][k] for k in ("binLabels", "coolantMedianC", "oilMedianC", "coolantNDrives", "coolantNDays", "oilNDrives", "oilNDays")},
           "oldWarmupCurves": {k: A["thermalWarmupLag"]["warmupCurves"][k] for k in ("coolantMedianC", "oilMedianC")}, "oldAuxByAmbientBin": A["auxLoadAmbient"]["byAmbientBin"]}
    print(json.dumps(res, indent=1)[:6000])
    if "--json" in argv:
        json.dump(res, open(argv[argv.index("--json") + 1], "w", encoding="utf-8", newline="\n"), indent=1)
    if "--dry-run" not in argv and changed:
        open(p, "w", encoding="utf-8", newline="").write(json.dumps(B, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
        print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
