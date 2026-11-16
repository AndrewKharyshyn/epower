"""M691 (N-11 part): does the logged actual-torque register x 256 reproduce the logged target-torque register? (spec analyses/M690_spec.md Rev 1.1)

Descriptive, payload only (block `torqueDecoder`). Both registers are logged / app-calculated PID values, never measured shaft torque.
Per-drive statistics are cached by raw sha256 (torque_decoder_cache/); aggregation never rereads raw files.
"""
import copy, datetime, hashlib, json, os, sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SPEC = "analyses/M690_spec.md"
CACHE_DIR = os.path.join(ROOT, "torque_decoder_cache")
METHOD_VERSION = 4
SCALE = 256.0
ACTIVE_MIN = 20.0            # N.m on the target register
MIN_ACTIVE = 200             # samples per eligible drive
TOLS = (3.0, 10.0)
LAGS = tuple(range(-3, 4))
SPEED_BANDS = ((0, 20), (20, 60), (60, 100), (100, 400))
TGT_BANDS = ((20, 50), (50, 100), (100, 200), (200, 1e9))
UPDATE_DATE = "2026-08-25"   # battery software update (owner statement; excluded middle of the early-late windows)
SEED, NBOOT = 42, 4000
MIN_DRIVES, MIN_DAYS, ESS_MIN = 10, 5, 10.0
PAIR_TOL_S = 0.5            # Rev 1.2: an actual row pairs with the latest preceding (or same) target row within 0.5 s
RPM_COL = "[VCM] Motor RPM (rpm)"   # the rejected PID (M102): read here only, never turned into a column or a speed
RATIO_LO, RATIO_HI = 250.0, 262.0
D2_FLOOR, D3_CEIL = 0.60, 0.05


# ------------------------------------------------------------------------------------------------ per-drive statistics
def _wmedian(x, w):
    o = np.argsort(x)
    x, w = x[o], w[o]
    c = np.cumsum(w)
    return float(x[int(np.searchsorted(c, 0.5 * c[-1]))])


def make_pairs(df, tol=PAIR_TOL_S, follow=False):
    """Rev 1.2 pairing: each actual-register row with the latest preceding (or same) row carrying a numeric target value, accepted when the time gap is at most `tol` seconds;
    each target row is used at most once; no forward fill, no interpolation, no averaging. Pair time = the actual row's timestamp."""
    ia = np.flatnonzero(df["actual"].notna().to_numpy())
    it = np.flatnonzero(df["target"].notna().to_numpy())
    empty = pd.DataFrame({"t": [], "actual": [], "target": [], "speed": [], "rpm": [], "gap": []})
    if len(ia) == 0 or len(it) == 0:
        return empty, len(ia)
    t = df["t"].to_numpy(float)
    if follow:      # sensitivity: the FOLLOWING (or same) target row
        j = np.searchsorted(it, ia, side="left")
        ok = j < len(it)
        ia2, j2 = ia[ok], j[ok]
        gap = t[it[j2]] - t[ia2]
    else:
        j = np.searchsorted(it, ia, side="right") - 1
        ok = j >= 0
        ia2, j2 = ia[ok], j[ok]
        gap = t[ia2] - t[it[j2]]
    keep = (gap >= 0) & (gap <= tol)
    ia2, j2, gap = ia2[keep], j2[keep], gap[keep]
    _, first = np.unique(j2, return_index=True)          # each target row once
    first.sort()
    ia2, j2, gap = ia2[first], j2[first], gap[first]
    return pd.DataFrame({"t": t[ia2], "actual": df["actual"].to_numpy(float)[ia2], "target": df["target"].to_numpy(float)[it[j2]],
                         "speed": df["speed"].to_numpy(float)[ia2], "rpm": df["rpm"].to_numpy(float)[ia2], "gap": gap}), len(ia)


def drive_metrics(df, tol=PAIR_TOL_S):
    """df columns: t (seconds), actual, target, speed (km/h, as-of, may be NaN), rpm (raw rejected PID, may be NaN), in log order. See make_pairs for the pairing rule."""
    n_rows = int(len(df))
    b, n_act = make_pairs(df, tol)
    out = {"nRows": n_rows, "nActualRows": int(n_act), "nPairs": int(len(b)), "nUnpairedActual": int(n_act - len(b)), "shareActualRowsPaired": round(len(b) / n_act, 4) if n_act else None,
           "medianPairGapS": round(float(b["gap"].median()), 4) if len(b) else None, "rpmRowsOnActualRowsShare": round(float(df["rpm"].notna().to_numpy()[df["actual"].notna().to_numpy()].mean()), 4) if (df["rpm"].notna().any() and df["actual"].notna().any()) else None,
           "actualPresent": bool(df["actual"].notna().any()), "targetPresent": bool(df["target"].notna().any())}
    b = b.reset_index(drop=True)
    act = b["target"].abs().to_numpy() >= ACTIVE_MIN
    out["nActive"] = int(act.sum())
    a = b["actual"].to_numpy(float)[act]
    g = b["target"].to_numpy(float)[act]
    t = b["t"].to_numpy(float)[act]
    if out["nActive"] < 1:
        return out
    z = a == 0
    out["nActiveActualZero"], out["shareActiveActualZero"] = int(z.sum()), round(float(z.mean()), 5)
    nz = ~z
    if nz.sum() >= 1:
        r = g[nz] / a[nz]
        out["ratioMedian"] = float(np.median(r))
        out["l1Slope"] = _wmedian(r, np.abs(a[nz]))
        out["oppositeSignShare"] = float(np.mean(np.sign(g[nz]) != np.sign(a[nz])))
        out["nSignScored"] = int(nz.sum())
    p99p1 = float(np.percentile(np.abs(g), 99) - np.percentile(np.abs(g), 1))
    res = SCALE * a - g
    out["tol3"], out["tol10"] = float(np.mean(np.abs(res) <= 3.0)), float(np.mean(np.abs(res) <= 10.0))
    out["tolOnePercentOfRange"] = float(np.mean(np.abs(res) <= 0.01 * p99p1)) if p99p1 > 0 else None
    # D5 register grid (first), resolution-limited label and the share expected from quantisation alone
    v = np.unique(np.round(b["actual"].to_numpy(float), 6))
    dv = np.diff(v)
    dv = dv[dv > 1e-9]
    step = float(dv.min()) if len(dv) else None
    out["actualStep"] = step
    out["resolutionLimited"] = bool(step is not None and SCALE * step > 3.0)
    out["quantisationOnlyShare3"] = round(min(1.0, 6.0 / (SCALE * step)), 4) if step else None
    # D4 timing: pair target[i] with actual[i + lag] inside the sequence of rows carrying both registers
    bt, ba, bg = b["t"].to_numpy(float), b["actual"].to_numpy(float), b["target"].to_numpy(float)
    ba_act = np.abs(bg) >= ACTIVE_MIN
    shares = {}
    for k in LAGS:
        if k >= 0:
            i0, i1 = np.arange(0, len(b) - k), np.arange(k, len(b))
        else:
            i0, i1 = np.arange(-k, len(b)), np.arange(0, len(b) + k)
        m = ba_act[i0]
        if m.sum() >= 20:
            shares[k] = float(np.mean(np.abs(SCALE * ba[i1][m] - bg[i0][m]) <= 3.0))
    if shares:
        best = max(shares, key=lambda k: (round(shares[k], 12), -abs(k)))
        dt = float(np.median(np.diff(bt))) if len(bt) > 1 else None
        out["bestLag"], out["tol3AtBestLag"], out["medianRowStepS"] = int(best), shares[best], dt
        out["bestLagSeconds"] = None if dt is None else round(best * dt, 4)
    # D6 rpm artefact (signs only): the rejected rpm PID sits on the actual-register rows; pairs with the target by the same rule; speed above 20 km/h
    if b["rpm"].notna().any():
        m = b["rpm"].notna() & (b["speed"] > 20)
        if m.sum() >= 50:
            rp, tg = b.loc[m, "rpm"].to_numpy(float), b.loc[m, "target"].to_numpy(float)
            nzs = (rp != 0) & (tg != 0)
            out["rpm"] = {"n": int(m.sum()), "negRpmShare": float(np.mean(rp < 0)), "negTargetShare": float(np.mean(tg < 0)),
                          "signAgreement": float(np.mean(np.sign(rp[nzs]) == np.sign(tg[nzs]))) if nzs.sum() else None}
    # D7 signed residual medians by speed band and by |target| band
    sp = b["speed"].to_numpy(float)[act]
    out["byBand"] = {}
    for lo, hi in SPEED_BANDS:
        mm = (sp >= lo) & (sp < hi)
        if mm.sum() >= 20:
            out["byBand"]["speed %d-%d" % (lo, min(hi, 999))] = {"n": int(mm.sum()), "medResidual": float(np.median(res[mm]))}
    for lo, hi in TGT_BANDS:
        mm = (np.abs(g) >= lo) & (np.abs(g) < hi)
        if mm.sum() >= 20:
            out["byBand"]["abs target %d-%s" % (lo, "up" if hi > 1e8 else int(hi))] = {"n": int(mm.sum()), "medResidual": float(np.median(res[mm]))}
    # D2 by pair-gap band (descriptive)
    gp = b["gap"].to_numpy(float)[act]
    out["tol3ByGapBand"] = {k: {"n": int(m.sum()), "tol3": float(np.mean(np.abs(res[m]) <= 3.0))} for k, m in (("gap<=0.1s", gp <= 0.1), ("gap>0.1s", gp > 0.1)) if m.sum() >= 20}
    return out


def _core(df, tol, follow):
    b, n_act = make_pairs(df, tol, follow)
    act = b["target"].abs().to_numpy() >= ACTIVE_MIN
    a, g = b["actual"].to_numpy(float)[act], b["target"].to_numpy(float)[act]
    r = {"nActive": int(act.sum())}
    if len(a) >= 1:
        nz = a != 0
        if nz.sum() >= 1:
            q = g[nz] / a[nz]
            r["ratioMedian"], r["l1Slope"] = float(np.median(q)), _wmedian(q, np.abs(a[nz]))
            r["oppositeSignShare"] = float(np.mean(np.sign(g[nz]) != np.sign(a[nz])))
        r["tol3"] = float(np.mean(np.abs(SCALE * a - g) <= 3.0))
    return r


def following_gap_median(df):
    """Unconstrained median time from an actual row to the next target row (a full polling cycle in the real layout)."""
    ia = np.flatnonzero(df["actual"].notna().to_numpy())
    it = np.flatnonzero(df["target"].notna().to_numpy())
    if len(ia) == 0 or len(it) == 0:
        return None
    j = np.searchsorted(it, ia, side="left")
    ok = j < len(it)
    t = df["t"].to_numpy(float)
    return float(np.median(t[it[j[ok]]] - t[ia[ok]])) if ok.any() else None


def variants(df):
    r = {"tol0.25s": _core(df, 0.25, False), "tol1.0s": _core(df, 1.0, False), "followingTarget": _core(df, PAIR_TOL_S, True)}
    r["followingTarget"]["followingGapMedianS"] = following_gap_median(df)
    return r


def extract(csv_bytes):
    sys.path.insert(0, ROOT)
    import compute_drive_summary_v6 as D
    df, t = D._prep_bytes(csv_bytes)
    raw = pd.read_csv(__import__("io").BytesIO(csv_bytes), low_memory=False, usecols=lambda c: c == RPM_COL)
    ts = (t - t.min()).dt.total_seconds().to_numpy(float) if hasattr(t, "dt") else np.asarray((t - t.min()).total_seconds(), float)
    fr = pd.DataFrame({"t": ts,
                       "actual": pd.to_numeric(df["motor_torque"], errors="coerce") if "motor_torque" in df.columns else np.nan,
                       "target": pd.to_numeric(df["target_torque"], errors="coerce") if "target_torque" in df.columns else np.nan,
                       "rpm": pd.to_numeric(raw[RPM_COL], errors="coerce").to_numpy() if RPM_COL in raw.columns else np.nan})
    spd = D._series(df, t, "speed", lo=0, hi=260)
    if spd is not None:
        base = pd.DataFrame({"t": t.values, "i": np.arange(len(df))}).sort_values("t")
        al = D._asof(base.copy(), spd, "speed", D.V_ALIGN_TOL).sort_values("i")
        fr["speed"] = al["speed"].to_numpy(float)
    else:
        fr["speed"] = np.nan
    out = drive_metrics(fr)
    out["variants"] = variants(fr)
    return out


CODE_TAG = hashlib.sha256(open(__file__, "rb").read()).hexdigest()[:8]


def _cache_path(sha):
    return os.path.join(CACHE_DIR, "%s_v%d_%s.json" % (sha, METHOD_VERSION, CODE_TAG))


def corpus_stats(raw_dir, files, verbose=False):
    import ah_throughput as AH
    sha_by, loader = AH.manifest_sha_lookup(), AH.raw_loader(raw_dir)
    os.makedirs(CACHE_DIR, exist_ok=True)
    out, nnew = {}, 0
    for f in files:
        by = loader(f)
        if by is None:
            out[f] = {"reason": "raw_missing"}
            continue
        sha = sha_by(f) or hashlib.sha256(by).hexdigest()
        cp = _cache_path(sha)
        if os.path.isfile(cp):
            r = json.load(open(cp, encoding="utf-8"))
        else:
            r = {"sha": sha, "extractorVersion": METHOD_VERSION, "codeTag": CODE_TAG, **extract(by)}
            json.dump(r, open(cp, "w", encoding="utf-8"), separators=(",", ":"))
            nnew += 1
        out[f] = r
    if verbose:
        print(json.dumps({"extractedNew": nnew, "files": len(out)}))
    return out


# ------------------------------------------------------------------------------------------------ aggregation (no raw access)
def ess(w):
    w = np.asarray(w, float)
    s = w / w.sum() if w.sum() > 0 else w
    return float(1.0 / np.sum(s ** 2)) if w.sum() > 0 else 0.0


def day_boot(vals, days, nboot=NBOOT, seed=SEED):
    """Median over all drives in the resampled days; percentile interval, calendar-day cluster."""
    vals, days = np.asarray(vals, float), np.asarray(days)
    ud = np.unique(days)
    idx = {d: np.where(days == d)[0] for d in ud}
    rng = np.random.default_rng(seed)
    draws = np.empty(nboot)
    for b in range(nboot):
        pick = rng.integers(0, len(ud), len(ud))
        draws[b] = np.median(np.concatenate([vals[idx[ud[k]]] for k in pick]))
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return [round(float(lo), 5), round(float(hi), 5)]


def _status(nd, ndays, e):
    return "not shown" if (nd < MIN_DRIVES or ndays < MIN_DAYS) else ("exploratory" if e < ESS_MIN else "supported")


def est(rows, key, nboot=NBOOT):
    r = [x for x in rows if x.get(key) is not None]
    if not r:
        return {"n": 0}
    v = np.array([x[key] for x in r], float)
    d = np.array([x["date"] for x in r])
    wd = {}
    for x in r:
        wd[x["date"]] = wd.get(x["date"], 0) + x["nActive"]
    ci = day_boot(v, d, nboot) if len(set(d)) >= 2 else None
    return {"estimate": round(float(np.median(v)), 5), "ci95": ci, "nDrives": len(r), "nDays": len(wd), "essDays": round(ess(list(wd.values())), 3), "status": _status(len(r), len(wd), ess(list(wd.values())))}


def decide(d1r, d1s, d2, d3, res_limited):
    inside = lambda b: bool(b is not None and b[0] >= RATIO_LO and b[1] <= RATIO_HI)
    d1 = inside(d1r.get("ci95")) and inside(d1s.get("ci95"))
    out = {"d1Passed": d1, "d1RatioContains256": bool(d1r.get("ci95") and d1r["ci95"][0] <= SCALE <= d1r["ci95"][1]), "d1SlopeContains256": bool(d1s.get("ci95") and d1s["ci95"][0] <= SCALE <= d1s["ci95"][1])}
    d2lo = d2.get("ci95", [None])[0] if d2.get("ci95") else None
    d3hi = d3.get("ci95", [None, None])[1] if d3.get("ci95") else None
    out["d2LowerBoundPassed"] = bool(d2lo is not None and d2lo >= D2_FLOOR)
    out["d3UpperBoundPassed"] = bool(d3hi is not None and d3hi <= D3_CEIL)
    pt = bool(d2.get("estimate") is not None and d2["estimate"] >= D2_FLOOR and d3.get("estimate") is not None and d3["estimate"] <= D3_CEIL)
    if not d1:
        s = "not consistent"
    elif out["d2LowerBoundPassed"] and out["d3UpperBoundPassed"]:
        s = "decoder consistent with x256"
    elif pt:
        s = "tolerance not established"
    else:
        s = "scale consistent, tolerance weak"
    out["status"] = s
    out["resolutionLimited"] = bool(res_limited)
    return out


def aggregate(stats, master, cad, pidc, nboot=NBOOT):
    rows = []
    for _, m in master.iterrows():
        r = stats.get(m["file"])
        if not r or r.get("reason") or not r.get("actualPresent") or not r.get("targetPresent"):
            continue
        rows.append({**r, "file": m["file"], "date": str(m["date"])[:10], "clean": bool(m["clean"]), "regime": cad.get(m["file"]), "pidClass": pidc.get(m["file"])})
    miss = master[master["file"].map(lambda f: not (stats.get(f) or {}).get("actualPresent"))]
    elig = [x for x in rows if x["clean"] and x.get("nActive", 0) >= MIN_ACTIVE and x.get("l1Slope") is not None]
    block = {"label": "logged actual-torque register x 256 against the logged target-torque register (descriptive; both registers are logged / app-calculated PID values and are not shaft-torque readings)", "spec": SPEC, "status": "exploratory",
             "population": {"nMasterDrives": int(len(master)), "nWithActualRegister": len(rows), "nMissingActualRegister": int(len(miss)), "nCanonicalClean": int(sum(1 for x in rows if x["clean"])),
                            "nEligible": len(elig), "nExcludedFewActive": int(sum(1 for x in rows if x["clean"] and x.get("nActive", 0) < MIN_ACTIVE)),
                            "excludedOverAllDrivesWithRegisters": {"nDrivesWithRegisters": len(rows), "nClean": int(sum(1 for x in rows if x["clean"])), "nNonClean": int(sum(1 for x in rows if not x["clean"])),
                                                                   "eligible": len(elig), "cleanExcludedFewActivePairs": int(sum(1 for x in rows if x["clean"] and x.get("nActive", 0) < MIN_ACTIVE)),
                                                                   "nonCleanExcluded": int(sum(1 for x in rows if not x["clean"])), "eligibleIncludesNonCleanDrives": False,
                                                                   "identity": "eligible + cleanExcludedFewActivePairs + nonCleanExcluded = nDrivesWithRegisters (a clean drive with an active pair but actual = 0 throughout would add a separate exclusion; none occurs)"}, "scope": "holds only for samples with |target| >= 20 N.m; low-load behaviour is not shown",
                            "rowFormation": "Rev 1.2: each actual-register row paired with the latest preceding (or same) target-register row within 0.5 s, each target row used once; no forward fill, no interpolation, no averaging (the two PIDs are logged on adjacent rows, never on one row)",
                            "medianShareOfActualRowsPaired": round(float(np.median([x["shareActualRowsPaired"] for x in elig])), 4) if elig else None}}
    if not elig:
        block["decision"] = {"status": "no eligible drives"}
        return block
    D1r, D1s = est(elig, "ratioMedian", nboot), est(elig, "l1Slope", nboot)
    D2, D2_10, D2_pct, D3 = est(elig, "tol3", nboot), est(elig, "tol10", nboot), est(elig, "tolOnePercentOfRange", nboot), est(elig, "oppositeSignShare", nboot)
    steps = [x["actualStep"] for x in elig if x.get("actualStep")]
    medstep = float(np.median(steps)) if steps else None
    reslim = bool(medstep is not None and SCALE * medstep > 3.0)
    block["D1_scale"] = {"ratioMedian": D1r, "l1SlopeThroughOrigin": D1s, "shareActiveActualZero": round(float(np.median([x["shareActiveActualZero"] for x in elig])), 5),
                         "note": "ratio statistic excludes active samples with actual = 0 (their share is shown)"}
    block["D2_tolerance"] = {"within3Nm_lag0": D2, "within10Nm_lag0": D2_10, "withinOnePercentOfRange_lag0": D2_pct, "resolutionLimited": reslim,
                             "quantisationOnlyShare3": round(float(np.median([x["quantisationOnlyShare3"] for x in elig if x.get("quantisationOnlyShare3") is not None])), 4) if reslim else None}
    block["D3_sign"] = {"oppositeSignShare": D3, "note": "samples with actual = 0 are excluded and counted in D1"}
    lagrows = [x for x in elig if x.get("bestLag") is not None]
    block["D4_timing"] = {"nDrives": len(lagrows), "shareOfDrivesBestLagNotZero": round(float(np.mean([x["bestLag"] != 0 for x in lagrows])), 4) if lagrows else None,
                          "tol3AtBestLagMedian": round(float(np.median([x["tol3AtBestLag"] for x in lagrows])), 5) if lagrows else None,
                          "tol3AtLag0Median": D2.get("estimate"), "bestLagSecondsMedianByCadence": {k: (round(float(np.median([x["bestLagSeconds"] for x in lagrows if x["regime"] == k and x.get("bestLagSeconds") is not None])), 4) if any(x["regime"] == k and x.get("bestLagSeconds") is not None for x in lagrows) else None) for k in ("fast", "slow")},
                          "note": "descriptive; the status uses lag 0 only"}
    block["D5_registerGrid"] = {"medianActualStep": medstep, "step256": None if medstep is None else round(SCALE * medstep, 4), "resolutionLimited": reslim}
    rp = [x["rpm"] for x in elig if x.get("rpm")]
    block["D6_rpmArtefactSigns"] = {"nDrives": len(rp), "medianNegRpmShare": round(float(np.median([x["negRpmShare"] for x in rp])), 5) if rp else None,
                                    "medianNegTargetShare": round(float(np.median([x["negTargetShare"] for x in rp])), 5) if rp else None,
                                    "medianSignAgreement": round(float(np.median([x["signAgreement"] for x in rp if x["signAgreement"] is not None])), 5) if rp else None,
                                    "sensitivityAllDrivesMeetingCondition": {"nDrives": len([x for x in rows if x.get("rpm")]), "medianNegRpmShare": round(float(np.median([x["rpm"]["negRpmShare"] for x in rows if x.get("rpm")])), 5) if any(x.get("rpm") for x in rows) else None,
                                                                           "medianNegTargetShare": round(float(np.median([x["rpm"]["negTargetShare"] for x in rows if x.get("rpm")])), 5) if any(x.get("rpm") for x in rows) else None,
                                                                           "medianSignAgreement": round(float(np.median([x["rpm"]["signAgreement"] for x in rows if x.get("rpm") and x["rpm"]["signAgreement"] is not None])), 5) if any(x.get("rpm") for x in rows) else None,
                                                                           "population": "every drive with the rpm PID and at least 50 pairs above 20 km/h, clean or not, with or without 200 active pairs"},
                                    "population": "primary = eligible drives; the all-drives variant is a sensitivity (clarification of the spec)",
                                    "note": "agreement of signs between the rejected rpm PID and the target register above 20 km/h; the rpm PID is not a speed and the M102 rejection is unchanged; read inside this tool only"}
    def grp(keyf):
        out = {}
        for k in sorted({keyf(x) for x in elig if keyf(x) is not None}):
            g = [x for x in elig if keyf(x) == k]
            wd = {}
            for x in g:
                wd[x["date"]] = wd.get(x["date"], 0) + x["nActive"]
            out[str(k)] = {"nDrives": len(g), "nDays": len(wd), "essDays": round(ess(list(wd.values())), 3), "status": _status(len(g), len(wd), ess(list(wd.values()))), "tol3Median": round(float(np.median([x["tol3"] for x in g])), 5), "oppositeSignMedian": round(float(np.median([x["oppositeSignShare"] for x in g])), 5),
                           "ratioMedian": round(float(np.median([x["ratioMedian"] for x in g])), 3)}
        return out
    block["D7_residualByBand"] = {}
    for key in sorted({k for x in elig for k in x.get("byBand", {})}):
        v = [x["byBand"][key]["medResidual"] for x in elig if key in x.get("byBand", {}) and x["byBand"][key]["n"] >= 20]
        if v:
            block["D7_residualByBand"][key] = {"nDrives": len(v), "medianOfDriveMedianResidualNm": round(float(np.median(v)), 3), "note": "signed residual 256 x actual - target, N.m (descriptive)"}
    block["splits"] = {"byCadence": grp(lambda x: x["regime"] if isinstance(x["regime"], str) else None), "byPidSetClass": grp(lambda x: x["pidClass"]), "bySoftwareUpdate": grp(lambda x: "before 2026-08-25" if x["date"] < UPDATE_DATE else "from 2026-08-25"),
                       "byMonth": grp(lambda x: x["date"][:7]), "note": "descriptive; no contrast drawn between strata"}
    block["decision"] = decide(D1r, D1s, D2, D3, reslim)
    var = {}
    for vk in ("tol0.25s", "tol1.0s", "followingTarget"):
        rr = [{**x["variants"][vk], "date": x["date"], "nActive": x["variants"][vk]["nActive"]} for x in elig if x.get("variants") and vk in x["variants"] and x["variants"][vk].get("l1Slope") is not None and x["variants"][vk]["nActive"] >= MIN_ACTIVE]
        if len(rr) >= MIN_DRIVES:
            v1r, v1s, v2, v3 = est(rr, "ratioMedian", nboot), est(rr, "l1Slope", nboot), est(rr, "tol3", nboot), est(rr, "oppositeSignShare", nboot)
            var[vk] = {"nDrives": len(rr), "ratioMedian": v1r, "l1Slope": v1s, "tol3": v2, "oppositeSignShare": v3, "decision": decide(v1r, v1s, v2, v3, reslim)["status"]}
    fg = [x["variants"]["followingTarget"].get("followingGapMedianS") for x in elig if x.get("variants") and x["variants"].get("followingTarget", {}).get("followingGapMedianS") is not None]
    notest = {}
    if "followingTarget" not in var:
        notest["followingTarget"] = "untested (no pairs within 0.5 s for almost every drive): the next target row lies a full polling cycle after the actual row (median %.2f s over drives), so the adjacent preceding-target pair is the within-cycle pair and the following-target pairing is not estimable under the 0.5 s tolerance" % (float(np.median(fg)) if fg else float("nan"))
    block["sensitivities"] = {"variants": var, "notEstimable": notest, "descriptiveOnly": "never changes the status; a different status is reported as method disagreement",
                              "statusDisagreement": bool(any(v["decision"] != block["decision"]["status"] for v in var.values())),
                              "tol3ByPairGapBand": {k: {"nDrives": len([x for x in elig if k in (x.get("tol3ByGapBand") or {})]),
                                                        "medianTol3": round(float(np.median([x["tol3ByGapBand"][k]["tol3"] for x in elig if k in (x.get("tol3ByGapBand") or {})])), 5)}
                                                    for k in ("gap<=0.1s", "gap>0.1s") if any(k in (x.get("tol3ByGapBand") or {}) for x in elig)}}
    block["pairGeometry"] = {"medianPairGapS": round(float(np.median([x["medianPairGapS"] for x in elig if x.get("medianPairGapS") is not None])), 4), "medianUnpairedActualRows": float(np.median([x["nUnpairedActual"] for x in elig])),
                             "medianRpmRowsOnActualRowsShare": round(float(np.median([x["rpmRowsOnActualRowsShare"] for x in elig if x.get("rpmRowsOnActualRowsShare") is not None])), 4) if any(x.get("rpmRowsOnActualRowsShare") is not None for x in elig) else None,
                             "timestampOnlyGeometryFile": "analyses/M691_pair_geometry.json (committed before the first torque statistic)", "wording": "paired adjacent log rows (target logged before actual, median gap given above); the row order shows the logger polling sequence, not a causal response"}
    block["decision"]["rule"] = "D1: both the ratio-scale and the L1-slope interval lie entirely within [250, 262]; D2 (within 3 N.m, lag 0): interval lower bound >= 0.60; D3: interval upper bound <= 0.05; a point value that passes with a failing bound gives 'tolerance not established'"
    block["decision"]["externalFiguresKnownWhenThresholdsSet"] = True
    block["decision"]["scaleWindow"] = [RATIO_LO, RATIO_HI]
    block["decision"]["contains256"] = bool(block["decision"]["d1RatioContains256"] and block["decision"]["d1SlopeContains256"])
    block["decision"]["empiricalScale"] = {"ratioMedian": D1r["estimate"], "ratioCi95": D1r["ci95"], "l1Slope": D1s["estimate"], "l1SlopeCi95": D1s["ci95"],
                                           "offsetFrom256Percent": round(100.0 * (D1r["estimate"] / SCALE - 1.0), 2)}
    block["decision"]["statementWhenWindowPassesButExcludes256"] = "within the pre-registered window around x256; the scale interval excludes 256 (about %+.1f %%)" % (100.0 * (D1r["estimate"] / SCALE - 1.0))
    block["decision"]["windowEvidence"] = "the window [250, 262] was set while an external scale figure was already known, so a pass of D1 is weak evidence; the pre-registered status string is kept as it is"
    block["externalComparison"] = {"policy": "external audit figures are known-answer targets and are never typed into the repository; the comparison is qualitative",
                                   "scale": "agrees with the external audit scale within the pre-registered window",
                                   "toleranceShareAt3Nm": "lower than the external audit share (reported as a disagreement); this statistic is resolution-limited (see D5) and mixes scale offset with torque change inside a pair gap",
                                   "negativeRpmShareAbove20kmh": "D6 reports it per drive over the eligible drives (primary) and over all drives meeting the condition (sensitivity); the external statistic is over all samples above 20 km/h and is not a drive median"}
    block["reading"] = ["both registers are logged / app-calculated PID values; the status says only that the logged actual-torque register x 256 does or does not track the logged target-torque register with the stated residual; neither register is a shaft-torque reading",
                        "holds only for |target| >= 20 N.m; the thresholds were set with the external audit figures known; the spec hash is recorded in the CHANGELOG before the first run",
                        "the rejected rpm PID is used for sign agreement only; it is not a motor speed and the M102 rejection is unchanged",
                        "strata (cadence, PID-set class, software-update period, month) are reported side by side with no contrast; no article figure"]
    dd = block["decision"]
    if not (dd["d1RatioContains256"] and dd["d1SlopeContains256"]):
        block["reading"].append("the scale intervals (ratio %s, L1 slope %s) lie within the pre-registered window [250, 262] but do not contain 256: the logged actual-torque register x 256 sits about %.1f %% below the logged target on adjacent-row pairs; the status is the window rule, not equality with 256" % (D1r["ci95"], D1s["ci95"], 100.0 * (D1r["estimate"] / SCALE - 1.0)))
    if reslim:
        block["reading"].append("the within-3-N.m share is resolution-limited: 256 x the actual-register step exceeds 3 N.m, so agreement at 3 N.m is partly set by the register grid (see D5); the 10 N.m share is the grid-robust reading")
    block["reading"].append("D2 at lag 0 is the tolerance share on adjacent-row pairs and mixes scale agreement with how much the torque changes within one pair gap; the row order shows the logger polling sequence, not a causal response")
    return block


def load_master():
    m = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), usecols=["file", "date", "ens_outlier_v2", "ens_invalid"], low_memory=False)
    m["clean"] = ~(m["ens_outlier_v2"].map(lambda x: x is True or x == "True") | m["ens_invalid"].map(lambda x: x is True or x == "True"))
    c = pd.read_csv(os.path.join(ROOT, "cadence_regime.csv"))
    cad = {r.file: (r.regime if isinstance(r.regime, str) else None) for r in c.itertuples()}
    p = pd.read_csv(os.path.join(ROOT, "pid_epoch.csv"))
    pidc = {r.file: r.pidSetClass for r in p.itertuples()}
    return m, cad, pidc


def stamp(A, md5):
    import stamp_common as _sc
    old = (A.get("_artifactStamps") or {}).get("torqueDecoder")
    st = copy.deepcopy(A["_artifactStamps"]["headroomUtilization"]) if "headroomUtilization" in A.get("_artifactStamps", {}) else {}
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for k in ("carriedForward", "recomputeMode", "corpusSizeAtRecompute"):
        st.pop(k, None)
    st.update(corpusHash=md5, generatedAt=now, computationStatus="computed", upstreamHashes={"driveMasterMd5": md5},
              computationStatusNote="M691: derived by tools/torque_decoder.py from raw drive CSVs (cached by sha256), drive_master.csv, cadence_regime.csv and pid_epoch.csv (spec analyses/M690_spec.md Rev 1.1); descriptive")
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A["_artifactStamps"]["torqueDecoder"] = _sc.carry_declared(old, st)


def splice(A, block, md5):
    """Adds the block and its stamp; asserts nothing else changed (isolation guard)."""
    old = copy.deepcopy(A)
    A["torqueDecoder"] = block
    stamp(A, md5)
    chk = copy.deepcopy(A); chk.pop("torqueDecoder"); chk["_artifactStamps"].pop("torqueDecoder")
    o2 = copy.deepcopy(old); o2.pop("torqueDecoder", None); o2.setdefault("_artifactStamps", {}).pop("torqueDecoder", None)
    assert chk == o2, "unexpected change outside /torqueDecoder"
    return A


def main(argv):
    sys.path.insert(0, ROOT)
    sys.path.insert(0, HERE)
    raw_dir = argv[argv.index("--raw-dir") + 1] if "--raw-dir" in argv else (os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    master, cad, pidc = load_master()
    stats = corpus_stats(raw_dir, sorted(master["file"]), verbose=True)
    nb = 400 if "--dry-run" in argv else NBOOT
    block = aggregate(stats, master, cad, pidc, nb)
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    block["provenance"] = {"masterMd5": md5, "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "specSha256Rev1_1": "d0a261e96e7d7efab4c1855c9a9d20e8b9f29c4f8a8ee74257b25d367e7888af", "specSha256Rev1_2": "13f2f9fb9d9a3baf565f0fa6ef6fe30a73cc19c17e6fa4e3480e4a24dd9d91b8", "seed": SEED, "nBoot": nb}
    if "--out" in argv:
        json.dump(block, open(argv[argv.index("--out") + 1], "w", encoding="utf-8"), indent=1)
        print("wrote block")
        return
    if "--dry-run" in argv:
        print(json.dumps({k: block.get(k) for k in ("population", "D1_scale", "D2_tolerance", "D3_sign", "decision")}, default=str)[:3500])
        return
    p = os.path.join(ROOT, "summary_arrays.json")
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    A = splice(A, block, md5)
    open(p, "w", encoding="utf-8", newline="").write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print(json.dumps({"changed": True}))


if __name__ == "__main__":
    main(sys.argv[1:])
