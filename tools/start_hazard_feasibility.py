"""M701 feasibility table (eligibility counts only, no estimate): pedal / target-torque coverage per canonical-clean drive,
by month; engine-off seconds are those with rpm <= 300 or missing rpm (nanIsOff). Spec analyses/M701_spec.md Rev 1 item 7."""
import os, sys, json, hashlib
import numpy as np, pandas as pd
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import re
from project_paths import resolve_raw
_DIG = lambda n: re.sub(r"\D", "", os.path.basename(n))[-14:]
_RAWIDX = {}


def _resolve(fname, root):
    """resolve_raw plus the digits-only match (master key 20260511_185709 vs raw 2026-05-11 18-57-09)."""
    p = resolve_raw(fname, root)
    if p:
        return p
    if not _RAWIDX:
        for n in os.listdir(root):
            _RAWIDX.setdefault(_DIG(n), os.path.join(root, n))
    return _RAWIDX.get(_DIG(fname))
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RAW = os.environ.get("XT_RAW_DIR", os.path.join(ROOT, "raw"))
PED = "Положення педалі акселератора D (%)"; PEDE = "Положення педалі акселератора E (%)"
TT = "[VCM] Target Motor Torque (N\u22c5m)"; RPM = "Оберти двигуна (rpm)"


def main(out):
    m = pd.read_csv(os.path.join(ROOT, "drive_master.csv"))
    m = m[m["ens_outlier_v2"].astype(str).str.lower().isin(["false", "0", "0.0"])]
    rows = []
    for _, r in m.iterrows():
        f = _resolve(r["file"], RAW)
        if not f or not os.path.exists(f):
            rows.append({"file": r["file"], "date": str(r["date"]), "missingRaw": True}); continue
        d = pd.read_csv(f, usecols=lambda c: c in (PED, PEDE, TT, RPM))
        for c in (PED, PEDE, TT):
            if c in d:
                d[c] = d[c].ffill(limit=15)   # spec Rev 1 item 2: LOCF with the existing 15 s limit, as the detector grid
        off = ~(d[RPM] > 300) if RPM in d else pd.Series(False, index=d.index)
        n_off = int(off.sum())
        rec = {"file": r["file"], "date": str(r["date"]), "nRows": len(d), "nOffSeconds": n_off}
        for nm, c in (("ped", PED), ("pedE", PEDE), ("tt", TT)):
            rec[nm + "Present"] = bool(c in d)
            rec[nm + "OffCoverage"] = float(d.loc[off, c].notna().mean()) if (c in d and n_off) else 0.0
        rows.append(rec)
    df = pd.DataFrame(rows)
    n_missing = int(df["missingRaw"].fillna(False).sum()) if "missingRaw" in df else 0
    df = df[df.get("missingRaw", False) != True].copy() if "missingRaw" in df else df
    df["month"] = df["date"].str[:7]
    elig = lambda c: (df[c] > 0.90)
    df["pedEligible"] = elig("pedOffCoverage"); df["ttEligible"] = elig("ttOffCoverage"); df["bothEligible"] = df["pedEligible"] & df["ttEligible"]
    def cnt(mask):
        s = df[mask]; return {"drives": int(len(s)), "days": int(s["date"].nunique())}
    res = {"spec": "analyses/M701_spec.md Rev 1 item 7", "nCleanDrives": int(len(df)), "masterRows": int(len(m)), "missingRawFiles": n_missing,
           "pedEligible": cnt(df["pedEligible"]), "ttEligible": cnt(df["ttEligible"]), "bothEligible": cnt(df["bothEligible"]),
           "byMonth": {k: {"drives": int(len(g)), "pedEligible": int(g["pedEligible"].sum()), "ttEligible": int(g["ttEligible"].sum()),
                           "pedEligibleDays": int(g.loc[g["pedEligible"], "date"].nunique())} for k, g in df.groupby("month")},
           "supportLadder": "10 drives on 5 days", "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest()}
    df.to_csv(out.replace(".json", "_perdrive.csv"), index=False)
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: res[k] for k in ("nCleanDrives", "pedEligible", "ttEligible", "bothEligible")}))


if __name__ == "__main__":
    main(sys.argv[1])
