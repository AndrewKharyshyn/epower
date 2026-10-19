#!/usr/bin/env python3
"""M460 (spec analyses/M460_spec.md Rev 1.1): the zero-logged-fuel distance share versus the RPM-defined engine-off distance share (M432 follow-up), payload only.
Per drive the released 1 Hz grid is rebuilt with the released helpers (compute_drive_summary_v6._prep_bytes / _series / ENG_ALIGN_TOL / _ev_debounce) and every grid second with a known RPM and a known logged fuel rate is
placed in one of four states: A = RPM-off and zero fuel, B = RPM-on and zero fuel (motored-unfuelled), C = RPM-off and fuel logged (inconsistency flag), D = RPM-on and fuel logged. Seconds with an unknown fuel rate are
kept apart (their distance is in no state). Distances are speed-integrated distance times the released odometer scale k, so that A + C + (RPM-off with unknown fuel) = the master's ev_dist_km (gate G1).
The fuel rate is a logged / app-calculated channel (CLAUDE.md); nothing here is a physical claim about injection. Ratio of sums over drives; day-clustered percentile bootstrap (default_rng(42), integers(0, D, (B, D)), B = 4000)."""
import concurrent.futures as cf
import hashlib
import io
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)

SPEC = "analyses/M460_spec.md"
FUEL, USED = "Витрати палива (L/h)", "Використане паливо (L)"
PLAUS_MAX_LH = 40.0                       # Rev 1.1 (b): a logged rate above this is treated as unknown
RPM_OFF = 400.0
DEBOUNCE = 3
COV_MIN = 0.95
EPS_SENS = (0.05, 0.10, 0.35)
MOTORED = dict(rpm=2000.0, boost=-0.70, load=8.0)        # M46 / M48 classifier (compute_summary_arrays._dissipation_census), verbatim
MOTORED_MIN_SHARE = 0.50                                 # Rev 1.1 (a): below this the channel cannot see the motored state -> not identifiable
INCONSISTENT_FLAG = 0.10                                 # Rev 1.1 (e): C / (A + C)
MARGIN_PP = 1.0
B_DRAWS, SEED = 4000, 42


def _V():
    import compute_drive_summary_v6 as V
    return V


def _fuel_series(df, t, col, hi=None):
    if col not in df.columns:
        return None
    v = pd.to_numeric(df[col], errors="coerce")
    m = v.notna() & (v >= 0)
    if hi is not None:
        m &= v <= hi
    if not m.any():
        return None
    s = pd.DataFrame({"t": t[m].values, "v": v[m].astype(float).values}).sort_values("t").reset_index(drop=True)
    return s if len(s) else None


def eval_drive(csv_bytes, tol="3s"):
    """All configurations of one drive in one pass. Returns a dict of scalars (km, seconds) or {'skip': reason}."""
    V = _V()
    df, t = V._prep_bytes(csv_bytes)
    eng = V._series(df, t, "eng_rpm", lo=0)
    spd = V._series(df, t, "speed", lo=0, hi=260)
    if spd is None or len(spd) < 20:
        spd = V._series(df, t, "speed_obd", lo=0, hi=260)
    if eng is None or spd is None or len(eng) < 20:
        return {"skip": "no rpm or speed channel"}
    fuel_all = _fuel_series(df, t, FUEL)
    if fuel_all is None or len(fuel_all) < 20:
        return {"skip": "no fuel-rate channel"}
    tv = t.dropna()
    grid = pd.DataFrame({"t": pd.date_range(tv.min(), tv.max(), freq="1s")})
    if len(grid) < 10:
        return {"skip": "short drive"}

    def merged(tolerance):
        tl = pd.Timedelta(tolerance)
        g = pd.merge_asof(grid, spd.rename(columns={"v": "speed"}), on="t", direction="nearest", tolerance=pd.Timedelta(V.ENG_ALIGN_TOL))
        g = pd.merge_asof(g, eng.rename(columns={"v": "rpm"}), on="t", direction="nearest", tolerance=pd.Timedelta(V.ENG_ALIGN_TOL))
        f_ok = fuel_all[fuel_all["v"] <= PLAUS_MAX_LH]
        g = pd.merge_asof(g, f_ok.rename(columns={"v": "fuel"}), on="t", direction="nearest", tolerance=tl)
        return g

    g = merged(tol)
    v = g["speed"].fillna(0.0)
    g["dkm"] = v / 3600.0
    dist_int = float(g["dkm"].sum())
    odo = V._series(df, t, "odo")
    dist_odo = float(odo["v"].max() - odo["v"].min()) if odo is not None and len(odo) else np.nan
    k = (dist_odo / dist_int) if (dist_int > 0 and np.isfinite(dist_odo) and dist_odo > 0) else np.nan
    kk = k if np.isfinite(k) else 1.0
    known = g["rpm"].notna()
    off = V._ev_debounce(known & (g["rpm"] <= RPM_OFF), DEBOUNCE) & known
    on = known & ~off
    fknown = g["fuel"].notna()
    out = {"k": None if not np.isfinite(k) else float(k), "covFuel": float(fknown.mean()), "covRpm": float(known.mean()), "covSpeed": float(g["speed"].notna().mean()),
           "fuelDtMedS": float(fuel_all["t"].diff().dt.total_seconds().median()), "evDistKm": float(g.loc[off, "dkm"].sum() * kk), "distIntKm": dist_int * kk, "nSec": int(len(g))}

    def states(zf):
        both = known & fknown
        A, B_, C_, D_ = off & zf & both, on & zf & both, off & ~zf & both, on & ~zf & both
        d = lambda m: float(g.loc[m, "dkm"].sum() * kk)
        return dict(A=d(A), B=d(B_), C=d(C_), D=d(D_), offUnknownFuel=d(off & ~fknown), onUnknownFuel=d(on & ~fknown), unknownRpm=d(~known),
                    sA=int(A.sum()), sB=int(B_.sum()), sC=int(C_.sum()), sD=int(D_.sum()))

    fv = g["fuel"]
    zf_raw0 = fknown & (fv <= 0.0)
    zf_deb0 = V._ev_debounce(fknown & (fv <= 0.0), DEBOUNCE) & fknown
    out["primary"] = states(zf_deb0)                                   # eps = 0, debounced (Rev 1.1 c)
    out["raw"] = states(zf_raw0)                                       # sensitivity: raw aligned state
    for e in EPS_SENS:
        out["eps%g" % e] = states(V._ev_debounce(fknown & (fv <= e), DEBOUNCE) & fknown)
    # diagnostic: undebounced RPM x raw ZF crosstab (seconds)
    off_raw = known & (g["rpm"] <= RPM_OFF)
    both = known & fknown
    out["crosstabRaw"] = dict(A=int((off_raw & zf_raw0 & both).sum()), B=int((~off_raw & known & zf_raw0 & both).sum()), C=int((off_raw & ~zf_raw0 & both).sum()), D=int((~off_raw & known & ~zf_raw0 & both).sum()))
    # counter-based consistency row (same app calculation): zero increment of the cumulative fuel counter between grid seconds
    cnt = _fuel_series(df, t, USED)
    if cnt is not None and len(cnt) >= 20:
        gc = pd.merge_asof(grid, cnt.rename(columns={"v": "used"}), on="t", direction="nearest", tolerance=pd.Timedelta(tol))
        cknown = gc["used"].notna() & gc["used"].shift(1).notna()
        zc = V._ev_debounce(cknown & ((gc["used"] - gc["used"].shift(1)).abs() <= 1e-9), DEBOUNCE) & cknown
        both_c = known & cknown
        d = lambda m: float(g.loc[m, "dkm"].sum() * kk)
        out["counter"] = dict(A=d(off & zc & both_c), B=d(on & zc & both_c), C=d(off & ~zc & both_c), D=d(on & ~zc & both_c), covCounter=float(cknown.mean()),
                              fuelledZeroIncShare=float(((fknown & (fv > 0) & zc).sum()) / max(int((fknown & (fv > 0)).sum()), 1)))
    # construct validity: M46 / M48 classifier motored seconds
    boost = V._series(df, t, "boost")
    load = V._series(df, t, "eng_load_calc")
    if boost is not None and load is not None:
        gb = pd.merge_asof(g[["t"]], boost.rename(columns={"v": "boost"}), on="t", direction="nearest", tolerance=pd.Timedelta(V.ENG_ALIGN_TOL))
        gb = pd.merge_asof(gb, load.rename(columns={"v": "load"}), on="t", direction="nearest", tolerance=pd.Timedelta(V.ENG_ALIGN_TOL))
        mot = known & (g["rpm"] > MOTORED["rpm"]) & (gb["boost"] <= MOTORED["boost"]) & (gb["load"] <= MOTORED["load"])
        out["motored"] = dict(sec=int(mot.sum()), secWithFuelKnown=int((mot & fknown).sum()), secZF=int((mot & zf_deb0).sum()))
    # 1.5 s alignment sensitivity (support lost / gained): primary states recomputed with the fuel channel at 1.5 s
    g15 = merged("1500ms")
    fk15 = g15["fuel"].notna()
    zf15 = V._ev_debounce(fk15 & (g15["fuel"] <= 0.0), DEBOUNCE) & fk15
    both15 = known & fk15
    d15 = lambda m: float(g.loc[m, "dkm"].sum() * kk)
    out["tol1.5"] = dict(A=d15(off & zf15 & both15), B=d15(on & zf15 & both15), C=d15(off & ~zf15 & both15), D=d15(on & ~zf15 & both15), covFuel=float(fk15.mean()))
    return out


def _worker(args):
    f, path = args
    try:
        with open(path, "rb") as fh:
            return f, eval_drive(fh.read())
    except Exception as ex:                       # noqa: BLE001 (recorded, never silent)
        return f, {"skip": "error: %s" % ex}


def day_counts(days, b=B_DRAWS, seed=SEED):
    ud = np.array(sorted(set(days)))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(ud), (b, len(ud)))
    cnt = np.zeros((b, len(ud)))
    for i in range(b):
        cnt[i] = np.bincount(idx[i], minlength=len(ud))
    return ud, cnt


def ratio_ci(num_by_day, den_by_day, cnt):
    """Day-level numerator / denominator arrays (aligned to the sorted unique days of cnt); returns (point, [lo, hi], failed_share)."""
    pt = float(num_by_day.sum() / den_by_day.sum())
    nb, db = cnt @ num_by_day, cnt @ den_by_day
    with np.errstate(invalid="ignore", divide="ignore"):
        dr = np.where(db > 0, nb / db, np.nan)
    fin = np.isfinite(dr)
    if fin.mean() < 0.975:
        return pt, None, float(1 - fin.mean())
    return pt, [float(np.percentile(dr[fin], 2.5)), float(np.percentile(dr[fin], 97.5))], float(1 - fin.mean())


def quantity(rows, cfg, num_fn, den_key="dist", days=None):
    """A share (in percent) over the drive rows `rows` (list of dicts) with the day-clustered interval."""
    ud, cnt = day_counts([r["date"] for r in rows])
    di = {d: i for i, d in enumerate(ud)}
    num = np.zeros(len(ud))
    den = np.zeros(len(ud))
    for r in rows:
        i = di[r["date"]]
        num[i] += num_fn(r[cfg])
        den[i] += r[den_key]
    pt, ci, failed = ratio_ci(num, den, cnt)
    return {"pct": round(100 * pt, 3), "ci95": None if ci is None else [round(100 * ci[0], 3), round(100 * ci[1], 3)], "failedDrawShare": round(failed, 4), "nDrives": len(rows), "nDays": len(ud)}


def spec_sha():
    return hashlib.sha256(open(SPEC, "rb").read()).hexdigest()


def frozen_ok():
    return ("M460 spec sha256 " + spec_sha()) in open("CHANGELOG.md", encoding="utf-8").read(150000)


def build(workers=5, smoke_files=None):
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    ens = dm["ens_outlier_v2"].map(lambda x: bool(x) if x == x else False) if "ens_outlier_v2" in dm else pd.Series(False, index=dm.index)
    evv = dm["ev_valid"].map(lambda x: bool(x) if x == x else False)
    p0 = dm[evv & ~ens].copy()
    seas = pd.read_csv("seasonal_drive_master.csv", low_memory=False).set_index("file")["thermal_regime"]
    import glob
    import corpus_manifest as CM
    rawmap = {}
    for pth in sorted(glob.glob(os.path.join("raw", "*.csv"))):
        rawmap.setdefault(CM._canonical(os.path.basename(pth)), pth)
    todo = [(f, rawmap.get(CM._canonical(str(f)), os.path.join("raw", f))) for f in p0["file"]]
    if smoke_files is not None:
        todo = todo[::max(len(todo) // smoke_files, 1)][:smoke_files]        # code test only: an evenly spread sample, never a result
    res = {}
    with cf.ProcessPoolExecutor(max_workers=workers) as ex:
        for f, r in ex.map(_worker, todo, chunksize=4):
            res[f] = r
    skipped = {f: r["skip"] for f, r in res.items() if "skip" in r}
    rows, excluded = [], dict(skipped)
    for _, m in p0.iterrows():
        r = res.get(m["file"])
        if r is None or "skip" in r:
            continue
        if r["covFuel"] < COV_MIN or r["covRpm"] < COV_MIN or r["covSpeed"] < COV_MIN:
            excluded[m["file"]] = "coverage below %.2f (fuel %.3f, rpm %.3f, speed %.3f)" % (COV_MIN, r["covFuel"], r["covRpm"], r["covSpeed"])
            continue
        rr = dict(r)
        rr.update(file=m["file"], date=str(m["date"])[:10], dist=float(m["distance_km"]), evKm=float(m["ev_dist_km"]), cohort=str(seas.get(m["file"], "unknown")),
                  rpmPoll="fast" if m["ev_rpm_dt_med_s"] < 1.0 else "slow", fuelPoll="fast" if r["fuelDtMedS"] < 1.0 else "slow")
        rows.append(rr)
    out = {"nP0": int(len(p0)), "nSkipped": len(excluded), "excluded": excluded, "nPF": len(rows)}
    if not rows:
        out["status"] = "no drives"
        return out, rows
    # G1 parity: A + C + RPM-off with unknown fuel = master ev_dist_km (stored rounding 5e-4 km per drive)
    par = [abs(r["primary"]["A"] + r["primary"]["C"] + r["primary"]["offUnknownFuel"] - r["evKm"]) for r in rows]
    out["G1"] = {"maxAbsDiffKm": round(float(max(par)), 6), "nOver5e-4": int(sum(p > 5e-4 for p in par)), "tolKm": 5e-4}
    out["G1"]["pass"] = bool(out["G1"]["nOver5e-4"] == 0)
    # construct validity (a)
    mot = [r["motored"] for r in rows if "motored" in r]
    msec, mzf = sum(x["sec"] for x in mot), sum(x["secZF"] for x in mot)
    out["constructValidity"] = {"nDrivesWithBoostLoad": len(mot), "motoredSeconds": int(msec), "motoredSecondsWithZeroFuelState": int(mzf), "share": None if msec == 0 else round(mzf / msec, 4), "minShare": MOTORED_MIN_SHARE,
                                "rule": "M46/M48 classifier (rpm > 2000, boost <= -0.70, calculated load <= 8) seconds that also carry the debounced zero-fuel state; below the minimum share the channel cannot see the motored state"}
    ident = msec > 0 and (mzf / msec) >= MOTORED_MIN_SHARE
    out["constructValidity"]["identifiable"] = bool(ident)
    return out, rows


def finish(out, rows):
    """Headline, decomposition, sensitivities and strata (only when the construct-validity gate passes)."""
    cv = out["constructValidity"]
    if not cv["identifiable"]:
        out["status"] = "not identifiable"
        out["reading"] = "The logged fuel rate does not carry the motored-unfuelled state in a share of at least %d %% of the classifier-motored seconds; the zero-fuel comparison is not identifiable and no headline is emitted." % int(100 * MOTORED_MIN_SHARE)
        return out
    out["status"] = "computed"
    st = lambda key: (lambda s: s)
    P = "primary"
    dist_all = sum(r["dist"] for r in rows)
    q = lambda rr, cfg, fn: quantity(rr, cfg, fn)
    rpm_fn = lambda s: s["A"] + s["C"] + s["offUnknownFuel"]
    out["primary"] = {
        "shareRpmReleasedDefinition": q(rows, P, rpm_fn),
        "shareZeroFuel": q(rows, P, lambda s: s["A"] + s["B"]),
        "motored": q(rows, P, lambda s: s["B"]),
        "inconsistent": q(rows, P, lambda s: s["C"]),
        "unknownFuelDistance": q(rows, P, lambda s: s["offUnknownFuel"] + s["onUnknownFuel"]),
        "diff": q(rows, P, lambda s: s["B"] - s["C"]),
        "denominator": "sum of distance_km over P_F (the released denominator); known-support shares below use the distance of the states A-D only",
        "sumDistanceKm": round(dist_all, 1)}
    a_ = sum(r[P]["A"] for r in rows); b_ = sum(r[P]["B"] for r in rows); c_ = sum(r[P]["C"] for r in rows); d_ = sum(r[P]["D"] for r in rows)
    out["decomposition"] = {"A_engineOffNoFuelKm": round(a_, 1), "B_engineOnNoFuelKm": round(b_, 1), "C_engineOffFuelLoggedKm": round(c_, 1), "D_fuelledKm": round(d_, 1),
                            "knownSupportShareZeroFuelPct": round(100 * (a_ + b_) / (a_ + b_ + c_ + d_), 3), "knownSupportShareRpmPct": round(100 * (a_ + c_) / (a_ + b_ + c_ + d_), 3)}
    ac = a_ + c_
    flag = (c_ / ac) if ac > 0 else None
    out["inconsistencyFlag"] = {"C_over_AplusC": None if flag is None else round(flag, 4), "threshold": INCONSISTENT_FLAG, "fires": bool(flag is not None and flag > INCONSISTENT_FLAG)}
    d = out["primary"]["diff"]
    inside = d["ci95"] is not None and abs(d["ci95"][0]) <= MARGIN_PP and abs(d["ci95"][1]) <= MARGIN_PP
    out["reading"] = ("diff not interpreted (inconsistency flag fires)" if out["inconsistencyFlag"]["fires"] else
                      ("the two definitions do not differ materially on these drives under the stated conventions (whole interval within +-%g pp)" % MARGIN_PP if inside else "the difference is stated as found with its decomposition (interval not within +-%g pp)" % MARGIN_PP))
    # sensitivities (ranges over declared conventions; common support = the same drives; the 1.5 s row lists support lost)
    sens = {}
    for name in ("raw", "eps0.05", "eps0.1", "eps0.35"):
        sens[name] = {"shareZeroFuel": q(rows, name, lambda s: s["A"] + s["B"]), "diff": q(rows, name, lambda s: s["B"] - s["C"])}
    rows15 = [r for r in rows if r["tol1.5"]["covFuel"] >= COV_MIN]
    sens["tol1.5"] = {"nDrivesSupported": len(rows15), "nDrivesLost": len(rows) - len(rows15), "shareZeroFuel": q(rows15, "tol1.5", lambda s: s["A"] + s["B"]), "diff": q(rows15, "tol1.5", lambda s: s["B"] - s["C"])}
    ctr = [r for r in rows if "counter" in r]
    sens["counterConsistencyRow"] = {"label": "same app calculation, not an independent definition", "nDrives": len(ctr), "shareZeroFuel": q(ctr, "counter", lambda s: s["A"] + s["B"]) if ctr else None,
                                     "diff": q(ctr, "counter", lambda s: s["B"] - s["C"]) if ctr else None,
                                     "fuelledSecondsWithZeroCounterIncrementShare": round(float(np.mean([r["counter"]["fuelledZeroIncShare"] for r in ctr])), 4) if ctr else None}
    out["sensitivities"] = sens
    out["crosstabUndebouncedSeconds"] = {k: int(sum(r["crosstabRaw"][k] for r in rows)) for k in "ABCD"}
    # strata
    strata = {}
    for key in ("rpmPoll", "fuelPoll", "cohort"):
        for val in sorted({r[key] for r in rows}):
            sub = [r for r in rows if r[key] == val]
            if len(sub) >= 5:
                strata["%s=%s" % (key, val)] = {"shareRpm": q(sub, P, rpm_fn), "shareZeroFuel": q(sub, P, lambda s: s["A"] + s["B"]), "diff": q(sub, P, lambda s: s["B"] - s["C"]), "motoredKm": round(sum(r[P]["B"] for r in sub), 2)}
    out["strata"] = strata
    return out


def describe_population(out, rows):
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    seas = pd.read_csv("seasonal_drive_master.csv", low_memory=False).set_index("file")["thermal_regime"]
    p0f = set(dm.loc[dm["ev_valid"].map(lambda x: bool(x) if x == x else False), "file"])
    dts = [r["fuelDtMedS"] for r in rows]
    out["populationDescription"] = {"P0_releasedNValid": 483, "PF_nDrives": len(rows), "PF_nDays": len({r["date"] for r in rows}), "PF_dateSpan": [min(r["date"] for r in rows), max(r["date"] for r in rows)],
                                     "PF_cohortMix": {c: int(sum(1 for r in rows if r["cohort"] == c)) for c in sorted({r["cohort"] for r in rows})},
                                     "PF_rpmPollMix": {c: int(sum(1 for r in rows if r["rpmPoll"] == c)) for c in ("fast", "slow")}, "PF_fuelPollMix": {c: int(sum(1 for r in rows if r["fuelPoll"] == c)) for c in ("fast", "slow")},
                                     "PF_fuelDtMedianS_quantiles_5_50_95": [round(float(np.percentile(dts, q)), 3) for q in (5, 50, 95)],
                                     "PF_kmShareOfP0Km": None}
    return out


if __name__ == "__main__":
    import time
    t0 = time.time()
    smoke = "--smoke" in sys.argv
    if not smoke and not frozen_ok():
        raise SystemExit("refusing to run: CHANGELOG.md does not carry 'M460 spec sha256 %s'" % spec_sha())
    lock = "analyses/M460_first.lock"
    out_path = "analyses/M460_result.json"
    if not smoke:
        if os.path.exists(lock):
            raise SystemExit("the first run already exists (%s); a rerun needs a recorded deviation and keeps the first output" % lock)
        with open(lock, "w", encoding="utf-8", newline=chr(10)) as f:
            f.write(json.dumps({"specSha256": spec_sha(), "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}))
    n = int(sys.argv[sys.argv.index("--smoke") + 1]) if smoke else None
    out, rows = build(smoke_files=n)
    if rows:
        out = describe_population(out, rows)
        out = finish(out, rows)
    out["_provenance"] = {"spec": SPEC, "specSha256": spec_sha(), "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "bootstrap": {"B": B_DRAWS, "seed": SEED, "cluster": "calendar day (days with data of the population)"},
                          "rawBasis": "raw/ = sha256-verified originals (M366)", "label": "zero-logged-fuel versus RPM-defined engine-off distance share (logged / app-calculated fuel rate); descriptive; no physical claim",
                          "seconds": round(time.time() - t0)}
    path = "analyses/M460_smoke.json" if smoke else out_path
    with open(path, "w", encoding="utf-8", newline=chr(10)) as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    if not smoke:
        with open(lock, "w", encoding="utf-8", newline=chr(10)) as f:
            f.write(json.dumps({"specSha256": spec_sha(), "resultSha256": hashlib.sha256(open(out_path, "rb").read()).hexdigest()}))
    print(json.dumps({"status": out.get("status"), "nPF": out.get("nPF"), "G1": out.get("G1"), "constructValidity": out.get("constructValidity"), "seconds": round(time.time() - t0)}))
