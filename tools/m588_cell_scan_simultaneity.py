#!/usr/bin/env python3
"""M588 (spec analyses/M588_spec.md Rev 1): simultaneity of the Vmax / Vmin reads behind the loaded p95 cell spread. Analysis only: reads drive_master.csv and the raw CSVs read-only, writes
analyses/M588_result.json; no payload key, no master column. The production helpers (compute_drive_summary_v6._prep_bytes, _series, _asof, SPREAD_TOL, V_ALIGN_TOL) are called, not re-implemented.
Reference D0 = production pairing (nearest within 300 ms, loaded |I| > 50 A at the Vmax read); D1-D3 keep pairs with dt <= 150 / 75 / 30 ms; D4 keeps pairs with |dI_A| <= 10 A and distinct current samples.
Usage: python tools/m588_cell_scan_simultaneity.py [--out analyses/M588_result.json] [--no-cache]"""
import argparse, hashlib, json, os, pickle, sys
import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import compute_drive_summary_v6 as D       # noqa: E402
import m573_cell_spread_step as m573        # noqa: E402
import m577_cell_spread_levels as m577      # noqa: E402

SEED, NBOOT = 42, 4000
MIN_PAIRS = 200
DT_THRESHOLDS = {"D1": 150.0, "D2": 75.0, "D3": 30.0}
DI_MATCH_A = 10.0
SAME_I_LIMIT = 0.5
ARM_DRIVES, ARM_DAYS = 10, 5
DEGENERATE_LIMIT = 0.10
CACHE_DIR = os.path.join(ROOT, "m588_cache")
BASE = m577.BASE


def build_pairs(vmax, vmin, I):
    """Pure. vmax, vmin, I: frames (t, v) as produced by D._series. Returns the pair frame with the matched Vmin timestamp carried explicitly, the currents at both read times (production _asof, V_ALIGN_TOL)
    and the matched current-sample timestamps. Pair set and spread are exactly those of the production pairing (merge_asof nearest within SPREAD_TOL)."""
    vmin2 = vmin.rename(columns={"v": "vmin"}).copy()
    vmin2["t_vmin"] = vmin2["t"]
    p = pd.merge_asof(vmax.rename(columns={"v": "vmax"}), vmin2, on="t", direction="nearest", tolerance=pd.Timedelta(D.SPREAD_TOL)).dropna().reset_index(drop=True)
    p = p.rename(columns={"t": "t_vmax"})
    p["spread_mv"] = (p["vmax"] - p["vmin"]) * 1000.0
    p["dt_ms"] = (p["t_vmax"] - p["t_vmin"]).abs().dt.total_seconds() * 1000.0
    Ii = I.rename(columns={"v": "I"}).copy()
    Ii["tI"] = Ii["t"]
    a = pd.merge_asof(p[["t_vmax"]].rename(columns={"t_vmax": "t"}), Ii, on="t", direction="nearest", tolerance=pd.Timedelta(D.V_ALIGN_TOL))
    b = pd.merge_asof(p[["t_vmin"]].rename(columns={"t_vmin": "t"}), Ii, on="t", direction="nearest", tolerance=pd.Timedelta(D.V_ALIGN_TOL))
    p["I_vmax"], p["tI_vmax"] = a["I"].values, a["tI"].values
    p["I_vmin"], p["tI_vmin"] = b["I"].values, b["tI"].values
    p["dI_A"] = p["I_vmin"] - p["I_vmax"]
    p["same_I"] = (p["tI_vmax"] == p["tI_vmin"]) & p["tI_vmax"].notna()
    p["abs_I"] = p["I_vmax"].abs()
    return p


def quantum_ms(s):
    """Smallest positive difference between consecutive timestamps of a series (ms) and the mode of the positive differences."""
    d = (s["t"].diff().dt.total_seconds().dropna() * 1000.0).round(3)
    d = d[d > 0]
    if not len(d):
        return None, None
    return float(d.min()), float(d.mode().iloc[0])


def p95(x):
    return None if len(x) == 0 else float(round(pd.Series(x).quantile(0.95), 1))      # numpy-float rounding exactly as production (round(Series.quantile, 1)); Python round on a float differs at x.x5


def drive_record(p, vmax, vmin):
    """Pure. Per-drive record from the pair frame."""
    loaded = p[p["abs_I"] > 50].copy()
    rec = {"nPairs": int(len(p)), "nLoaded": int(len(loaded)), "p95Ref": p95(loaded["spread_mv"].values) if len(loaded) else None}
    qv, qm = quantum_ms(vmax), quantum_ms(vmin)
    rec["quantumMs"] = {"vmax": qv[0], "vmin": qm[0], "vmaxMode": qv[1], "vminMode": qm[1]}
    rec["vminReuseShare"] = float(1.0 - p["t_vmin"].nunique() / len(p)) if len(p) else None
    if len(loaded):
        rec["dtMs"] = {"median": float(loaded["dt_ms"].median()), "p95": float(loaded["dt_ms"].quantile(0.95))}
        di = loaded["dI_A"].dropna()
        rec["sameIShare"] = float(loaded["same_I"].mean())
        rec["absDiA"] = {"median": (float(di.abs().median()) if len(di) else None), "p95": (float(di.abs().quantile(0.95)) if len(di) else None), "n": int(len(di))}
        rec["absIMedian"] = float(loaded["abs_I"].median())
        # E2: spread ~ dI_A + |I| over loaded pairs with distinct current samples, and Spearman(spread, dt)
        dist = loaded[(~loaded["same_I"]) & loaded["dI_A"].notna()]
        rec["e2"] = {"nDistinct": int(len(dist))}
        if len(dist) >= 50 and dist["dI_A"].std() > 0:
            X = np.column_stack([np.ones(len(dist)), dist["dI_A"].values, dist["abs_I"].values])
            beta = np.linalg.lstsq(X, dist["spread_mv"].values, rcond=None)[0]
            rec["e2"]["dIcoef"] = float(beta[1])
        if len(loaded) >= 50 and loaded["dt_ms"].nunique() > 1 and loaded["spread_mv"].nunique() > 1:
            rec["e2"]["spearmanDt"] = float(stats.spearmanr(loaded["spread_mv"], loaded["dt_ms"]).correlation)
        designs = {}
        masks = {k: loaded["dt_ms"] <= v for k, v in DT_THRESHOLDS.items()}
        masks["D4"] = (loaded["dI_A"].abs() <= DI_MATCH_A) & (~loaded["same_I"])
        for k, m in masks.items():
            kept = loaded[m]
            designs[k] = {"nKept": int(len(kept)), "p95": (p95(kept["spread_mv"].values) if len(kept) >= MIN_PAIRS else None), "absIMedianKept": (float(kept["abs_I"].median()) if len(kept) else None),
                          "sameIShareKept": (float(kept["same_I"].mean()) if len(kept) else None)}
        rec["designs"] = designs
    return rec


def extract(csv_bytes):
    df, t = D._prep_bytes(csv_bytes)
    I = D._series(df, t, "I")
    if I is not None:
        I = I[I["v"].abs() < 900]
    vmax = D._series(df, t, "Vcell_max", lo=2.0, hi=5.0)
    vmin = D._series(df, t, "Vcell_min", lo=2.0, hi=5.0)
    if vmax is None or vmin is None or I is None:
        return {"nPairs": 0, "nLoaded": 0, "p95Ref": None}
    p = build_pairs(vmax, vmin, I)
    if not len(p):
        return {"nPairs": 0, "nLoaded": 0, "p95Ref": None}
    return drive_record(p, vmax, vmin)


def code_hash():
    return hashlib.sha256(open(os.path.abspath(__file__), "rb").read()).hexdigest()[:16]


def load_records(dm, loader, use_cache=True):
    os.makedirs(CACHE_DIR, exist_ok=True)
    ch = code_hash()
    out = {}
    for f in dm["file"]:
        b = loader(f)
        if b is None:
            raise SystemExit("STOP: no raw bytes for master drive %s" % f)
        h = hashlib.sha256(b).hexdigest()
        cp = os.path.join(CACHE_DIR, "%s.pkl" % f)
        if use_cache and os.path.exists(cp):
            c = pickle.load(open(cp, "rb"))
            if c.get("sha") == h and c.get("code") == ch:
                out[f] = c["rec"]
                continue
        rec = extract(b)
        pickle.dump({"sha": h, "code": ch, "rec": rec}, open(cp, "wb"))
        out[f] = rec
    return out


def fidelity(dm, recs):
    """R6: round(p95, 1) equals the master value and n_loaded_spread_samples matches exactly (same missingness)."""
    bad = []
    for f, m95, mn in zip(dm["file"], dm["cell_spread_loaded_p95_mv"], dm["n_loaded_spread_samples"]):
        r = recs[f]
        a = r["p95Ref"]
        ok_p = (a is None and pd.isna(m95)) or (a is not None and not pd.isna(m95) and a == round(float(m95), 1))
        ok_n = (int(r["nLoaded"]) == (0 if pd.isna(mn) else int(mn)))
        if not (ok_p and ok_n):
            bad.append(f)
    return bad


def design_y(dm, recs, k):
    """Per-drive outcome of design k (None below the pairs rule)."""
    return {f: (recs[f].get("designs", {}).get(k, {}).get("p95") if recs[f].get("designs") else None) for f in dm["file"]}


def arm_ok(df, min_n=ARM_DRIVES, min_days=ARM_DAYS):
    return all(int((df["step"] == s).sum()) >= min_n and int(df.loc[df["step"] == s, "day"].nunique()) >= min_days for s in (0, 1))


def fit_both(d, ycol_k, n=NBOOT, seed=SEED):
    """E3 on one design set: D0-on-the-same-set and D_k fits of model A (CR2 t(G-1), Satterthwaite) for step and slow within the support re-derived on this set, plus the paired difference
    (D_k minus D0) with a day-clustered pairs bootstrap using the SAME day draws for both outcomes."""
    out = {"nDrives": int(len(d)), "days": int(d["day"].nunique())}
    if not arm_ok(d):
        return {**out, "status": "not estimable (arm floor)"}
    lo, hi = m577.common_support(d)
    s = d[(d["T"] >= lo) & (d["T"] <= hi)].copy()
    out["supportT"] = [round(lo, 2), round(hi, 2)]
    out["nInSupport"] = int(len(s))
    if not arm_ok(s):
        return {**out, "status": "not estimable (arm floor in support)"}
    cols = [c for c in BASE if s[c].nunique() > 1]
    X = np.column_stack([np.ones(len(s)), s[cols].values.astype(float)])
    y0, yk = s["y"].values.astype(float), s[ycol_k].values.astype(float)
    res = {}
    for term in ("step", "slow"):
        if term not in cols:
            res[term] = {"status": "not estimable (term constant)"}
            continue
        d0, dk = s.assign(y=y0), s.assign(y=yk)
        f0, fk = m577.fit_term(d0, cols, term), m577.fit_term(dk, cols, term)
        k = 1 + cols.index(term)
        days = s["day"].values
        u = np.unique(days)
        idx = {x: np.flatnonzero(days == x) for x in u}
        rng = np.random.default_rng(seed)
        diffs, bad = [], 0
        for _ in range(n):
            ch = rng.choice(u, len(u))
            sel = np.concatenate([idx[x] for x in ch])
            if len(np.unique(s["step"].values[sel])) < 2:
                bad += 1
                continue
            try:
                b0 = np.linalg.lstsq(X[sel], y0[sel], rcond=None)[0][k]
                bk = np.linalg.lstsq(X[sel], yk[sel], rcond=None)[0][k]
            except np.linalg.LinAlgError:
                bad += 1
                continue
            diffs.append(bk - b0)
        ci = [round(float(np.percentile(diffs, 2.5)), 4), round(float(np.percentile(diffs, 97.5)), 4)] if diffs else None
        margin = f0["mde80"]
        diff = round(fk["est"] - f0["est"], 4)
        evaluable = bool(ci is not None and bad / n <= DEGENERATE_LIMIT)
        if not evaluable:
            reading = "not evaluable"
        elif ci[0] >= -margin and ci[1] <= margin:
            reading = "no change beyond %.2f mV detected" % margin
        elif ci[0] > 0 or ci[1] < 0:
            reading = "changes by about %.2f mV (paired interval %s)" % (diff, ci)
        else:
            reading = "not resolved at this precision"
        res[term] = {"D0sameSet": {k_: f0[k_] for k_ in ("est", "se", "ci95", "ciSatterthwaite", "mde80", "dfDependent")}, "Dk": {k_: fk[k_] for k_ in ("est", "se", "ci95", "ciSatterthwaite", "mde80", "dfDependent")},
                     "pairedDiff": diff, "pairedDiffCi95": ci, "relevanceMarginMv": margin, "degenerateDraws": bad, "reading": reading,
                     "includesZeroD0": bool(f0["ci95"][0] <= 0 <= f0["ci95"][1]), "includesZeroDk": bool(fk["ci95"][0] <= 0 <= fk["ci95"][1])}
    return {**out, "status": "ok", "terms": res}


def summarise(vals):
    v = pd.Series([x for x in vals if x is not None and not (isinstance(x, float) and np.isnan(x))], dtype=float)
    return None if len(v) == 0 else {"n": int(len(v)), "median": round(float(v.median()), 3), "q25": round(float(v.quantile(.25)), 3), "q75": round(float(v.quantile(.75)), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "analyses", "M588_result.json"))
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()
    os.chdir(ROOT)
    import ah_throughput as AH
    mp = os.path.join(ROOT, "drive_master.csv")
    md5_before = hashlib.md5(open(mp, "rb").read()).hexdigest()
    dm = pd.read_csv(mp, low_memory=False)
    recs = load_records(dm, AH.raw_loader(), use_cache=not a.no_cache)
    bad = fidelity(dm, recs)
    if bad:
        raise SystemExit("M588 STOP: the reference pairing does not reproduce the master column / count on %d drives, e.g. %s" % (len(bad), bad[:5]))
    reg = pd.read_csv("cadence_regime.csv").set_index("file")["regime"]
    pid = pd.read_csv("pid_epoch.csv").set_index("file")["pidSetClass"]
    out = {"milestone": "M588", "spec": "analyses/M588_spec.md Rev 1", "specSha256": hashlib.sha256(open("analyses/M588_spec.md", "rb").read()).hexdigest(), "masterMd5": md5_before,
           "scriptSha256": hashlib.sha256(open(os.path.abspath(__file__), "rb").read()).hexdigest(), "seed": SEED, "draws": NBOOT, "fidelity": {"passed": True, "nDrives": int(len(dm))}}
    # ---- E1 / E2 summaries
    def grp(sel_fn):
        fs = [f for f in dm["file"] if recs[f].get("nLoaded", 0) > 0 and sel_fn(f)]
        g = lambda path: summarise([_get(recs[f], path) for f in fs])
        return {"nDrives": len(fs), "dtMedianMs": g(("dtMs", "median")), "dtP95Ms": g(("dtMs", "p95")), "absDiAMedian": g(("absDiA", "median")), "sameIShare": g(("sameIShare",)), "vminReuseShare": g(("vminReuseShare",)),
                "quantumMinMs": summarise([min(q for q in (recs[f]["quantumMs"]["vmax"], recs[f]["quantumMs"]["vmin"]) if q is not None) for f in fs if recs[f].get("quantumMs") and (recs[f]["quantumMs"]["vmax"] or recs[f]["quantumMs"]["vmin"])]),
                "e2DIcoef": g(("e2", "dIcoef")), "e2SpearmanDt": g(("e2", "spearmanDt"))}
    def _get(r, path):
        for k in path:
            if r is None or k not in r:
                return None
            r = r[k]
        return r
    out["E1"] = {"all": grp(lambda f: True), "byRegime": {rg: grp(lambda f, rg=rg: reg.get(f) == rg) for rg in ("fast", "slow")}, "byPidClass": {c: grp(lambda f, c=c: pid.get(f) == c) for c in "ABCD"}}
    # estimability of the thresholds by quantum (per regime): below two quanta is not estimable
    qmin = {rg: out["E1"]["byRegime"][rg]["quantumMinMs"] for rg in ("fast", "slow")}
    out["thresholdEstimability"] = {k: {rg: (None if qmin[rg] is None else bool(thr >= 2 * qmin[rg]["median"])) for rg in ("fast", "slow")} for k, thr in DT_THRESHOLDS.items()}
    # ---- E3
    d0 = m573.build_frame(dm).dropna(subset=["soc", "socr", "lrest", "I_sample_period_s"]).copy()
    out["frame"] = {"nEligible": int(len(d0))}
    out["E3"] = {}
    for k in ("D1", "D2", "D3", "D4"):
        yk = design_y(dm, recs, k)
        d = d0.assign(y_k=d0["file"].map(yk)).dropna(subset=["y_k"]).copy()
        dropped = d0[~d0["file"].isin(d["file"])]
        kept_all, kept_k = d0["file"].map(lambda f: recs[f].get("absIMedian")), d["file"].map(lambda f: recs[f]["designs"][k]["absIMedianKept"])
        info = {"nDroppedDrives": int(len(dropped)), "droppedByRegime": {str(r): int(n) for r, n in dropped["file"].map(reg).value_counts(dropna=False).items()},
                "droppedByPidClass": {str(r): int(n) for r, n in dropped["file"].map(pid).value_counts(dropna=False).items()}, "droppedByStepArm": {str(int(s)): int(n) for s, n in dropped["step"].value_counts().items()},
                "absIMedianAllLoaded": summarise(kept_all), "absIMedianKeptLoaded": summarise(kept_k)}
        if k == "D4":
            info["sameIShareKept"] = summarise([recs[f]["designs"][k]["sameIShareKept"] for f in d["file"]])
            info["interpretable"] = bool(info["sameIShareKept"] is None or info["sameIShareKept"]["median"] <= SAME_I_LIMIT)
        fit = fit_both(d, "y_k")
        # Director ruling (M588): the frozen rule is applied as written. D1-D3 are below two raw timestamp quanta -> not estimable; D4 not interpretable when same_I_share > limit.
        # The fits stay only as a labelled descriptive appendix, never a decision reading (the rule is ill-posed for a cross-series offset: disclosed deviation).
        if k == "D4":
            status = "not interpretable (same_I_share>0.5)" if not info["interpretable"] else fit.get("status")
        else:
            status = "not estimable (sub-quantum threshold, frozen rule)" if not any(out["thresholdEstimability"][k].values()) else fit.get("status")
        out["E3"][k] = {"population": info, "status": status, "descriptiveAppendix": {"note": "descriptive appendix, not a decision reading", **fit}}
    assert hashlib.md5(open(mp, "rb").read()).hexdigest() == md5_before, "drive_master.csv changed: STOP"
    out["masterMd5After"] = md5_before
    out["headline"] = "no read-offset contrast exists in these data (logger response offset near-constant within regime; current on a ~1 s grid); the pairing sensitivity of the loaded p95 and of the M577 step / slow terms is not testable here"
    out["perDrive"] = {f: {"nLoaded": recs[f].get("nLoaded"), "p95Ref": recs[f].get("p95Ref"), "dtMedianMs": (recs[f].get("dtMs") or {}).get("median"), "sameIShare": recs[f].get("sameIShare"),
                           "designs": {k: v.get("p95") for k, v in (recs[f].get("designs") or {}).items()}} for f in dm["file"]}
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({"fidelity": out["fidelity"], "E1all": out["E1"]["all"], "thresholdEstimability": out["thresholdEstimability"],
                      "E3": {k: {"status": v.get("status")} for k, v in out["E3"].items()}}, indent=1)[:6000])


if __name__ == "__main__":
    main()
