#!/usr/bin/env python3
"""M362 (spec analyses/M362_spec.md): distribution summary of the per-drive engine-start rate (RPM onsets per 100 km) per drive class, spliced additively into
engineStartsByType and seasonalCharts.charts.EngineStartsByType.data.{all,warm,shoulder}.
Detector = tools/engine_start_rate (RPM > 300, 1 Hz grid, runs >= MIN_ENGINE_START_S). KNOWN ANSWER (a mismatch STOPS): per class and cohort the per-drive rates reproduce the stored
lo / hi / avg (rounded as the pipeline rounds them) and the recomputed pooled rate agrees with engineStartRate.byClass[*].est (all) within 0.05 (report only: M343 is on the canonical-clean drive set, this chart on all classed drives with distance > 0, so n differs, see check JSON). New fields only: n, nDays, p10, p25, median, p75, p90 (numpy linear / type 7),
nShort (distance < SHORT_KM = descriptive display threshold, never an exclusion), shortKm, maxDrive, maxKm. NO pooled field is written: the chart's pooled diamond binds to engineStartRate.byClass (M343) only. lo/hi/avg and every other key are byte-identical (deep-diff allow-list). Reads the pipeline frame cache; never writes the master.
Modes: --check (writes analyses/M362_check.json, no payload write) | --splice. Usage: python tools/m362_splice.py --check|--splice"""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import compute_summary_arrays as C
import drive_raw_cache as drc
import engine_start_rate as E

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M362_check.json")
SHORT_KM = 2.0
canon = lambda o: json.dumps(o, sort_keys=True, ensure_ascii=False, default=float)


def per_drive(dm):
    fl = drc.make_frame_loader()
    rows = []
    for _, r in dm.iterrows():
        cls = C._cond_class(r.get("drive_type"))
        km = r.get("distance_km")
        if cls is None or not (km and km > 0):
            continue
        fr = fl(r["file"])
        if fr is None:
            continue
        hz = E.build_hz(fr)
        if hz is None or "eng_rpm" not in hz or not hz["eng_rpm"].values.size:
            continue
        s, _, _ = E.onsets(hz)
        rows.append({"file": r["file"], "date": str(r["date"])[:10], "cls": cls, "km": float(km), "n": int(len(s)), "rate": len(s) / float(km) * 100.0})
    return pd.DataFrame(rows)


def summarise(g):
    v = g["rate"].values
    mx = g.loc[g["rate"].idxmax()]
    return {"n": int(len(g)), "nDays": int(g["date"].nunique()),
            "p10": round(float(np.percentile(v, 10)), 1), "p25": round(float(np.percentile(v, 25)), 1), "median": round(float(np.median(v)), 1),
            "p75": round(float(np.percentile(v, 75)), 1), "p90": round(float(np.percentile(v, 90)), 1),
            "nShort": int((g["km"] < SHORT_KM).sum()), "shortKm": SHORT_KM,
            "maxDrive": str(mx["file"]), "maxKm": round(float(mx["km"]), 2)}


def main():
    mode = "--splice" if "--splice" in sys.argv else "--check"
    A = json.load(open(ARR, encoding="utf-8"))
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    reg = pd.read_csv("seasonal_drive_master.csv", low_memory=False)[["file", "thermal_regime"]]
    pdv = per_drive(dm).merge(reg, on="file", how="left")
    subsets = {"all": pdv, "warm": pdv[pdv.thermal_regime == "warm"], "shoulder": pdv[pdv.thermal_regime == "shoulder"]}
    stored = {"all": A["engineStartsByType"], **{m: A["seasonalCharts"]["charts"]["EngineStartsByType"]["data"][m] for m in ("warm", "shoulder")}}
    res = {"milestone": "M362", "mode": mode, "nDrives": int(len(pdv)), "control": {"knownAnswerMismatches": [], "pooledVsM343": {}}, "summary": {}}
    new = {}
    for m, sub in subsets.items():
        new[m] = {}
        for ent in stored[m]:
            ck = ent.get("classKey") or ent["label"].lower().replace(" ", "_")
            g = sub[sub.cls == ck]
            if not len(g):
                res["control"]["knownAnswerMismatches"].append(f"{m}/{ck}: stored entry without drives")
                continue
            if (round(float(g.rate.min())), round(float(g.rate.max())), round(float(g.rate.mean()))) != (ent["lo"], ent["hi"], ent["avg"]):
                res["control"]["knownAnswerMismatches"].append(f"{m}/{ck}: recomputed {(round(float(g.rate.min())), round(float(g.rate.max())), round(float(g.rate.mean())))} vs stored {(ent['lo'], ent['hi'], ent['avg'])}")
            new[m][ck] = summarise(g)
    sens = {}
    for ck in new["all"]:
        g = pdv[pdv.cls == ck]; gl = g[g.km >= SHORT_KM]
        est = (A.get("engineStartRate", {}).get("byClass", {}).get(ck) or {}).get("est")
        pooled = float(g["n"].sum() / g["km"].sum() * 100.0)
        res["control"]["pooledVsM343"][ck] = {"pooledRecomputed": round(pooled, 3), "M343": est, "nHere": int(len(g)), "nM343": (A.get("engineStartRate", {}).get("byClass", {}).get(ck) or {}).get("nTrips"), "ok": est is not None and abs(pooled - est) <= 0.05}
        sens[ck] = {"nShort": int((g.km < SHORT_KM).sum()), "shortShare": round(float((g.km < SHORT_KM).mean()), 3), "median": round(float(g.rate.median()), 1), "pooled": round(pooled, 2),
                    "medianExcludingShort": round(float(gl.rate.median()), 1) if len(gl) else None, "pooledExcludingShort": round(float(gl.n.sum() / gl.km.sum() * 100.0), 2) if len(gl) else None, "nExcludingShort": int(len(gl))}
    res["sensitivityExcludingShort"] = sens
    res["summary"] = new
    ok = not res["control"]["knownAnswerMismatches"] and all(v["ok"] for v in res["control"]["pooledVsM343"].values())
    res["controlPassed"] = bool(ok)
    json.dump(res, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False, default=float)
    print(json.dumps({"controlPassed": ok, "control": res["control"], "sensitivityExcludingShort": res["sensitivityExcludingShort"]}, indent=1, default=float))
    if mode == "--check" or not ok:
        sys.exit(0 if ok else 1)
    old = copy.deepcopy(A)
    for m in ("all", "warm", "shoulder"):
        rows = A["engineStartsByType"] if m == "all" else A["seasonalCharts"]["charts"]["EngineStartsByType"]["data"][m]
        for ent in rows:
            ck = ent.get("classKey") or ent["label"].lower().replace(" ", "_")
            ent.update(json.loads(json.dumps(new[m][ck], default=float)))
    # deep-diff: only the new leaf keys may differ
    NEWK = set(next(iter(new["all"].values())).keys())
    def walk(a, b, path):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in set(a) | set(b):
                if k not in a:
                    assert k in NEWK and path.endswith("]"), (path, k)
                    continue
                assert k in b, (path, k)
                walk(a[k], b[k], f"{path}/{k}")
        elif isinstance(a, list) and isinstance(b, list):
            assert len(a) == len(b), path
            for i, (x, y) in enumerate(zip(a, b)):
                walk(x, y, f"{path}[{i}]")
        else:
            assert canon(a) == canon(b), (path, a, b)
    walk(old, A, "")
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A, f, ensure_ascii=False, indent=1)
    print("spliced new fields into engineStartsByType and the three cohort copies; deep-diff clean")


if __name__ == "__main__":
    main()
