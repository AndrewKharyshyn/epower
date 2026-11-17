"""M707 R4 verification: ledger pack_temp_start_c (10 s hold composite, median of first 30 s) vs the native start = mean of each probe's own first valid reading
(read independently of raw_temp_pass.py). Split by logger cadence (master I_sample_period_s). Read-only on raw/."""
import csv, json, os, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
RAW = os.environ.get("XT_RAW_DIR", os.path.join(ROOT, "raw"))
S = pd.read_csv(os.path.join(ROOT, "seasonal_drive_master.csv"), low_memory=False, usecols=["file", "date", "pack_temp_start_c"])
M = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False, usecols=["file", "I_sample_period_s"])
dig = lambda f: "".join(c for c in str(f) if c.isdigit())
M["k"] = M["file"].map(dig); S["k"] = S["file"].map(dig)
D = S.merge(M[["k", "I_sample_period_s"]], on="k", how="left")
raws = {dig(f): f for f in os.listdir(RAW) if f.lower().endswith(".csv")}
PROBES = [f"[BMS] HV Battery Temperature Sensor {i} (\u2103)" for i in range(1, 5)]
rows = []
for _, r in D.iterrows():
    f = raws.get(r["k"])
    if f is None: continue
    with open(os.path.join(RAW, f), newline="", encoding="utf-8", errors="replace") as fh:
        rd = csv.reader(fh); h = next(rd)
        ix = [h.index(p) if p in h else None for p in PROBES]
        first = [None] * 4
        for n, row in enumerate(rd):
            for j, i in enumerate(ix):
                if first[j] is None and i is not None and i < len(row) and row[i] not in ("", "-"):
                    try: first[j] = float(row[i])
                    except ValueError: pass
            if all(v is not None for v in first) or n > 400: break
    got = [v for v in first if v is not None]
    if len(got) == 4:
        rows.append((r["k"], str(r["date"]), r["pack_temp_start_c"], float(np.mean(got)), first[0]))
X = pd.DataFrame(rows, columns=["k", "date", "ledger", "native4", "T1"])
X["d"] = X["ledger"] - X["native4"]
X["slow"] = X["date"] >= "2026-09-06"  # logger polling change window named in the restart census (slow-polled from 2026-09-06)
def summ(g):
    return {"n": int(len(g)), "meanDiff": round(float(g.d.mean()), 3), "share>=1C": round(float((g.d >= 1).mean()), 3), "max": round(float(g.d.max()), 2)}
out = {"slow": summ(X[X.slow]), "fast": summ(X[~X.slow])}
json.dump(out, open(os.path.join(os.path.dirname(__file__), "start_bias.json"), "w"), indent=1)
print(json.dumps(out, indent=1))
