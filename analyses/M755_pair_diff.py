#!/usr/bin/env python3
"""M755 (Director condition on the scoped re-audit): script-written pair-level diff between the builder's pack-mean basis (compute_summary_arrays._battery_temp_traj: 1 s grid by MEAN of the samples in a second, ffill limit 3)
and the auditor's reimplementation (1 s grid by LAST sample, ffill limit 3). Counts the heat-soak pairs with an ambient and the tau fit points on both bases with the same pairing code and names the pairs whose eligibility differs.
Usage: XT_RAW_DIR=<raw> python analyses/M755_pair_diff.py   (writes analyses/M755_pair_diff.json; aggregates only, no file names)."""
import glob, json, os, re, sys
import numpy as np
import pandas as pd
from scipy.stats import theilslopes

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import compute_summary_arrays as C
import ambient_protocol as AP

RAW = os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"))
cfg = json.load(open(os.path.join(ROOT, "summary_config.json"), encoding="utf-8"))["ambientByDrive"]
key = lambda f: "".join(re.search(r"(\d{4})-?(\d{2})-?(\d{2})[ _-](\d{2})-?(\d{2})-?(\d{2})", f).groups())
rawp = {key(os.path.basename(p)): p for p in glob.glob(os.path.join(RAW, "*.csv"))}
loader = lambda fn: open(rawp[key(fn)], "rb").read()

traj = C._battery_temp_traj(dm, loader)                       # builder basis


def aud_pm():
    out = {}
    for f in dm["file"]:
        p = rawp[key(f)]
        cols = [c for c in pd.read_csv(p, nrows=0).columns if re.search(r"HV Battery Temperature Sensor [1-4]", c)]
        x = pd.read_csv(p, usecols=["time"] + cols)
        t = pd.to_timedelta(x.time, errors="coerce")
        x = x[cols].apply(pd.to_numeric, errors="coerce")
        x.index = t
        x = x[x.index.notna()]
        x = x.where((x >= -40) & (x <= 80))
        x = x[~x.index.duplicated()]
        pm = x.resample("1s").last().ffill(limit=3).mean(axis=1).dropna()
        if len(pm):
            out[f] = {"pm_start": int(round(pm.iloc[0])), "pm_end": int(round(pm.iloc[-1]))}
    return out


aud = aud_pm()
d = C._full_datetimes(dm).dropna(subset=["ts_full"]).sort_values("ts_full").reset_index(drop=True)


def count(tr, plain):
    amb = {}
    for fn, v in cfg.items():
        m = AP.mean_reading(v) if plain else (sum(float(x) for x in v) / len(v) if isinstance(v, list) else None)
        if m is not None:
            amb[fn] = m
    rows = []
    for k in range(len(d) - 1):
        a, b = d.iloc[k], d.iloc[k + 1]
        ta, tb = tr.get(a["file"], {}), tr.get(b["file"], {})
        if "pm_end" not in ta or "pm_start" not in tb or pd.isna(a["te_full"]) or pd.isna(b["ts_full"]):
            continue
        gap = (b["ts_full"] - a["te_full"]).total_seconds() / 3600.0
        if gap < 0:
            continue
        am = amb.get(b["file"])
        ie = ta["pm_end"] - am if am is not None else None
        re_ = tb["pm_start"] - am if am is not None else None
        rows.append((k, gap, ie, re_))
    amb_ok = {r[0] for r in rows if r[2] is not None and r[2] > 0}
    fit = [r for r in rows if r[2] is not None and r[2] > 3.0 and r[3] is not None and r[3] > 0]
    fit_ids = {r[0] for r in fit}
    x = np.array([r[1] for r in fit]); y = np.log(np.array([r[3] / r[2] for r in fit]))
    ok = x > 0
    sl = theilslopes(y[ok], x[ok])[0] if ok.sum() > 2 else float("nan")
    return {"nPairs": len(rows), "nPairsAmbient": len(amb_ok), "tauFitN": len(fit), "tauSenH": round(-1 / sl, 3)}, amb_ok, fit_ids


res = {}
sets = {}
for name, tr in (("builder", traj), ("auditor", {f: v for f, v in aud.items()})):
    for plain in (False, True):
        r, a_ok, f_ok = count(tr, plain)
        res["%s_%s" % (name, "plainRead" if plain else "listOnly")] = r
        sets[(name, plain)] = (a_ok, f_ok)
diffs = {}
for plain in (False, True):
    ba, bf = sets[("builder", plain)]; aa, af = sets[("auditor", plain)]
    diffs["plainRead" if plain else "listOnly"] = {"ambientPairsOnlyBuilder": len(ba - aa), "ambientPairsOnlyAuditor": len(aa - ba), "fitOnlyBuilder": len(bf - af), "fitOnlyAuditor": len(af - bf)}
nd = sum(1 for f in dm["file"] if f in aud and f in traj and (aud[f]["pm_start"] != traj[f].get("pm_start") or aud[f]["pm_end"] != traj[f].get("pm_end")))
res["driveLevel"] = {"nDrives": len(dm), "nPackMeanDiffers": nd,
                     "maxAbsDiffStart": int(max([abs(aud[f]["pm_start"] - traj[f]["pm_start"]) for f in aud if f in traj and "pm_start" in traj[f]] or [0])),
                     "maxAbsDiffEnd": int(max([abs(aud[f]["pm_end"] - traj[f]["pm_end"]) for f in aud if f in traj and "pm_end" in traj[f]] or [0]))}
res["pairLevelDiff"] = diffs
res["note"] = "builder = mean-in-second 1 s grid (compute_summary_arrays._battery_temp_traj); auditor = last-sample-in-second 1 s grid. Same pairing, filters (init excess > 0 for the ambient count, > 3.0 and resid > 0 for the fit) and Sen slope through the origin."
json.dump(res, open(os.path.join(ROOT, "analyses", "M755_pair_diff.json"), "w", encoding="utf-8", newline="\n"), indent=1)
print(json.dumps(res, indent=1))
