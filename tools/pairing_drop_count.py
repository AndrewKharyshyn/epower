#!/usr/bin/env python3
"""M794: report-only count of the current samples the master's current/voltage pairing (compute_drive_summary_v6._asof via window_use.pairs) does not use, per drive: samples with |I| >= 900 A (out-of-range sentinel filter) and samples with no pack-voltage sample within 1.5 s.
Reads raw bytes only; writes analyses/M794_pairing_drops.json (counts, no estimand, no payload change). Usage: python tools/pairing_drop_count.py"""
import hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd


def main():
    import ah_throughput as AH, compute_drive_summary_v6 as D
    loader = AH.raw_loader()
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    rows = []
    for fn in dm["file"]:
        b = loader(fn)
        if b is None:
            continue
        df, t = D._prep_bytes(b)
        I = D._series(df, t, "I")
        V = D._series(df, t, "V", lo=200, hi=450)
        if I is None or V is None:
            rows.append({"file": fn, "nI": 0 if I is None else len(I), "sentinel": 0, "noVoltage": 0, "kept": 0}); continue
        n = len(I); I2 = I[I["v"].abs() < 900]
        e = D._asof(I2.copy(), V, "V", D.V_ALIGN_TOL)
        rows.append({"file": fn, "nI": int(n), "sentinel": int(n - len(I2)), "noVoltage": int(e["V"].isna().sum()), "kept": int(e["V"].notna().sum())})
    r = pd.DataFrame(rows); r["dropped"] = r["nI"] - r["kept"]; r["share"] = r["dropped"] / r["nI"].where(r["nI"] > 0)
    out = {"milestone": "M794", "rule": "each current sample with |I| < 900 A takes the nearest pack-voltage sample within 1.5 s (merge_asof, base = current samples); samples without one are dropped; several current samples may share one voltage sample; nothing is overwritten",
           "nDrives": int(len(r)), "drivesWithAnyDrop": int((r["dropped"] > 0).sum()), "drivesWithSentinel": int((r["sentinel"] > 0).sum()), "drivesWithNoVoltage": int((r["noVoltage"] > 0).sum()),
           "droppedShare": {f"p{q}": round(float(np.nanpercentile(r["share"], q)), 5) for q in (50, 90, 99)} | {"max": round(float(np.nanmax(r["share"])), 5)},
           "totals": {k: int(r[k].sum()) for k in ("nI", "sentinel", "noVoltage", "kept", "dropped")},
           "worst": r.sort_values("share", ascending=False).head(10).to_dict("records"),
           "driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()}
    json.dump(out, open(os.path.join(ROOT, "analyses", "M794_pairing_drops.json"), "w", encoding="utf-8"), indent=1, default=float)
    print(json.dumps({k: v for k, v in out.items() if k != "worst"}, default=float))


if __name__ == "__main__":
    main()
