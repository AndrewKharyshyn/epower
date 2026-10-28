#!/usr/bin/env python3
"""M531 (analyses/M531_spec.md Rev 2): day-clustered interval for the motored share of the boost-classified engine seconds above fuelStateRpmMin (the share shown beside the RPM Distribution chart).
Sibling payload key motoredShare (+ stamp); nothing else changes.

Per-drive sidecar rpm_fuel_state_sidecar.csv (tracked; keyed by the raw-file SHA-256 AND by rpm_fuel_state_sidecar.meta.json: source hash of fuel_state_row + the pipeline thresholds + RPM_HIST_EDGES; a mismatch
rebuilds all): per drive the motored / fuelled second counts in each RPM_HIST bin on the boost-verified path of compute_summary_arrays._RawAccum.add (replicated for the three columns jointly: RAW_MAP rename,
_ft time, col() ffill(limit=15) with the rpm >= 0 filter, resample('1s').mean(), ffill(limit=15), dropna(['eng_rpm','boost'])), the number of classified seconds and the unclassified seconds above the floor.
Thresholds are READ from the pipeline module constants, never retyped.
Usage: python tools/rpm_fuel_state.py [--dry-run] [--check] [--rebuild]"""
import copy, datetime, hashlib, inspect, io, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

KEY = "motoredShare"
SIDECAR = os.path.join(ROOT, "rpm_fuel_state_sidecar.csv")
META = os.path.join(ROOT, "rpm_fuel_state_sidecar.meta.json")
SPEC = "analyses/M531_spec.md"
NB, SEED = 4000, 42
FAITH_TOL_H = 0.001
MIN_DAYS_MOTORED, MAX_ZERO_DRAW = 10, 0.025       # support rule for showing an interval (Director, Rev 2 Q2)


def fuel_state_row(df, cs):
    """boost-verified path of _RawAccum.add for one drive; returns None when the drive has no time column; otherwise
    (on_boost_path, n_classified_seconds, motored counts per RPM_HIST bin, fuelled counts per RPM_HIST bin, unclassified seconds above the floor)."""
    df = df.rename(columns={k: v for k, v in cs.RAW_MAP.items() if k in df.columns})
    if "time" not in df:
        return None
    t = cs._ft(df["time"], mixed=True)
    def col(name, lo=None):
        if name not in df:
            return None
        s = pd.to_numeric(df[name], errors="coerce").ffill(limit=15)
        return s.where(s >= lo) if lo is not None else s
    cols = {"eng_rpm": col("eng_rpm", 0), "boost": col("boost"), "eng_load_calc": col("eng_load_calc")}
    g1 = pd.DataFrame({"t": t})
    for k, v in cols.items():
        g1[k] = v.values if v is not None else np.nan
    hz = g1.dropna(subset=["t"]).set_index("t").resample("1s").mean().ffill(limit=15)
    n_bins = len(cs.RPM_HIST_EDGES) - 1
    # post hoc sensitivity (auditor-found, M531 Director review): the same classification with the NATIVE-row ffill(15) skipped (grid-only ffill); counted above the floor
    g2 = pd.DataFrame({"t": t})
    for k, c in (("eng_rpm", "eng_rpm"), ("boost", "boost"), ("eng_load_calc", "eng_load_calc")):
        v = pd.to_numeric(df[c], errors="coerce") if c in df else None
        if v is not None and k == "eng_rpm":
            v = v.where(v >= 0)
        g2[k] = v.values if v is not None else np.nan
    h2 = g2.dropna(subset=["t"]).set_index("t").resample("1s").mean().ffill(limit=15)
    vbv, vm, vd = 0, 0, 0
    if h2["boost"].notna().any() and h2["eng_load_calc"].notna().any():
        s2 = h2.dropna(subset=["eng_rpm", "boost"]); b2 = s2["eng_rpm"] > cs.RPM_HIST_FUELSTATE_RPM_MIN; l2 = s2["eng_load_calc"].fillna(0)
        m2 = b2 & (s2["boost"] < cs.RPM_HIST_BOOST_MOTORED) & (l2 < cs.RPM_HIST_LOAD_MAX); f2 = b2 & (s2["boost"] >= cs.RPM_HIST_BOOST_FUELLED)
        vbv, vm, vd = 1, int(m2.sum()), int(m2.sum() + f2.sum())
    has_boost = hz["boost"].notna().any(); has_load = hz["eng_load_calc"].notna().any()
    if not (has_boost and has_load):
        return (0, 0, np.zeros(n_bins, dtype=np.int64), np.zeros(n_bins, dtype=np.int64), 0, (vbv, vm, vd))
    sub = hz.dropna(subset=["eng_rpm", "boost"])
    base = sub["eng_rpm"] > cs.RPM_HIST_FUELSTATE_RPM_MIN
    ld = sub["eng_load_calc"].fillna(0)
    mot = base & (sub["boost"] < cs.RPM_HIST_BOOST_MOTORED) & (ld < cs.RPM_HIST_LOAD_MAX)
    fue = base & (sub["boost"] >= cs.RPM_HIST_BOOST_FUELLED)
    hm = np.histogram(sub[mot]["eng_rpm"].values, bins=cs.RPM_HIST_EDGES)[0] if mot.any() else np.zeros(n_bins, dtype=np.int64)
    hf = np.histogram(sub[fue]["eng_rpm"].values, bins=cs.RPM_HIST_EDGES)[0] if fue.any() else np.zeros(n_bins, dtype=np.int64)
    return (1, int(len(sub)), hm.astype(np.int64), hf.astype(np.int64), int((base & ~mot & ~fue).sum()), (vbv, vm, vd))


def cols(n_bins):
    return ["file", "sha256", "date", "bv", "n_state", "n_unclassified", "gv_bv", "gv_m", "gv_d"] + ["m%d" % k for k in range(n_bins)] + ["f%d" % k for k in range(n_bins)]


def meta_now():
    import compute_summary_arrays as cs
    return {"fuelStateRowSourceSha256": hashlib.sha256(inspect.getsource(fuel_state_row).encode("utf-8")).hexdigest(),
            "thresholds": {"floorRpm": cs.RPM_HIST_FUELSTATE_RPM_MIN, "boostMotored": cs.RPM_HIST_BOOST_MOTORED, "boostFuelled": cs.RPM_HIST_BOOST_FUELLED, "loadMax": cs.RPM_HIST_LOAD_MAX},
            "rpmHistEdges": list(cs.RPM_HIST_EDGES)}


def build_sidecar(dm, rebuild=False):
    import compute_summary_arrays as cs
    import ah_throughput as AH
    load = AH.raw_loader()
    m = meta_now(); n_bins = len(cs.RPM_HIST_EDGES) - 1
    old = {}
    ok_meta = os.path.exists(META) and json.load(open(META, encoding="utf-8")) == m
    if os.path.exists(SIDECAR) and ok_meta and not rebuild:
        sc = pd.read_csv(SIDECAR, dtype={"sha256": str})
        if list(sc.columns) == cols(n_bins):
            old = sc.set_index("file").to_dict("index")
    rows, reparsed = [], 0
    for f, d in zip(dm["file"], dm["date"]):
        raw = load(f)
        if raw is None:
            continue
        sha = hashlib.sha256(raw).hexdigest()
        prev = old.get(f)
        if prev and prev["sha256"] == sha and str(prev["date"]) == str(d):
            rows.append({"file": f, **prev}); continue
        r = fuel_state_row(pd.read_csv(io.BytesIO(raw), low_memory=False), cs)
        if r is None:
            continue
        bv, n, hm, hf, u, gv = r
        row = {"file": f, "sha256": sha, "date": d, "bv": bv, "n_state": n, "n_unclassified": u, "gv_bv": gv[0], "gv_m": gv[1], "gv_d": gv[2]}
        row.update({"m%d" % k: int(hm[k]) for k in range(n_bins)}); row.update({"f%d" % k: int(hf[k]) for k in range(n_bins)})
        rows.append(row); reparsed += 1
    sc = pd.DataFrame(rows, columns=cols(n_bins))
    sc.to_csv(SIDECAR, index=False, lineterminator="\n")
    json.dump(m, open(META, "w", encoding="utf-8", newline="\n"), indent=1)
    return sc, reparsed


def boot(num, den, days, nb=NB, seed=SEED):
    """pooled ratio of sums and a day-clustered percentile bootstrap interval (calendar day = cluster; ratio of sums inside every draw) plus the share of draws with a zero numerator."""
    ud, inv = np.unique(np.asarray(days), return_inverse=True)
    dn = np.bincount(inv, weights=num, minlength=len(ud)); dd = np.bincount(inv, weights=den, minlength=len(ud))
    pt = float(dn.sum() / dd.sum()) if dd.sum() > 0 else float("nan")
    idx = np.random.default_rng(seed).integers(0, len(ud), (nb, len(ud)))
    ds, ns = dd[idx].sum(1), dn[idx].sum(1)
    ok = ds > 0
    r = ns[ok] / ds[ok]
    lo, hi = np.percentile(r, [2.5, 97.5])
    return pt, [float(lo), float(hi)], int(len(ud)), float((ns[ok] == 0).mean()), int((~ok).sum()), int((dn > 0).sum())


def two_stage(num, den, days, drives_idx_by_day, nb=1000, seed=SEED):
    """sensitivity only: resample days, then drives within each sampled day."""
    rng = np.random.default_rng(seed)
    ud = list(drives_idx_by_day)
    out = []
    for _ in range(nb):
        sd = rng.integers(0, len(ud), len(ud))
        nn = dd = 0.0
        for d in sd:
            ix = drives_idx_by_day[ud[d]]
            pick = ix[rng.integers(0, len(ix), len(ix))]
            nn += num[pick].sum(); dd += den[pick].sum()
        if dd > 0:
            out.append(nn / dd)
    lo, hi = np.percentile(out, [2.5, 97.5])
    return [float(lo), float(hi)]


def est(num, den, days, nb=NB):
    pt, ci, nd, zero, bad, nd_pos = boot(num, den, days, nb)
    shown = bool(nd_pos >= MIN_DAYS_MOTORED and zero < MAX_ZERO_DRAW)
    return {"pct": round(100 * pt, 4), "ci95Pct": [round(100 * ci[0], 4), round(100 * ci[1], 4)] if shown else None, "intervalShown": shown,
            "intervalNotShownReason": None if shown else "fewer than %d days with motored seconds or >= %.1f %% of draws with a zero numerator" % (MIN_DAYS_MOTORED, 100 * MAX_ZERO_DRAW),
            "bootstrapCi95PctRaw": [round(100 * ci[0], 4), round(100 * ci[1], 4)], "motoredSeconds": int(num.sum()), "classifiedSeconds": int(den.sum()), "nDrivesWithClassified": int((den > 0).sum()),
            "nDrivesWithMotored": int((num > 0).sum()), "nDays": nd, "nDaysWithMotored": nd_pos, "zeroNumeratorDrawShare": round(zero, 5), "degenerateDraws": bad}


def compute(sc, dm, A, nb=NB):
    import compute_summary_arrays as cs
    edges = list(cs.RPM_HIST_EDGES); n_bins = len(edges) - 1
    ib = [k for k in range(n_bins) if edges[k] >= cs.RPM_HIST_FUELSTATE_RPM_MIN]
    M = sc[["m%d" % k for k in range(n_bins)]].values.astype(np.int64); F = sc[["f%d" % k for k in range(n_bins)]].values.astype(np.int64)
    days = sc["date"].astype(str).values; bv = sc["bv"].values.astype(bool)
    num = M[:, ib].sum(axis=1).astype(float); den = num + F[:, ib].sum(axis=1)
    rd = A["rpmDistribution"]; out = {}
    mh, fh = rd["motored"]["hours"], rd["fuelled"]["hours"]
    dmo = [abs(round(float(M[:, k].sum()) / 3600.0, 3) - mh[k]) for k in range(n_bins)]; dfu = [abs(round(float(F[:, k].sum()) / 3600.0, 3) - fh[k]) for k in range(n_bins)]
    stored_num = sum(mh[k] for k in ib); stored_den = stored_num + sum(fh[k] for k in ib)
    # the stored headline sums the per-bin ROUNDED hours (0.001 h each): compare like with like (the exact seconds give a slightly different total)
    mine_num = round(sum(round(float(M[:, k].sum()) / 3600.0, 3) for k in ib), 3)
    mine_den = round(mine_num + sum(round(float(F[:, k].sum()) / 3600.0, 3) for k in ib), 3)
    out["faithfulness"] = {"maxAbsDiffHoursMotored": round(max(dmo), 6), "maxAbsDiffHoursFuelled": round(max(dfu), 6), "tolHours": FAITH_TOL_H,
                           "nSamplesMotored": int(M.sum()), "storedNSamplesMotored": rd["motored"]["nSamplesS"], "nSamplesFuelled": int(F.sum()), "storedNSamplesFuelled": rd["fuelled"]["nSamplesS"],
                           "nDrivesBoostVerified": int(bv.sum()), "storedNDrivesFuelState": rd["coverage"]["nDrivesFuelState"],
                           "motoredHoursAboveFloor_sumOfRoundedBinHours": mine_num, "storedMotoredHoursAboveFloor": round(stored_num, 3), "denominatorHours_sumOfRoundedBinHours": mine_den, "storedDenominatorHours": round(stored_den, 3), "exactMotoredHoursAboveFloor": round(float(num.sum()) / 3600.0, 4),
                           "passed": bool(max(dmo) <= FAITH_TOL_H and max(dfu) <= FAITH_TOL_H and int(M.sum()) == rd["motored"]["nSamplesS"] and int(F.sum()) == rd["fuelled"]["nSamplesS"]
                                          and int(bv.sum()) == rd["coverage"]["nDrivesFuelState"] and abs(mine_num - round(stored_num, 3)) <= FAITH_TOL_H and abs(mine_den - round(stored_den, 3)) <= FAITH_TOL_H)}
    m = bv                                      # only boost-verified drives contribute
    out["pooled"] = est(num[m], den[m], days[m], nb)
    cond = sc["n_unclassified"].values.astype(float)[m].sum()
    out["unclassifiedSecondsAboveFloor"] = {"seconds": int(cond), "shareOfClassifiedPlusUnclassifiedPct": round(100 * cond / (cond + den[m].sum()), 3)}
    # cohorts (the displayed share follows the shown cohort)
    reg = pd.read_csv(os.path.join(ROOT, "seasonal_drive_master.csv"), low_memory=False).set_index("file")["thermal_regime"]
    coh = sc["file"].map(reg).values
    out["cohorts"] = {c: est(num[m & (coh == c)], den[m & (coh == c)], days[m & (coh == c)], nb) for c in ("warm", "shoulder", "cold") if (m & (coh == c)).any()}
    # zero-inflation descriptives
    srt = np.sort(num[m])[::-1]
    d_u, d_inv = np.unique(days[m], return_inverse=True); dn = np.bincount(d_inv, weights=num[m], minlength=len(d_u)); dd = np.bincount(d_inv, weights=den[m], minlength=len(d_u))
    big = den[m] >= 600
    shares = num[m][big] / den[m][big]
    loo = [(dn.sum() - dn[i]) / (dd.sum() - dd[i]) for i in range(len(d_u)) if dd.sum() - dd[i] > 0]
    out["descriptives"] = {"drivesWithMotoredPct": round(100 * float((num[m] > 0).sum()) / float((den[m] > 0).sum()), 2), "nDrivesWithMotored": int((num[m] > 0).sum()),
                           "top5DrivesShareOfMotoredSecondsPct": round(100 * float(srt[:5].sum() / num[m].sum()), 2), "top5DaysShareOfMotoredSecondsPct": round(100 * float(np.sort(dn)[::-1][:5].sum() / dn.sum()), 2),
                           "perDriveShare": {"median": round(100 * float(np.median(shares)), 3), "p25": round(100 * float(np.percentile(shares, 25)), 3), "p75": round(100 * float(np.percentile(shares, 75)), 3), "nDrives": int(big.sum()), "minClassifiedSeconds": 600},
                           "leaveOneDayOutRangePct": [round(100 * min(loo), 4), round(100 * max(loo), 4)]}
    # sensitivities: polling-regime periods, canonical outliers, day-then-drive two-stage resampling
    cr = pd.read_csv(os.path.join(ROOT, "cadence_regime.csv")).set_index("file")["regime"]
    rg = sc["file"].map(cr).values
    out["pollingRegimePeriods"] = {lab: est(num[m & (rg == lab)], den[m & (rg == lab)], days[m & (rg == lab)], nb) for lab in ("slow", "fast")}
    ex = dm.set_index("file")["ens_outlier_v2"].reindex(sc["file"]).fillna(False).astype(bool).values
    out["ensOutlierV2Excluded"] = est(num[m & ~ex], den[m & ~ex], days[m & ~ex], nb)
    # resampling population sensitivity: all master days (days without a boost-verified drive add empty clusters) - reproduces the blind audit's convention
    alld = est(np.where(m, num, 0.0), np.where(m, den, 0.0), days, nb)
    out["allMasterDaysResampling"] = {"pct": alld["pct"], "ci95Pct": alld["bootstrapCi95PctRaw"], "nDays": alld["nDays"], "nDaysWithMotored": alld["nDaysWithMotored"]}
    # POST HOC, found by the blind audit: grid-only ffill (the native-row ffill(15) before the grid skipped); the pipeline convention (native ffill first) is what the stored rpmDistribution uses
    gm, gd = sc["gv_m"].values.astype(float), sc["gv_d"].values.astype(float); gb = sc["gv_bv"].values.astype(bool)
    ge = est(gm[gb], gd[gb], days[gb], nb)
    out["gridOnlyFfillSensitivity_postHoc_auditorFound"] = {"pct": ge["pct"], "ci95Pct": ge["bootstrapCi95PctRaw"], "motoredSeconds": ge["motoredSeconds"], "classifiedSeconds": ge["classifiedSeconds"], "nDrivesWithMotored": ge["nDrivesWithMotored"],
                                                            "nDaysWithMotored": ge["nDaysWithMotored"], "nDays": ge["nDays"], "note": "NOT the pipeline convention; moves the point by about 28 % and the drive count by 56"}
    byday = {}
    idxm = np.where(m & (den > 0))[0]
    for i in idxm:
        byday.setdefault(days[i], []).append(i)
    byday = {d: np.array(v) for d, v in byday.items()}
    out["twoStageDayThenDriveCi95Pct"] = [round(100 * x, 4) for x in two_stage(num, den, days, byday, nb=1000)]
    lo_, hi_ = out["pooled"]["bootstrapCi95PctRaw"]
    out["escalationRule"] = f"at later ingestions a pooled share outside [{lo_:.2f}, {hi_:.2f}] (the first-run 95 percent interval) escalates to the Director"
    tw = {}
    p = out["pooled"]
    tw["halfWidthExceedsEstimate"] = bool(p["ci95Pct"] is not None and (p["ci95Pct"][1] - p["ci95Pct"][0]) / 2 > p["pct"])
    tw["top5DrivesOver50pct"] = bool(out["descriptives"]["top5DrivesShareOfMotoredSecondsPct"] > 50)
    tw["leaveOneDayOutRangeWiderThanBootstrap"] = bool(p["ci95Pct"] is not None and (out["descriptives"]["leaveOneDayOutRangePct"][1] - out["descriptives"]["leaveOneDayOutRangePct"][0]) > (p["ci95Pct"][1] - p["ci95Pct"][0]))
    tw["cohortIntervalNotShown"] = {c: (not v["intervalShown"]) for c, v in out["cohorts"].items()}
    sl, fa = out["pollingRegimePeriods"]["slow"], out["pollingRegimePeriods"]["fast"]
    tw["slowFastPeriodsDifferBeyondCombinedIntervals"] = bool(sl["ci95Pct"] and fa["ci95Pct"] and (sl["ci95Pct"][1] < fa["ci95Pct"][0] or fa["ci95Pct"][1] < sl["ci95Pct"][0]))
    out["tripwires"] = tw
    return out


def build_block(dm, A, nb=NB, rebuild=False):
    import compute_summary_arrays as cs
    sc, reparsed = build_sidecar(dm, rebuild)
    r = compute(sc, dm, A, nb)
    sha = lambda p: hashlib.sha256(open(os.path.join(ROOT, p), "rb").read()).hexdigest()
    return {"estimand": "motored seconds / (motored + fuelled seconds) of the boost-classified 1 Hz seconds in the rpm bins with lower edge >= fuelStateRpmMin (strict eng_rpm > fuelStateRpmMin), pooled over the boost-verified drives",
            "basis": "observed share of classified seconds of app-calculated boost and engine load (thresholds read from the pipeline constants); not a direct observation of the fuel state, not an energy share; rpm exactly at the floor is excluded; raw/ = sha256-verified originals (M366)",
            "descriptive": True, "displayed": False, "thresholds": meta_now()["thresholds"], **r,
            "limits": ["hours-weighted: long drives dominate", "the polling-regime split is confounded with calendar date, season and ambient", "boost and load are app-calculated channels", "the day bootstrap does not capture serial day correlation",
                       "motored is a rare, zero-inflated state (most drives never reach it)", "unclassified seconds (boost between the two thresholds, or load at or above the maximum at motored boost) are excluded from the denominator"],
            "provenance": {"spec": SPEC, "specSha256": sha(SPEC), "toolSha256": sha("tools/rpm_fuel_state.py"), "sidecar": "rpm_fuel_state_sidecar.csv", "sidecarSha256": sha("rpm_fuel_state_sidecar.csv"),
                           "masterMd5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest(), "reparsedDrives": reparsed}}


def splice(A, blk, master_md5="", now=None):
    new = copy.deepcopy(A)
    new[KEY] = blk
    old = (A.get("_artifactStamps") or {}).get(KEY)
    if old and A.get(KEY) == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"][KEY] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M531: derived by tools/rpm_fuel_state.py from drive_master.csv, the raw drive files through rpm_fuel_state_sidecar.csv (keyed by raw sha256) and the stored rpmDistribution (faithfulness gate)",
                  upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
        import stamp_common as _sc
        new["_artifactStamps"][KEY] = _sc.carry_declared(old, st)
    ch = [k for k in set(A) | set(new) if A.get(k) != new.get(k)]
    bad = [k for k in ch if k not in (KEY, "_artifactStamps")]
    st_bad = [k for k in set(A["_artifactStamps"]) | set(new["_artifactStamps"]) if A["_artifactStamps"].get(k) != new["_artifactStamps"].get(k) and k != KEY]
    return new, ch, bad + st_bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    raw_txt = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A = json.loads(raw_txt)
    blk = build_block(dm, A, rebuild="--rebuild" in argv)
    if not blk["faithfulness"]["passed"]:
        print(json.dumps({"STOP": "faithfulness gate failed", "faithfulness": blk["faithfulness"]}))
        return 1
    if "--check" in argv:
        have = A.get(KEY)
        keep = lambda b: {k: v for k, v in (b or {}).items() if k != "provenance"}
        print(json.dumps({"check": "motoredShare", "matchesPayload": keep(have) == keep(blk)}))
        return 0 if keep(have) == keep(blk) else 1
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    new, ch, bad = splice(A, blk, md5)
    res = os.path.join("analyses", "M531_result.json")
    if not os.path.exists(res):                                    # run-once lock: the first output is kept
        json.dump(blk, open(res, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False)
    print(json.dumps({"pooled": blk["pooled"], "faithfulness": blk["faithfulness"]["passed"], "nChanged": len(ch), "outsideAllowList": bad}))
    if bad:
        return 1
    if "--dry-run" not in argv and ch:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + (chr(10) if raw_txt.endswith(chr(10)) else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
