#!/usr/bin/env python3
"""M545 G0 (analyses/M545_spec.md Rev 2 section 10 A0): the _RawAccum refactor to the pure kernels of tools/engine_on_blocks.py at ENGINE_ON_STORED_RPM (300) leaves the stored payload unchanged. Re-runs _RawAccum over the
canonical drive set (pipeline loader, master order) as the pool 'all' and the three season cohorts and compares the finalize output of the five engine-on blocks (engineOnDuration, engineOnBySpeed, turboByRpm, turboBySpeedCtx,
hvcTurboActivity) with summary_arrays.json and the cohort charts of seasonalCharts, byte for byte (canonical JSON). Read-only; writes analyses/M545_g0.json. Usage: python tools/engine_on_blocks_g0.py"""
import hashlib, json, os, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd

OUT = os.path.join(ROOT, "analyses", "M545_g0.json")
BLOCKS = ("engineOnDuration", "engineOnBySpeed", "turboByRpm", "turboBySpeedCtx", "hvcTurboActivity")
CHART = {"engineOnDuration": "EngineOnDuration", "engineOnBySpeed": "EngineOnBySpeed", "turboByRpm": "TurboByRpm"}


def canon(o):
    return json.dumps(json.loads(json.dumps(o, default=float)), sort_keys=True)


def main():
    os.chdir(ROOT)
    import drive_raw_cache as drc
    import compute_summary_arrays as C
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False, usecols=["file", "thermal_regime"]).set_index("file")["thermal_regime"]
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    fl = drc.make_frame_loader(raw_dir=os.path.abspath("raw_only"))
    dist, cond = dict(zip(dm["file"], dm["distance_km"])), dict(zip(dm["file"], dm["drive_type"]))
    cohorts = ["all", "warm", "shoulder", "cold"]
    pools = {c: C._RawAccum() for c in cohorts}
    assert all(p.eng_on_rpm == 300 for p in pools.values())
    t0, n = time.time(), 0
    for i, fn in enumerate(dm["file"]):
        try:
            df = fl(fn)
        except Exception:
            continue
        if df is None:
            continue
        n += 1
        lab = C._day_label(dm, i)
        for c in cohorts:
            if c == "all" or sdm.get(fn) == c:
                pools[c].add(df.copy(), dist.get(fn), cond.get(fn), lab, fn)
    fin = {c: pools[c].finalize() for c in cohorts}
    sc = A["seasonalCharts"]["charts"]
    g = {"primary": {k: canon(fin["all"][k]) == canon(A[k]) for k in BLOCKS},
         "cohortCharts": {c: {k: canon(fin[c][k]) == canon(sc[CHART[k]]["data"][c]) for k in CHART} for c in cohorts}}
    g["passed"] = bool(all(g["primary"].values()) and all(all(v.values()) for v in g["cohortCharts"].values()))
    res = {"spec": "analyses/M545_spec.md Rev 2 (A0 / G0)", "nDrivesUsed": n, "nDrivesMaster": int(len(dm)), "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(),
           "engineOnBlocksSha256": hashlib.sha256(open("tools/engine_on_blocks.py", "rb").read()).hexdigest(), "runSeconds": round(time.time() - t0, 1), "gates": g}
    json.dump(res, open(OUT, "w", encoding="utf-8", newline=chr(10)), indent=1)
    print(json.dumps(res)[:1500])
    return 0 if g["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
