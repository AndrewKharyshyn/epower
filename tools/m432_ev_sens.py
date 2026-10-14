#!/usr/bin/env python3
"""M432 (spec analyses/M432_spec.md Rev 2 + 2.1, external audit F04): detector-sensitivity range for the engine-off distance share (evTraction.evPctDistance).

  python tools/m432_ev_sens.py run --out analyses/M432_result.json [--workers 5] [--raw-dir raw_only]

Per drive the engine-state detector of compute_drive_summary_v6._ev_metrics is re-run under declared variants of the RPM threshold T, the RPM alignment (direction and tolerance), the debounce B and the coverage gate G;
the speed alignment, the integrated distance, the odometer scale k and the distance denominator are held at the RELEASED values (only the engine-state detector varies). Unknown RPM seconds are never off:
the debounce input is `known & (rpm <= T)` (unknown counts as ON inside the debounce, the first run is exempt) and `& known` is applied afterwards, exactly as released.
Reported per variant (percentage points, adding up to share_v(P_v) - S0): support lost = share_0(C_v) - S0; detector effect Delta_v = share_v(C_v) - share_0(C_v) (paired, drives valid under both); support gained = share_v(P_v) - share_v(C_v).
The range is deterministic, never merged with the day-clustered sampling interval of the released share. drive_master.csv and the raw files are only read."""
import argparse, gzip, hashlib, itertools, json, os, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd

THRESHOLDS = (100, 200, 400, 800)
DEBOUNCES = (0, 2, 3, 5, 10)
CORE_B = (0, 2, 3, 5)
GATES = (0.90, 0.95, 0.98)
# alignment id -> (direction, tolerance in seconds); backward / forward are at MATCHED window width to the nearest tolerance A (one-sided tolerance 2A)
ALIGN = {"n0.5": ("nearest", 0.5), "n1.0": ("nearest", 1.0), "n1.5": ("nearest", 1.5), "n3.0": ("nearest", 3.0),
         "b2.0": ("backward", 2.0), "b3.0": ("backward", 3.0), "b6.0": ("backward", 6.0),
         "f2.0": ("forward", 2.0), "f3.0": ("forward", 3.0), "f6.0": ("forward", 6.0)}
CORE_A = {"nearest": {"1.0": "n1.0", "1.5": "n1.5", "3.0": "n3.0"}, "backward": {"1.0": "b2.0", "1.5": "b3.0", "3.0": "b6.0"}, "forward": {"1.0": "f2.0", "1.5": "f3.0", "3.0": "f6.0"}}
S0 = ("n3.0", 400, 3, 0.95)
POLL_MAX_S, MIN_DIST_KM, K_LO, K_HI = 2.0, 1.0, 0.90, 1.10
COMPARABLE_MIN = 0.90


# ------------------------------------------------------------------ pure pieces (importable by the known-answer tests)
def align_rpm(grid_t, eng, direction, tol_s):
    """RPM aligned to the 1 Hz grid by merge_asof; NaN = no sample inside the tolerance (UNKNOWN)."""
    g = pd.DataFrame({"t": pd.DatetimeIndex(grid_t).astype("datetime64[ns]")})
    e = eng[["t", "v"]].rename(columns={"v": "rpm"}).copy()
    e["t"] = pd.DatetimeIndex(e["t"]).astype("datetime64[ns]")
    m = pd.merge_asof(g, e, on="t", direction=direction, tolerance=pd.Timedelta(seconds=float(tol_s)))
    return m["rpm"].to_numpy(float)


def debounce(state, n):
    """Identical to compute_drive_summary_v6._ev_debounce on a boolean array: runs shorter than n samples take the previous state; the first run is exempt."""
    s = np.asarray(state).astype(np.int8).copy()
    if n <= 0 or len(s) == 0:
        return s.astype(bool)
    chg = np.flatnonzero(np.diff(s)) + 1
    for a, b in zip(np.r_[0, chg], np.r_[chg, len(s)]):
        if (b - a) < n and a > 0:
            s[a:b] = s[a - 1]
    return s.astype(bool)


def off_state(rpm, thr, deb):
    known = ~np.isnan(rpm)
    return debounce(known & (np.nan_to_num(rpm, nan=0.0) <= thr), deb) & known


def ev_from_arrays(rpm, dkm, kk, thr, deb):
    off = off_state(rpm, thr, deb)
    return float(dkm[off].sum() * kk), int(off.sum())


def drive_inputs(csv_bytes):
    """Everything about one drive that does not depend on the detector variant (the front half of _ev_metrics): grid, speed-based distance per second, scale k, coverage of speed, RPM poll."""
    import compute_drive_summary_v6 as v6
    df, t = v6._prep_bytes(csv_bytes)
    eng = v6._series(df, t, "eng_rpm", lo=0)
    spd = v6._series(df, t, "speed", lo=0, hi=260)
    if spd is None or len(spd) < 20:
        spd = v6._series(df, t, "speed_obd", lo=0, hi=260)
    if eng is None or spd is None or len(eng) < 20:
        return None
    tv = t.dropna()
    if len(tv) < 10:
        return None
    grid_t = pd.date_range(tv.min(), tv.max(), freq="1s")
    if len(grid_t) < 10:
        return None
    tol = pd.Timedelta(v6.ENG_ALIGN_TOL)
    gs = pd.merge_asof(pd.DataFrame({"t": grid_t}), spd.rename(columns={"v": "speed"}), on="t", direction="nearest", tolerance=tol)
    v = gs["speed"].fillna(0.0).to_numpy(float)
    dkm = v / 3600.0
    dist_int = float(dkm.sum())
    odo = v6._series(df, t, "odo")
    dist_odo = float(odo["v"].max() - odo["v"].min()) if odo is not None and len(odo) else np.nan
    k = (dist_odo / dist_int) if (dist_int > 0 and np.isfinite(dist_odo) and dist_odo > 0) else np.nan
    return {"grid_t": grid_t, "eng": eng, "dkm": dkm, "kk": float(k) if np.isfinite(k) else 1.0, "k": float(k) if np.isfinite(k) else np.nan, "distOdo": dist_odo,
            "covSpeed": round(float(gs["speed"].notna().mean()), 4), "pollS": round(float(eng["t"].diff().dt.total_seconds().median()), 2), "nGrid": int(len(grid_t))}


def gate_ok(inp, cov_rpm, gate):
    """The released ev_valid conditions with the coverage gate G (RPM and speed) as a parameter."""
    return bool(cov_rpm >= gate and inp["covSpeed"] >= gate and inp["pollS"] <= POLL_MAX_S and np.isfinite(inp["distOdo"]) and inp["distOdo"] >= MIN_DIST_KM
                and np.isfinite(inp["k"]) and K_LO <= inp["k"] <= K_HI)


def drive_variants(csv_bytes, aligns=ALIGN):
    inp = drive_inputs(csv_bytes)
    if inp is None:
        return None
    out = {"nGrid": inp["nGrid"], "covSpeed": inp["covSpeed"], "pollS": inp["pollS"], "distOdo": inp["distOdo"], "k": inp["k"], "cov": {}, "ev": {}, "valid95": {}}
    for aid, (direction, tol_s) in aligns.items():
        rpm = align_rpm(inp["grid_t"], inp["eng"], direction, tol_s)
        cov = round(float((~np.isnan(rpm)).mean()), 4)
        out["cov"][aid] = cov
        for thr in THRESHOLDS:
            for deb in DEBOUNCES:
                km, ts = ev_from_arrays(rpm, inp["dkm"], inp["kk"], thr, deb)
                out["ev"]["%s|%d|%d" % (aid, thr, deb)] = (km, ts)         # full precision: the parity gate rounds once, like the released column
    return out


def _worker(args):
    fn, path = args
    try:
        with open(path, "rb") as f:
            r = drive_variants(f.read())
    except Exception as e:                       # reported, never silent
        return fn, {"error": "%s: %s" % (type(e).__name__, str(e)[:120])}
    return fn, r


# ------------------------------------------------------------------ aggregation
def _as_bool(s):
    return s.map(lambda x: x is True or str(x).strip().lower() == "true").astype(bool)


class Study:
    def __init__(self, dm, per_drive):
        self.dm = dm.reset_index(drop=True)
        n = len(self.dm)
        self.files = list(self.dm["file"])
        self.dist = pd.to_numeric(self.dm["distance_km"], errors="coerce").fillna(0.0).to_numpy(float)
        self.ens = _as_bool(self.dm["ens_outlier_v2"]).to_numpy(bool)
        self.rel_valid = _as_bool(self.dm["ev_valid"]).to_numpy(bool)
        self.days = np.array([str(d) for d in self.dm["date"]])
        self.has = np.array([isinstance(per_drive.get(f), dict) and "ev" in per_drive[f] for f in self.files])
        keys = ["%s|%d|%d" % (a, t, b) for a in ALIGN for t in THRESHOLDS for b in DEBOUNCES]
        self.EV = {k: np.full(n, np.nan) for k in keys}
        self.ET = {k: np.full(n, np.nan) for k in keys}
        self.COV = {a: np.full(n, np.nan) for a in ALIGN}
        self.base_ok = np.zeros(n, bool)
        self.nGrid = np.zeros(n)
        self.covSpeed = np.full(n, np.nan)
        for i, f in enumerate(self.files):
            r = per_drive.get(f)
            if not (isinstance(r, dict) and "ev" in r):
                continue
            self.nGrid[i] = r["nGrid"]
            self.base_ok[i] = bool(r["pollS"] <= POLL_MAX_S and np.isfinite(r["distOdo"]) and r["distOdo"] >= MIN_DIST_KM and np.isfinite(r["k"]) and K_LO <= r["k"] <= K_HI)
            self.covSpeed[i] = r["covSpeed"]
            for a, c in r["cov"].items():
                self.COV[a][i] = c
            for k, (km, ts) in r["ev"].items():
                self.EV[k][i], self.ET[k][i] = km, ts

    def valid(self, aid, gate):
        return self.has & self.base_ok & (np.nan_to_num(self.COV[aid], nan=-1) >= gate) & (np.nan_to_num(self.covSpeed, nan=-1) >= gate)

    def share(self, mask, key):
        d = self.dist[mask].sum()
        return float(100.0 * np.nansum(self.EV[key][mask]) / d) if d > 0 else float("nan")

    def pieces(self, aid, thr, deb, gate):
        k0 = "%s|%d|%d" % (S0[0], S0[1], S0[2])
        kv = "%s|%d|%d" % (aid, thr, deb)
        P0 = self.rel_valid & ~self.ens
        Pv = self.valid(aid, gate) & ~self.ens
        C = P0 & Pv
        s0 = self.share(P0, k0)
        out = {"nValidOwn": int(Pv.sum()), "nCommon": int(C.sum()), "nReleased": int(P0.sum()),
               "kmCommon": float(self.dist[C].sum()), "kmReleased": float(self.dist[P0].sum())}
        out["nCommonPct"] = round(100.0 * out["nCommon"] / out["nReleased"], 1)
        out["kmCommonPct"] = round(100.0 * out["kmCommon"] / out["kmReleased"], 1)
        out["daysKept"] = int(len(set(self.days[C]))); out["daysReleased"] = int(len(set(self.days[P0])))
        out["supportLostPp"] = self.share(C, k0) - s0
        out["detectorPp"] = self.share(C, kv) - self.share(C, k0)
        out["supportGainedPp"] = self.share(Pv, kv) - self.share(C, kv)
        out["totalPp"] = self.share(Pv, kv) - s0
        out["ownSharePct"] = self.share(Pv, kv)
        ng = self.nGrid[Pv]
        out["unknownRpmShare"] = float(np.nansum(ng * (1 - self.COV[aid][Pv])) / ng.sum()) if ng.sum() > 0 else float("nan")
        out["comparable"] = bool(out["nCommon"] >= COMPARABLE_MIN * out["nReleased"] and out["kmCommon"] >= COMPARABLE_MIN * out["kmReleased"])
        return out, C, Pv


def _r(x, d=4):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), d)


def build_result(study, b=4000, seed=42):
    import day_bootstrap as DB
    k0 = "%s|%d|%d" % (S0[0], S0[1], S0[2])
    P0 = study.rel_valid & ~study.ens
    s0 = study.share(P0, k0)
    # released share and its day-clustered sampling interval
    df0 = pd.DataFrame({"date": study.days[P0], "num": study.EV[k0][P0], "den": study.dist[P0]})
    ci0, used = DB.ratio_boot_ci_detail(df0, "num", "den", scale=100.0, nb=b, seed=seed, day_col="date")
    dayden = df0.groupby("date")["den"].sum().to_numpy()
    released = {"nValid": int(P0.sum()), "kmValid": _r(study.dist[P0].sum(), 1), "evKm": _r(np.nansum(study.EV[k0][P0]), 1), "evPctDistance": _r(s0, 1), "sharePct": _r(s0, 3),
                "samplingCi95": [_r(ci0[0], 2), _r(ci0[1], 2)], "bootstrap": {"B": b, "seed": seed, "cluster": "calendar day", "ratioOfDaySums": True},
                "nDays": int(len(dayden)), "essDays": _r(dayden.sum() ** 2 / (dayden ** 2).sum(), 1)}

    def row(axis, label, role, aid, thr, deb, gate, with_ci):
        p, C, Pv = study.pieces(aid, thr, deb, gate)
        d = {"axis": axis, "value": label, "role": role, "alignment": aid, "thresholdRpm": thr, "debounceSamples": deb, "coverageGate": gate}
        for k_ in ("nValidOwn", "nCommon", "nCommonPct", "kmCommonPct", "daysKept", "daysReleased", "comparable"):
            d[k_] = p[k_]
        d["unknownRpmShare"] = _r(p["unknownRpmShare"], 4)
        d["ownSharePct"] = _r(p["ownSharePct"], 3)
        d["supportLostPp"], d["detectorPp"], d["supportGainedPp"], d["totalPp"] = (_r(p[k_], 3) for k_ in ("supportLostPp", "detectorPp", "supportGainedPp", "totalPp"))
        if with_ci and p["nCommon"] > 5 and len(set(study.days[C])) > 2:
            kv = "%s|%d|%d" % (aid, thr, deb)
            dfc = pd.DataFrame({"date": study.days[C], "num": study.EV[kv][C] - study.EV[k0][C], "den": study.dist[C]})
            ci, _ = DB.ratio_boot_ci_detail(dfc, "num", "den", scale=100.0, nb=b, seed=seed, day_col="date")
            d["detectorPpCi95"] = [_r(ci[0], 3), _r(ci[1], 3)]
        return d

    # one-at-a-time rows
    oat = [row("released", "S0", "released", *S0[:3], S0[3], True)]
    for thr in THRESHOLDS:
        if thr != S0[1]:
            oat.append(row("T", "%d rpm" % thr, "core", S0[0], thr, S0[2], S0[3], True))
    for tol in ("1.0", "1.5"):
        oat.append(row("A", "nearest %s s" % tol, "core", CORE_A["nearest"][tol], S0[1], S0[2], S0[3], True))
    oat.append(row("A", "nearest 0.5 s", "stress", "n0.5", S0[1], S0[2], S0[3], True))
    oat.append(row("D", "backward, matched width (one-sided 6.0 s)", "core", "b6.0", S0[1], S0[2], S0[3], True))
    oat.append(row("D", "forward, matched width (one-sided 6.0 s)", "core", "f6.0", S0[1], S0[2], S0[3], True))
    oat.append(row("D", "backward, same tolerance (one-sided 3.0 s)", "stress", "b3.0", S0[1], S0[2], S0[3], True))
    for deb in CORE_B:
        if deb != S0[2]:
            oat.append(row("B", "%d samples" % deb, "core", S0[0], S0[1], deb, S0[3], True))
    oat.append(row("B", "10 samples", "stress", S0[0], S0[1], 10, S0[3], True))
    for g in (0.90, 0.98):
        oat.append(row("G", "coverage gate %.2f" % g, "stress", S0[0], S0[1], S0[2], g, True))
    axis_range = {}
    for ax in ("T", "A", "D", "B"):
        core = [r for r in oat if r["axis"] == ax and r["role"] == "core" and r["comparable"]] + [oat[0]]
        deltas = [r["detectorPp"] for r in core]
        axis_range[ax] = {"nComparableCoreRows": len(core) - 1, "deltaPp": [_r(min(deltas), 3), _r(max(deltas), 3)], "sharePct": [_r(s0 + min(deltas), 2), _r(s0 + max(deltas), 2)]}
    # factorial over the core grid (matched-width directions, B in the core set)
    cells = []
    for thr, (direction, tolmap), deb in itertools.product(THRESHOLDS, CORE_A.items(), CORE_B):
        for tolname, aid in tolmap.items():
            p, C, Pv = study.pieces(aid, thr, deb, S0[3])
            cells.append({"direction": direction, "A": tolname, "alignment": aid, "thresholdRpm": thr, "debounceSamples": deb, "comparable": p["comparable"], "detectorPp": _r(p["detectorPp"], 3),
                          "nCommonPct": p["nCommonPct"], "kmCommonPct": p["kmCommonPct"]})
    comp = [c for c in cells if c["comparable"]]
    dmin, dmax = min(comp, key=lambda c: c["detectorPp"]), max(comp, key=lambda c: c["detectorPp"])
    factorial = {"nCells": len(cells), "nComparable": len(comp), "nNotComparable": len(cells) - len(comp), "deltaPpRange": [dmin["detectorPp"], dmax["detectorPp"]],
                 "sharePctRange": [_r(s0 + dmin["detectorPp"], 2), _r(s0 + dmax["detectorPp"], 2)], "minCell": dmin, "maxCell": dmax,
                 "notComparableCells": [{k_: c[k_] for k_ in ("direction", "A", "thresholdRpm", "debounceSamples", "nCommonPct", "kmCommonPct")} for c in cells if not c["comparable"]][:60]}
    return {"released": released, "oneAtATime": oat, "axisRanges": axis_range, "factorial": factorial, "factorialCells": cells}


def g1_parity(study):
    """Gate G1: the evaluator at S0 reproduces the master's EV columns for every drive and the payload population totals."""
    dm, k0 = study.dm, "%s|%d|%d" % (S0[0], S0[1], S0[2])
    bad = []
    for i, f in enumerate(study.files):
        m_ev = dm.loc[i, "ev_dist_km"]
        if not study.has[i]:
            if pd.notna(m_ev):
                bad.append((f, "evaluator has no result but the master has ev_dist_km"))
            continue
        if pd.isna(m_ev):
            bad.append((f, "master has no ev_dist_km"))
            continue
        if round(study.EV[k0][i], 3) != round(float(m_ev), 3) or int(study.ET[k0][i]) != int(dm.loc[i, "ev_time_s"]) or round(float(study.COV[S0[0]][i]), 4) != round(float(dm.loc[i, "ev_cov_rpm"]), 4):
            bad.append((f, "ev_dist_km %s vs %s" % (round(study.EV[k0][i], 3), m_ev)))
        ok = bool(study.valid(S0[0], S0[3])[i])
        if ok != bool(study.rel_valid[i]):
            bad.append((f, "ev_valid %s vs %s" % (ok, study.rel_valid[i])))
    P0 = study.rel_valid & ~study.ens
    return {"ok": not bad, "nMismatch": len(bad), "examples": bad[:8], "nValid": int(P0.sum()), "kmValid": round(float(study.dist[P0].sum()), 1), "evKm": round(float(np.nansum(study.EV[k0][P0])), 1),
            "evPctDistance": round(study.share(P0, k0), 1)}


def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run"); r.add_argument("--out", required=True); r.add_argument("--workers", type=int, default=5); r.add_argument("--raw-dir", default=os.path.join(ROOT, "raw_only"))
    r.add_argument("--boot-b", type=int, default=4000)
    a = ap.parse_args()
    os.chdir(ROOT)
    t0 = time.time()
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    jobs = [(f, os.path.join(a.raw_dir, f)) for f in dm["file"]]
    import multiprocessing as mp
    per = {}
    with mp.get_context("spawn").Pool(a.workers) as pool:
        for i, (fn, res) in enumerate(pool.imap_unordered(_worker, jobs, chunksize=4)):
            per[fn] = res
            if (i + 1) % 100 == 0:
                print("%d / %d drives (%.0f s)" % (i + 1, len(jobs), time.time() - t0), flush=True)
    errs = {f: r_["error"] for f, r_ in per.items() if isinstance(r_, dict) and "error" in r_}
    study = Study(dm, per)
    g1 = g1_parity(study)
    res = {"_provenance": {"spec": "analyses/M432_spec.md", "masterMd5": md5, "script": "tools/m432_ev_sens.py", "nDrives": len(dm), "nWithResult": int(study.has.sum()), "nErrors": len(errs), "errors": dict(list(errs.items())[:10]),
                           "label": "raw/ = sha256-verified originals (M366); detector-sensitivity range over declared conventions; not a confidence interval; model-derived"},
           "G1": g1}
    if g1["ok"]:
        res.update(build_result(study, b=a.boot_b))
    # per-drive per-variant table (evidence for the audit): file, alignment, threshold, debounce, ev_km, ev_time_s, rpm coverage
    rows = []
    for f in dm["file"]:
        r_ = per.get(f)
        if isinstance(r_, dict) and "ev" in r_:
            for k_, (km, ts) in r_["ev"].items():
                aid, thr, deb = k_.split("|")
                rows.append((f, aid, int(thr), int(deb), round(km, 6), ts, r_["cov"][aid]))
    tab = pd.DataFrame(rows, columns=["file", "alignment", "thresholdRpm", "debounce", "evKm", "evTimeS", "covRpm"])
    tpath = os.path.splitext(a.out)[0] + "_per_drive.csv.gz"
    with gzip.open(tpath, "wt", encoding="utf-8", newline="\n") as f:
        tab.to_csv(f, index=False, lineterminator="\n")
    res["_provenance"]["elapsedSeconds"] = round(time.time() - t0)
    res["_provenance"]["perDriveTable"] = os.path.basename(tpath)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(res, indent=1, ensure_ascii=False, default=float) + "\n")
    print(json.dumps({"G1": {k_: g1[k_] for k_ in ("ok", "nMismatch", "nValid", "kmValid", "evKm", "evPctDistance")}, "errors": len(errs)}, indent=1))
    if not g1["ok"]:
        print("G1 FAILED:", g1["examples"])
        sys.exit(1)


if __name__ == "__main__":
    main()
