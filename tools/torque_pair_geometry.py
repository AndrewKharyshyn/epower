"""M691: timestamps-only geometry of the actual-torque / target-torque rows (spec analyses/M690_spec.md section 10). No torque value is read or used."""
import json, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
TOL = 0.5


def geometry(csv_bytes):
    import compute_drive_summary_v6 as D
    df, t = D._prep_bytes(csv_bytes)
    if "motor_torque" not in df.columns or "target_torque" not in df.columns:
        return None
    ts = (t - t.min()).dt.total_seconds().to_numpy(float)
    ia = np.flatnonzero(df["motor_torque"].notna().to_numpy()); it = np.flatnonzero(df["target_torque"].notna().to_numpy())
    if len(ia) == 0 or len(it) == 0:
        return None
    j = np.searchsorted(it, ia, side="right") - 1
    ok = j >= 0
    gap = ts[ia[ok]] - ts[it[j[ok]]]
    rowd = ia[ok] - it[j[ok]]
    return {"nActual": int(len(ia)), "nTarget": int(len(it)), "gaps": gap, "rowDist": rowd}


def main():
    import ah_throughput as AH
    master = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), usecols=["file"], low_memory=False)
    cad = pd.read_csv(os.path.join(ROOT, "cadence_regime.csv"))
    reg = {r.file: (r.regime if isinstance(r.regime, str) else "unknown") for r in cad.itertuples()}
    loader = AH.raw_loader(os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    by = {}
    nd = {}
    for f in sorted(master["file"]):
        b = loader(f)
        if b is None:
            continue
        g = geometry(b)
        if g is None:
            continue
        k = reg.get(f, "unknown")
        by.setdefault(k, {"gaps": [], "rowDist": [], "nActual": 0, "nPaired": 0})
        by[k]["gaps"].append(g["gaps"]); by[k]["rowDist"].append(g["rowDist"]); by[k]["nActual"] += g["nActual"]
        by[k]["nPaired"] += int(((g["gaps"] >= 0) & (g["gaps"] <= TOL)).sum())
        nd[k] = nd.get(k, 0) + 1
    out = {"spec": "analyses/M690_spec.md section 10", "note": "timestamps only; no torque value read; computed before any torque statistic", "tolS": TOL, "byCadence": {}}
    for k, v in by.items():
        gp = np.concatenate(v["gaps"]); rd = np.concatenate(v["rowDist"])
        out["byCadence"][k] = {"nDrives": nd[k], "nActualRows": v["nActual"], "nPairedAtTol": v["nPaired"], "unpairedShare": round(1 - v["nPaired"] / v["nActual"], 5),
                               "gapSecondsQuantiles": {q: round(float(np.percentile(gp, q)), 4) for q in (5, 50, 95, 99, 99.9)}, "gapMax": round(float(gp.max()), 3),
                               "rowDistanceShare": {str(int(x)): round(float(np.mean(rd == x)), 5) for x in sorted(set(rd.tolist()))[:6]}}
    json.dump(out, open(os.path.join(ROOT, "analyses", "M691_pair_geometry.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps(out)[:1800])


if __name__ == "__main__":
    main()
