#!/usr/bin/env python3
"""M466 stage B diagnostics for the GTR f_gen BASE movement 0.466 (348 drives / 63 days, M426) -> 0.518 (376 drives / 67 days), analyses/M466_spec.md section B.
Reads the script-written per-drive file fuel_recon_master.csv (current and at --prev-ref) and drive_master.csv / seasonal_drive_master.csv; writes analyses/M466_gtr_diag.json. Nothing is published.
Estimator (same as the headline and the sensitivity BASE): f_gen = sum(gen_to_traction * dist) / sum(traction_gross * dist) over canonical-clean fuel drives (eligibility.py).
  D1 reproduction of both headline values from the per-drive file
  D2 composition / shift-share (drive type, thermal regime, polling stratum): Delta f = sum_g (s_new,g - s_old,g) f_old,g + sum_g s_new,g (f_new,g - f_old,g), s = traction-km share (exact identity for a ratio of sums)
  D3 leave-one-day-out (all days; the 5 new days separately)
  D4 day-clustered percentile bootstrap (seed 42, 4000 draws) of f_gen on the current set and of the difference new - old
  D5 cold-penalty regime check (f_gen by thermal regime and by cold_fuel_frac band; new vs old)
  D6 data health of the new drives
Usage: python tools/m466_gtr_diag.py --prev-ref 3eb3f3c~1 [--out analyses/M466_gtr_diag.json]"""
import argparse, io, json, os, subprocess, sys
import numpy as np, pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
import eligibility as EL

B, SEED = 4000, 42


def git_text(ref, path):
    return subprocess.run(["git", "show", "%s:%s" % (ref, path)], capture_output=True, check=True).stdout.decode("utf-8")


def clean(fr):
    fr = fr[fr["f_gen"].notna()].copy()
    ok = set(EL.canonical_clean(list(fr["file"])))
    return fr[fr["file"].isin(ok)].copy()


def fgen(x):
    t = (x["traction_gross_kWh_100"] * x["distance_km"]).sum()
    return float((x["gen_to_traction_kWh_100"] * x["distance_km"]).sum() / t) if t > 0 else float("nan")


def shares(x, g):
    t = x["_T"].groupby(x[g]).sum()
    return (t / t.sum())


def shift_share(old, new, g):
    so, sn = shares(old, g), shares(new, g)
    fo = old.groupby(g).apply(fgen)
    fn = new.groupby(g).apply(fgen)
    keys = sorted(set(so.index) | set(sn.index) | set(fo.index) | set(fn.index), key=str)
    comp = within = 0.0
    rows = {}
    for k in keys:
        a, b = float(so.get(k, 0.0)), float(sn.get(k, 0.0))
        f0 = float(fo.get(k, np.nan))
        f1 = float(fn.get(k, np.nan))
        f0u = f0 if np.isfinite(f0) else float(fgen(new))          # a group absent from the old set enters at the new overall rate for the composition term (identity kept: within term uses the same reference)
        c = (b - a) * f0u
        w = b * ((f1 if np.isfinite(f1) else f0u) - f0u)
        comp += c
        within += w
        rows[str(k)] = {"shareOld": round(a, 4), "shareNew": round(b, 4), "fOld": None if not np.isfinite(f0) else round(f0, 4), "fNew": None if not np.isfinite(f1) else round(f1, 4), "composition": round(c, 4), "within": round(w, 4)}
    return {"total": round(fgen(new) - fgen(old), 4), "composition": round(comp, 4), "within": round(within, 4), "check": round(fgen(new) - fgen(old) - comp - within, 6), "groups": rows}


def boot(frame, days):
    """Day-clustered percentile bootstrap of f_gen; rows grouped by day."""
    ud = sorted(set(days))
    idx = {d: np.where(days == d)[0] for d in ud}
    g = (frame["gen_to_traction_kWh_100"] * frame["distance_km"]).values
    t = (frame["traction_gross_kWh_100"] * frame["distance_km"]).values
    gd = np.array([g[idx[d]].sum() for d in ud])
    td = np.array([t[idx[d]].sum() for d in ud])
    rng = np.random.default_rng(SEED)
    pick = rng.integers(0, len(ud), (B, len(ud)))
    return gd, td, pick


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prev-ref", required=True)
    ap.add_argument("--out", default="analyses/M466_gtr_diag.json")
    a = ap.parse_args()
    cur = pd.read_csv("fuel_recon_master.csv")
    prv = pd.read_csv(io.StringIO(git_text(a.prev_ref, "fuel_recon_master.csv")))
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    reg = pd.read_csv("seasonal_drive_master.csv", low_memory=False).set_index("file")["thermal_regime"]
    cadence = dm.set_index("file")["ev_rpm_dt_med_s"].map(lambda v: "undefined" if not np.isfinite(v) else ("fast" if v < 1.0 else "slow"))
    c, p = clean(cur), clean(prv)
    for x in (c, p):
        x["_T"] = x["traction_gross_kWh_100"] * x["distance_km"]
        x["day"] = x["date"].astype(str).str[:10]
        x["regime"] = x["file"].map(reg)
        x["cadence"] = x["file"].map(cadence)
    new = c[~c["file"].isin(set(p["file"]))].copy()
    old = c[c["file"].isin(set(p["file"]))].copy()
    out = {"prevRef": a.prev_ref, "estimator": "ratio of sums over canonical-clean fuel drives, distance-weighted (as the headline and the sensitivity BASE)"}
    out["D1"] = {"nNow": len(c), "daysNow": int(c["day"].nunique()), "fNow": round(fgen(c), 4), "nPrev": len(p), "daysPrev": int(p["day"].nunique()), "fPrev": round(fgen(p), 4),
                 "nNew": len(new), "daysNew": int(new["day"].nunique()), "fNewDrivesOnly": round(fgen(new), 4), "fOldDrivesOnCurrentFile": round(fgen(old), 4), "nOldStillPresent": len(old),
                 "kmNew": round(float(new["distance_km"].sum()), 1), "kmOld": round(float(old["distance_km"].sum()), 1)}
    out["D2"] = {g: shift_share(old, new, g) for g in ("drive_type", "regime", "cadence")}
    days = sorted(c["day"].unique())
    lodo = {}
    for d in days:
        lodo[d] = round(fgen(c[c["day"] != d]), 4)
    ndays = sorted(new["day"].unique())
    out["D3"] = {"min": min(lodo.values()), "max": max(lodo.values()), "argmin": min(lodo, key=lodo.get), "argmax": max(lodo, key=lodo.get),
                 "nDaysBelow0p5": sum(1 for v in lodo.values() if v < 0.5), "nDays": len(lodo), "newDays": {d: lodo[d] for d in ndays}, "dropAllNewDays": round(fgen(c[~c["day"].isin(ndays)]), 4)}
    dd = c["day"].values
    gd, td, pick = boot(c, dd)
    f = (gd[pick].sum(1)) / (td[pick].sum(1))
    out["D4"] = {"B": B, "seed": SEED, "cluster": "calendar day", "point": round(fgen(c), 4), "ci95": [round(float(np.percentile(f, 2.5)), 4), round(float(np.percentile(f, 97.5)), 4)], "shareDrawsBelow0p5": round(float((f < 0.5).mean()), 4)}
    # difference new minus old: bootstrap old days and new days independently (days are disjoint except the shared day)
    go, to_, _ = boot(old, old["day"].values)
    gn, tn, _ = boot(new, new["day"].values)
    rng = np.random.default_rng(SEED + 1)
    po = rng.integers(0, len(go), (B, len(go)))
    pn = rng.integers(0, len(gn), (B, len(gn)))
    df_ = gn[pn].sum(1) / tn[pn].sum(1) - go[po].sum(1) / to_[po].sum(1)
    # blind audit Rev 2 (analytical-auditor): old and new drives share one calendar day, so the primary difference interval resamples the days of the union JOINTLY
    ud = sorted(set(c["day"]))
    def per_day(x):
        g_ = (x["gen_to_traction_kWh_100"] * x["distance_km"]).groupby(x["day"]).sum().reindex(ud, fill_value=0.0).values
        t_ = (x["traction_gross_kWh_100"] * x["distance_km"]).groupby(x["day"]).sum().reindex(ud, fill_value=0.0).values
        return g_, t_
    (g_o, t_o), (g_n, t_n) = per_day(old), per_day(new)
    pj = np.random.default_rng(SEED + 2).integers(0, len(ud), (B, len(ud)))
    with np.errstate(invalid="ignore", divide="ignore"):
        dj = (g_n[pj].sum(1) / t_n[pj].sum(1)) - (g_o[pj].sum(1) / t_o[pj].sum(1))
    dj = dj[np.isfinite(dj)]
    out["D4"]["newMinusOldJointDaysCi95"] = [round(float(np.percentile(dj, 2.5)), 4), round(float(np.percentile(dj, 97.5)), 4)]
    out["D4"]["newMinusOldJointDaysNDraws"] = int(len(dj))
    out["D4"]["newMinusOldDrivesPoint"] = round(fgen(new) - fgen(old), 4)
    out["D4"]["newMinusOldDrivesCi95"] = [round(float(np.percentile(df_, 2.5)), 4), round(float(np.percentile(df_, 97.5)), 4)]
    out["D4"]["newDaysN"] = len(gn)
    out["D4"]["nonindependenceNote"] = "old and new drives share one calendar day (2026-10-13); the two resamples are drawn independently, so the difference interval ignores that day's shared component"
    cb = pd.cut(c["cold_fuel_frac"], [-0.001, 0.0, 0.05, 0.2, 1.0001], labels=["0", "(0,0.05]", "(0.05,0.2]", ">0.2"])
    out["D5"] = {"byRegime": {k: {"n": int(len(g)), "days": int(g["day"].nunique()), "f": round(fgen(g), 4), "nNew": int(g["file"].isin(set(new["file"])).sum())} for k, g in c.groupby("regime")},
                 "byColdFuelFrac": {str(k): {"n": int(len(g)), "f": None if len(g) == 0 else round(fgen(g), 4), "nNew": int(g["file"].isin(set(new["file"])).sum())} for k, g in c.groupby(cb, observed=False)},
                 "coldGate": {str(k): int(v) for k, v in c["cold_gate"].value_counts().items()},
                 "note": "descriptive; the regime / cold-fuel strata are display bands and the cold-penalty model constants are unchanged"}
    nz = new
    out["D6"] = {"nNew": len(nz), "fGenRange": [round(float(nz["f_gen"].min()), 3), round(float(nz["f_gen"].max()), 3)], "nOutside01": int(((nz["f_gen"] < 0) | (nz["f_gen"] > 1)).sum()),
                 "fuelBasis": {str(k): int(v) for k, v in nz["fuel_basis"].value_counts().items()}, "method": {str(k): int(v) for k, v in nz["method"].value_counts().items()},
                 "chargeSustainingShare": round(float(nz["charge_sustaining"].mean()), 3), "chargeSustainingShareOld": round(float(old["charge_sustaining"].mean()), 3),
                 "etaEngMedianNew": round(float(nz["eta_eng"].median()), 4), "etaEngMedianOld": round(float(old["eta_eng"].median()), 4), "kmPerDriveMedianNew": round(float(nz["distance_km"].median()), 1), "kmPerDriveMedianOld": round(float(old["distance_km"].median()), 1),
                 "nanColumns": {k: int(v) for k, v in nz.isna().sum().items() if v}, "cadenceNew": {str(k): int(v) for k, v in nz["cadence"].value_counts().items()}}
    with open(a.out, "w", encoding="utf-8", newline="\n") as f_:
        json.dump(out, f_, indent=1, ensure_ascii=False)
    print(json.dumps(out, ensure_ascii=False)[:6000])


if __name__ == "__main__":
    main()
