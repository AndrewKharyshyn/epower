import sys, os, json, glob, collections
import numpy as np, pandas as pd
ROOT = os.getcwd()
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools")]
from drive_raw_cache import fast_time
import compute_summary_arrays as C
from tools.thermal_support_ledger import raw_record

m = pd.read_csv("drive_master.csv", encoding="utf-8", low_memory=False)
cr = pd.read_csv("cadence_regime.csv", encoding="utf-8").set_index("file")
m["stratum"] = m["file"].map(cr["regime"]).fillna("unknown")
m.loc[m["stratum"].astype(str).str.strip() == "", "stratum"] = "unknown"
rawmap = {}
for p in glob.glob("raw/*.csv"):
    b = os.path.basename(p)
    if b.startswith("e4ORCE") or "comparison" in b.lower(): continue
    rawmap["".join(ch for ch in b if ch.isdigit())[:14]] = p
CH = {"hvIntake": ("[BMS] HV Battery Intake Air Temperature (℃)", -40, 90),
      "engCool": ("Температура охолодної рідини (℃)", -40, 150),
      "hvCool": ("[VCM] HV Coolant Temperature (℃)", -40, 120),
      "engIntake": ("Температура повітря, що всмоктується (℃)", -40, 90)}

def flags(cov, longest, nvalid, present, covt=0.5, gap=60):
    if not present: return "absent"
    if nvalid == 0: return "empty"
    if cov < covt: return "partial"
    if longest > gap: return "gappy"
    return "ok"

rows = []; outcomes = []
for i, r in m.iterrows():
    key = "".join(ch for ch in r["file"] if ch.isdigit())[:14]
    p = rawmap.get(key)
    if p is None:
        print("NO RAW", r["file"]); continue
    df = pd.read_csv(p, encoding="utf-8", low_memory=False)
    t = fast_time(df["time"], mixed=True)
    ok = t.notna().to_numpy()
    sec = ((t[ok] - t[ok].min()).dt.total_seconds()).to_numpy()
    tt = sec  # per-row seconds from min
    # use first timestamp as t0 (rows chronological after unwrap); spec: first to last timestamp
    t0 = tt[0] if len(tt) else 0.0; tend = tt.max() if len(tt) else 0.0
    t0 = tt.min() if len(tt) else 0.0
    span = tend - t0; nb = int(np.floor(span / 10)) + 1
    rec = {"i": i, "file": r["file"], "date": r["date"], "ts": r["time_start"], "stratum": r["stratum"], "month": str(r["date"])[:7]}
    for k, (name, lo, hi) in CH.items():
        present = name in df.columns
        d = {"present": present, "nValid": 0, "oow": 0, "sent": 0, "cov": 0.0, "longest": None, "med": None}
        if present:
            v = pd.to_numeric(df[name], errors="coerce").to_numpy()[ok]
            fin = np.isfinite(v)
            valid = fin & (v >= lo) & (v <= hi)
            d["oow"] = int((fin & ~valid).sum()); d["sent"] = int((fin & (v == -100)).sum())
            # collapse duplicate timestamps: valid if any valid; count nValid as unique timestamps with valid
            s = pd.Series(valid, index=tt).groupby(level=0).max()
            vt = np.sort(s.index[s.values].to_numpy())
            d["nValid"] = int(len(vt))
            if len(vt):
                bins = np.unique(np.floor((vt - t0) / 10).astype(int))
                d["cov"] = len(bins) / nb
                edges = np.concatenate([[t0], vt, [tend]])
                d["longest"] = float(np.diff(edges).max())
                d["med"] = float(np.median(np.diff(vt))) if len(vt) > 1 else None
        rec[k] = d
    rows.append(rec)
    # outcome
    fr = df
    o = raw_record(fr, r["distance_km"], r["drive_type"], C)
    if "status" in o: st = o["status"]
    else:
        h = o["hvc"]
        st = ("reached" if h["reached"] else "rightCensored") if h["status"] == "accepted" else "notEligible:" + h["status"]
    outcomes.append((r["stratum"], st))

out = {"n_rows": len(rows), "n_master": len(m)}
# 1 epoch
ordr = sorted(rows, key=lambda x: (str(x["date"]), str(x["ts"])))
ep = {}
for k in CH:
    val = [j for j, x in enumerate(ordr) if x[k]["nValid"] > 0]
    ep[k] = {"first": str(ordr[val[0]]["date"]) if val else None, "last": str(ordr[val[-1]]["date"]) if val else None,
             "nValidDrives": len(val), "after": len(ordr) - 1 - val[-1] if val else len(ordr)}
out["epoch"] = ep
FL = ["absent", "empty", "partial", "gappy", "ok"]
strata = ["fast", "slow", "unknown"]
def cnt(sel, k, covt=0.5, gap=60):
    c = collections.Counter(flags(x[k]["cov"], x[k]["longest"] or 0, x[k]["nValid"], x[k]["present"], covt, gap) for x in sel)
    return {f: c.get(f, 0) for f in FL}
out["byStratum"] = {}
for k in CH:
    out["byStratum"][k] = {}
    for s in strata:
        sel = [x for x in rows if x["stratum"] == s]
        out["byStratum"][k][s] = {"n": len(sel), **cnt(sel, k), "nOutOfWindow": sum(x[k]["oow"] for x in sel), "nSentinel100": sum(x[k]["sent"] for x in sel)}
out["monthStratum_hvIntake"] = {}
for mo in sorted({x["month"] for x in rows}):
    for s in strata:
        sel = [x for x in rows if x["month"] == mo and x["stratum"] == s]
        if sel: out["monthStratum_hvIntake"][mo + "|" + s] = {"n": len(sel), **cnt(sel, "hvIntake")}
out["sens_hvIntake"] = {}
for s in strata:
    sel = [x for x in rows if x["stratum"] == s]
    out["sens_hvIntake"][s] = {"cov0.25": cnt(sel, "hvIntake", 0.25), "cov0.75": cnt(sel, "hvIntake", 0.75), "gap30": cnt(sel, "hvIntake", 0.5, 30), "gap120": cnt(sel, "hvIntake", 0.5, 120)}
oc = collections.Counter(s for _, s in outcomes)
out["outcome"] = dict(oc)
out["outcomeByStratum"] = {s: dict(collections.Counter(st for ss, st in outcomes if ss == s)) for s in strata}
json.dump(out, open("analyses/M606_audit/audit_out.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(json.dumps({k: out[k] for k in ["n_rows","n_master","epoch","byStratum","outcome","outcomeByStratum"]}, ensure_ascii=False))
