#!/usr/bin/env python3
"""M577 (spec analyses/M577_spec.md Rev 1): cell-spread level after the M575 ingestion; temperature, logger regime and PID-set change.
Analysis only: reads drive_master.csv, writes analyses/M577_levels.json; no payload key, no dashboard change, no master column.
Frame and covariates are the M573 frame (tools/m573_cell_spread_step.py::build_frame). Inference: calendar-day cluster; CR2 SE (tools/dependence_sensitivity.py::cr2) with a
t(G-1) interval; day-clustered pairs percentile bootstrap and week-block bootstrap (seed 42, 4000 draws). Usage: python tools/m577_cell_spread_levels.py [--out PATH]"""
import argparse, hashlib, json, os, sys
import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import dependence_sensitivity as ds           # noqa: E402
import m573_cell_spread_step as m573           # noqa: E402

SEED, NBOOT = 42, 4000
STEP_DATE, PID_DATE = "2026-10-01", "2026-11-03"
FLOOR_DRIVES, FLOOR_DAYS = 10, 5
VIF_LIMIT = 5.0
ADJ_COL = "cell_spread_loaded_p95_adj_mv"
BASE = ["months", "step", "slow", "T", "I", "soc", "socr", "lrest", "first"]       # model A (M5 plus R)


def _r(x, nd=4):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), nd)


def design(d, cols):
    return np.c_[np.ones(len(d)), d[cols].values.astype(float)], d["y"].values.astype(float)


def fit_term(d, cols, coef):
    """CR2 standard error, t(G-1) interval, minimum detectable effect (80 % power) of `coef`."""
    X, y = design(d, cols)
    k = 1 + cols.index(coef)
    b, se, df_sat, fl = ds.cr2(X, y, d["day"].values, k)
    G = int(d["day"].nunique())
    tc = float(stats.t.ppf(0.975, G - 1))
    ci = [_r(b - tc * se), _r(b + tc * se)]
    ci_sat = sat_interval(b, se, df_sat)
    return {"est": _r(b), "se": _r(se), "ci95": ci, "n": int(len(d)), "days": G, "G": G, "dfSatterthwaite": _r(df_sat, 2),
            "mde80": _r((tc + float(stats.t.ppf(0.8, G - 1))) * se), "unitLeverageClusters": fl["clustersWithUnitLeverage"],
            "ciSatterthwaite": ci_sat, "dfDependent": bool(ci_sat is not None and excl(ci) and not excl(ci_sat))}


def day_boot(d, cols, coef, n=NBOOT, seed=SEED):
    """Day-clustered pairs percentile bootstrap (whole calendar days resampled)."""
    X, y = design(d, cols)
    k = 1 + cols.index(coef)
    days = d["day"].values
    u = np.unique(days)
    idx = {x: np.flatnonzero(days == x) for x in u}
    rng = np.random.default_rng(seed)
    out = np.empty(n)
    for i in range(n):
        s = np.concatenate([idx[x] for x in rng.choice(u, len(u))])
        out[i] = np.linalg.lstsq(X[s], y[s], rcond=None)[0][k]
    return {"ci95": [_r(np.percentile(out, 2.5)), _r(np.percentile(out, 97.5))], "draws": n, "seed": seed, "nDays": int(len(u))}


def week_boot(d, cols, coef):
    r = m573.week_block_bootstrap(d, cols, coef=coef)
    return {"ci95": r["ci95"], "draws": r["draws"], "seed": r["seed"], "nBlocks": r["nBlocks"]}


def leave_one_week_out(d, cols, coef):
    k = 1 + cols.index(coef)
    est = []
    for w in d["wk"].unique():
        s = d[d["wk"] != w]
        X, y = design(s, cols)
        est.append(np.linalg.lstsq(X, y, rcond=None)[0][k])
    return {"min": _r(min(est)), "max": _r(max(est)), "nWeeks": int(d["wk"].nunique())}


def vif(d, cols, coef):
    X = d[cols].values.astype(float)
    j = cols.index(coef)
    o = np.c_[np.ones(len(d)), np.delete(X, j, axis=1)]
    beta = np.linalg.lstsq(o, X[:, j], rcond=None)[0]
    res = X[:, j] - o @ beta
    tss = ((X[:, j] - X[:, j].mean()) ** 2).sum()
    r2 = 1.0 - float((res ** 2).sum()) / tss if tss > 0 else 1.0
    return float("inf") if r2 >= 1 - 1e-12 else _r(1.0 / (1.0 - r2), 3)


def excl(ci):
    return ci is not None and ci[0] is not None and (ci[0] > 0 or ci[1] < 0)


def label_term(A, others, vif_val, gate_vif):
    """Spec 'Decision rules' (fixed precedence). A: CR2 result of the primary model; others: {name: ci95 or None (not evaluable)}; gate_vif: the VIF gate applies (R only)."""
    missing = sorted(k for k, v in others.items() if v is None)
    if gate_vif and (vif_val is None or vif_val > VIF_LIMIT):
        return "not separable", missing
    ev = {k: v for k, v in others.items() if v is not None}
    a_sign = np.sign(A["est"])
    if excl(A["ci95"]):
        agree = all(excl(v) and np.sign(np.mean(v)) == a_sign for v in ev.values())
        return ("distinguishable from zero" if agree else "procedure-dependent"), missing
    return "not distinguishable from zero (not equivalence)", missing


def pid_identification(d, pid_date=PID_DATE):
    p = d["date"] >= pd.Timestamp(pid_date)
    n, days = int(p.sum()), int(d.loc[p, "day"].nunique())
    ok = n >= FLOOR_DRIVES and days >= FLOOR_DAYS
    return {"pidDate": pid_date, "nDrives": n, "nDays": days, "label": "testable" if ok else f"not identified (P on {days} day{'s' if days != 1 else ''})"}


def common_support(d):
    a, b = d[d["step"] == 0]["T"], d[d["step"] == 1]["T"]
    return float(max(a.min(), b.min())), float(min(a.max(), b.max()))


def spline_cols(d, lo, hi):
    from patsy import dmatrix
    q = [float(np.percentile(d["T"], p)) for p in (25, 50, 75)]
    M = np.asarray(dmatrix("cr(T, knots=q, lower_bound=lo, upper_bound=hi, constraints='center') - 1", {"T": d["T"].values, "q": q, "lo": lo, "hi": hi}))
    names = [f"sp{i}" for i in range(M.shape[1])]
    return pd.concat([d, pd.DataFrame(M, columns=names, index=d.index)], axis=1), names, q


def arm_floor(d):
    return all(int((d["step"] == s).sum()) >= FLOOR_DRIVES and int(d.loc[d["step"] == s, "day"].nunique()) >= FLOOR_DAYS for s in (0, 1))


def run(dm):
    d0 = m573.build_frame(dm)
    n_pre = len(d0)
    d = d0.dropna(subset=["soc", "socr", "lrest", "I_sample_period_s"]).copy()
    dropped = {"frameDrives": int(n_pre), "droppedMissingCovariateOrSamplePeriod": int(n_pre - len(d))}
    lo, hi = common_support(d)
    ins = d[(d["T"] >= lo) & (d["T"] <= hi)].copy()
    out_of = d[(d["T"] < lo) | (d["T"] > hi)]
    out = {"support": {"commonSupportT": [_r(lo, 2), _r(hi, 2)], "nInSupport": int(len(ins)), "nOutside": int(len(out_of)), "outsideByStep": {str(int(k)): int(v) for k, v in out_of["step"].value_counts().items()},
                       "outsideDays": int(out_of["day"].nunique()), "armsInSupport": {str(int(k)): {"n": int(v), "days": int(ins.loc[ins["step"] == k, "day"].nunique())} for k, v in ins["step"].value_counts().items()},
                       "m119FitBasisSensitivity": "model A-include below; the 9 C figure is a flagged sensitivity, not the rule"}, "frame": dropped}
    out["frame"].update({"nAnalysis": int(len(ins)), "days": int(ins["day"].nunique()), "first": str(ins["date"].min().date()), "last": str(ins["date"].max().date())})

    # primary model A
    A = {t: fit_term(ins, BASE, t) for t in ("step", "slow")}
    Ab = {t: day_boot(ins, BASE, t) for t in ("step", "slow")}
    Ae = {t: {"weekBlockBootstrap": week_boot(ins, BASE, t), "leaveOneWeekOut": leave_one_week_out(ins, BASE, t)} for t in ("step", "slow")}
    v = {t: vif(ins, BASE, t) for t in ("step", "slow", "months")}
    v["corrStepMonths"] = _r(float(np.corrcoef(ins["step"], ins["months"])[0, 1]), 3)
    v["corrStepSlow"] = _r(float(np.corrcoef(ins["step"], ins["slow"])[0, 1]), 3)

    # B: spline temperature
    sp, names, knots = spline_cols(ins, lo, hi)
    colsB = [c for c in BASE if c != "T"] + names
    B = {t: fit_term(sp, colsB, t) for t in ("step", "slow")}

    # C: cold subset by quantile
    q25 = float(np.percentile(ins["T"], 25))
    cs = ins[ins["T"] <= q25].copy()
    colsC = ["step", "slow", "I", "soc", "socr"]
    C_ok = arm_floor(cs)
    C = {t: fit_term(cs, colsC, t) for t in ("step", "slow")} if C_ok else None
    out["modelC_info"] = {"T_upper_quantile25": _r(q25, 2), "n": int(len(cs)), "days": int(cs["day"].nunique()), "evaluable": bool(C_ok),
                          "arms": {str(int(k)): {"n": int((cs["step"] == k).sum()), "days": int(cs.loc[cs["step"] == k, "day"].nunique())} for k in (0, 1)},
                          "monthsOfStep0Drives": {str(k): int(x) for k, x in cs.loc[cs["step"] == 0, "date"].dt.strftime("%Y-%m").value_counts().sort_index().items()}}

    labels = {}
    for t in ("step", "slow"):
        others = {"dayBootstrap": Ab[t]["ci95"], "splineT_B": B[t]["ci95"], "coldSubset_C": (C[t]["ci95"] if C else None), "weekBlock_E": Ae[t]["weekBlockBootstrap"]["ci95"]}
        lab, miss = label_term(A[t], others, v[t], gate_vif=(t == "slow"))
        labels[t] = {"label": lab, "modelsNotEvaluable": miss, "mde80_A": A[t]["mde80"], "vif": v[t], "ciSatterthwaite": A[t]["ciSatterthwaite"], "dfSatterthwaite": A[t]["dfSatterthwaite"], "G": A[t]["G"], "dfDependent": A[t]["dfDependent"]}

    # sensitivities
    sens = {}
    nop = ins[ins["date"] < pd.Timestamp(PID_DATE)]
    sens["A_noPidDay"] = {t: fit_term(nop, BASE, t) for t in ("step", "slow")}
    adj = d.assign(y=d[ADJ_COL].astype(float)).dropna(subset=["y"])
    adj = adj[(adj["T"] >= lo) & (adj["T"] <= hi)]
    sens["A_adjustedOutcome"] = {t: fit_term(adj, BASE, t) for t in ("step", "slow")}
    sens["A_includeOutsideSupport"] = {t: fit_term(d, BASE, t) for t in ("step", "slow")}
    sens["A_includeOutsideSupport"]["n"] = int(len(d))

    # PID / sample period
    pid = pid_identification(d)
    sp_ = d.assign(per=np.where(d["date"] >= pd.Timestamp(PID_DATE), "2026-11-03", np.where(d["date"] >= pd.Timestamp("2026-11-01"), "2026-11-01..02", "earlier")))
    pid["samplePeriodS"] = {k: {"n": int(len(g)), "median": _r(g["I_sample_period_s"].median(), 3), "q25": _r(g["I_sample_period_s"].quantile(.25), 3), "q75": _r(g["I_sample_period_s"].quantile(.75), 3)} for k, g in sp_.groupby("per")}
    pid["descriptiveYMedianP1"] = _r(float(d.loc[d["date"] >= pd.Timestamp(PID_DATE), "y"].median()), 2)
    out.update({"modelA": {"terms": A, "dayBootstrap": Ab, "dependenceE": Ae, "formula": "y ~ " + " + ".join(BASE)}, "modelB": {"terms": B, "splineKnotsT": [_r(x, 2) for x in knots], "splineColumns": len(names)},
                "modelC": C, "labels": labels, "sensitivities": sens, "q3Pid": pid, "multiplicity": "2 terms (step, slow) x models A, B, C, E and sensitivities, uncorrected; no family-wise claim"})
    return out


# ============================================================================================ M577 Rev 2: PID-set class test (Q3), frozen in analyses/M577_spec_rev2.md
PID_LOOKS = os.path.join(ROOT, "analyses", "M577_pid_looks.json")
PID_TERM_DRIVES, PID_TERM_DAYS, PID_TERM_FALLBACK = 20, 10, "2027-03-31"
FIRST_POST_STEP_B = "2026-11-03_15-07-48.csv"
DEGENERATE_LIMIT = 0.10


def sat_interval(est, se, df_sat):
    """Interval with the Satterthwaite degrees of freedom (None when df is not finite)."""
    if df_sat is None or not np.isfinite(df_sat) or df_sat <= 0:
        return None
    tc = float(stats.t.ppf(0.975, float(df_sat)))
    return [_r(est - tc * se), _r(est + tc * se)]


def wider_interval(a, b):
    """The wider of two intervals (R6): the label for a term resting on very few clusters uses it."""
    if a is None:
        return b
    if b is None:
        return a
    return [min(a[0], b[0]), max(a[1], b[1])]


def pid_indicator(d, side):
    """R3: B = 1 for class-B drives at or after the first post-step class-B drive; the early class-B drive and the class C / D drives are dropped (primary); class A = 0.
    Returns (frame with column B, dict of the dropped drives)."""
    m = d.merge(side[["file", "pidSetClass"]], on="file", how="left")
    ts = m["_ts"] if "_ts" in m.columns else pd.to_datetime(m["date"])
    first = ts[m["file"] == FIRST_POST_STEP_B]
    first_ts = first.iloc[0] if len(first) else ts[(m["pidSetClass"] == "B") & (m["date"] >= pd.Timestamp(STEP_DATE))].min()
    isb = (m["pidSetClass"] == "B") & (ts >= first_ts)
    early_b = m[(m["pidSetClass"] == "B") & (ts < first_ts)]["file"].tolist()
    other = m[m["pidSetClass"].isin(["C", "D"])]["file"].tolist()
    keep = m["pidSetClass"].eq("A") | isb
    m = m.assign(B=isb.astype(float))[keep].copy()
    return m, {"earlyClassB": early_b, "classCD": other}


def pid_floor(df, col="B", min_n=FLOOR_DRIVES, min_days=FLOOR_DAYS):
    g = df[df[col] == 1]
    return int(len(g)), int(g["day"].nunique()), bool(len(g) >= min_n and g["day"].nunique() >= min_days)


def _boot_with_degenerate(d, cols, coef, group, n=NBOOT, seed=SEED):
    """Pairs bootstrap over `group` clusters; draws without any class-B cluster (or with a singular design) are counted as degenerate and excluded."""
    X, y = design(d, cols)
    k = 1 + cols.index(coef)
    keys = d[group].values
    u = np.unique(keys)
    idx = {x: np.flatnonzero(keys == x) for x in u}
    hasb = {x: bool((d["B"].values[idx[x]] == 1).any()) for x in u}
    rng = np.random.default_rng(seed)
    out, bad = [], 0
    for _ in range(n):
        ch = rng.choice(u, len(u))
        if not any(hasb[x] for x in ch):
            bad += 1
            continue
        s = np.concatenate([idx[x] for x in ch])
        beta = np.linalg.lstsq(X[s], y[s], rcond=None)[0]
        out.append(beta[k])
    ci = [_r(np.percentile(out, 2.5)), _r(np.percentile(out, 97.5))] if out else None
    return {"ci95": ci, "draws": n, "degenerate": bad, "degenerateShare": _r(bad / n, 3), "evaluable": bool(bad / n <= DEGENERATE_LIMIT and ci is not None)}


def pid_class_run(d_frame, side, readiness, master_md5, master=None, ledger_path=PID_LOOKS, write=True, spec_sha=None):
    """R3-R9: the class-B test. d_frame: the eligible M573 frame (with y, months, T, I, soc, socr, lrest, first, step, slow, day, wk, date, file); side: pid_epoch sidecar; readiness: payload pidEpoch.q3Readiness.
    Refuses (nothing computed) below the floors; STOPs when the payload and the sidecar disagree. Interim looks carry no ladder label."""
    ind, dropped = pid_indicator(d_frame, side)
    nB, daysB, ok_frame = pid_floor(ind)
    if master is not None:
        sm = side.merge(master[["file", "date"]], on="file")
        n_post_b = int(((sm["pidSetClass"] == "B") & (pd.to_datetime(sm["date"]) >= pd.Timestamp(STEP_DATE))).sum())
        if readiness.get("runDrives") is not None and int(readiness["runDrives"]) != n_post_b:
            raise SystemExit("STOP: payload q3Readiness.runDrives (%s) differs from the sidecar / master class B drives after the step (%d)" % (readiness.get("runDrives"), n_post_b))
    base = {"specRev2": "analyses/M577_spec_rev2.md", "specRev2Sha256": spec_sha, "masterMd5": master_md5, "payloadReadiness": readiness, "inFrame": {"classBDrives": nB, "classBDays": daysB, "floorsMet": ok_frame}, "dropped": dropped}
    pay_ok = bool(readiness.get("runDrives", 0) >= FLOOR_DRIVES and readiness.get("runDays", 0) >= FLOOR_DAYS)
    if not (pay_ok and ok_frame):
        return {**base, "status": "not identified (floors not met)", "note": "nothing computed or looked at"}, None
    led = json.load(open(ledger_path, encoding="utf-8")) if os.path.exists(ledger_path) else {"schema": 1, "looks": [], "terminal": None}
    prim = ind[(ind["slow"] == 0) & (ind["step"] == 1)].copy()
    lo = max(prim[prim["B"] == 0]["T"].min(), prim[prim["B"] == 1]["T"].min())
    hi = min(prim[prim["B"] == 0]["T"].max(), prim[prim["B"] == 1]["T"].max())
    prim = prim[(prim["T"] >= lo) & (prim["T"] <= hi)].copy()
    pn, pdays, p_ok = pid_floor(prim)
    cols = [c for c in ["months", "B", "T", "I", "soc", "socr", "lrest", "first"] if c == "B" or prim[c].nunique() > 1]
    res = {"supportT": [_r(lo, 2), _r(hi, 2)], "nPrimary": int(len(prim)), "classBDrives": pn, "classBDays": pdays, "nonBDrives": int((prim["B"] == 0).sum()), "nonBDays": int(prim.loc[prim["B"] == 0, "day"].nunique())}
    if not p_ok:
        return {**base, "status": "not identified (primary-design floors not met)", "primary": res}, None
    b = fit_term(prim, cols, "B")
    b["ciSat"] = sat_interval(b["est"], b["se"], b["dfSatterthwaite"])
    b["labelInterval"] = wider_interval(b["ci95"], b["ciSat"])
    vif_ = {t: vif(prim, cols, t) for t in ("B", "months")}
    vif_["corrBMonths"] = _r(float(np.corrcoef(prim["B"], prim["months"])[0, 1]), 3)
    dboot = _boot_with_degenerate(prim, cols, "B", "day")
    wboot = _boot_with_degenerate(prim, cols, "B", "wk")
    weeks_with_b = sorted(prim[prim["B"] == 1]["wk"].unique().tolist())
    sens_cols = [c for c in ["months", "step", "slow", "B", "T", "I", "soc", "socr", "lrest", "first"] if c == "B" or ind[c].nunique() > 1]      # constant columns (collinear with the intercept) are dropped
    sens = fit_term(ind, sens_cols, "B")
    out = {**base, "primary": res, "modelPrimary": b, "vif": vif_, "dayBootstrap": dboot, "weekBlockBootstrap": wboot, "weeksWithClassB": weeks_with_b,
           "sensitivityFullModelAplusB": sens, "interpretation": "associated with, conditional on the stated covariates; header-derived, post hoc class; no PID-set effect and no cadence effect is claimed"}
    rec = next((x for x in led["looks"] if x["masterMd5"] == master_md5), None)
    if rec is None:
        rec = {"masterMd5": master_md5, "look": 1 + len(led["looks"]), "classBDrives": pn, "classBDays": pdays}
        led["looks"].append(rec)
    terminal_now = bool(pn >= PID_TERM_DRIVES and pdays >= PID_TERM_DAYS) or bool(ind["date"].max() >= pd.Timestamp(PID_TERM_FALLBACK))
    out["look"] = rec["look"]
    if led["terminal"] is not None:
        out["terminal"] = led["terminal"]
        out["status"] = "after the terminal evaluation; descriptive"
    elif not terminal_now:
        out["status"] = "descriptive look %d; no ladder label" % rec["look"]
    else:
        if vif_["B"] is None or vif_["B"] > VIF_LIMIT:
            lab = "not separable"
        elif not (dboot["evaluable"] and wboot["evaluable"]):
            lab = "not evaluable"
        else:
            A_ = {"est": b["est"], "ci95": b["labelInterval"]}
            lab, _m = label_term(A_, {"dayBootstrap": dboot["ci95"], "weekBlock": wboot["ci95"]}, vif_["B"], gate_vif=True)
        out["status"] = "terminal evaluation"
        out["label"] = lab
        led["terminal"] = {"look": rec["look"], "masterMd5": master_md5, "label": lab, "estimate": b["est"], "labelInterval": b["labelInterval"], "specRev2Sha256": spec_sha}
        out["terminal"] = led["terminal"]
    if write:
        with open(ledger_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(led, f, indent=1)
    return out, led


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "analyses", "M577_levels.json"))
    ap.add_argument("--pid-class", action="store_true", help="M577 Rev 2: run the class-B test (refuses below the floors); writes analyses/M577_pid_class.json unless --out is given")
    a = ap.parse_args()
    mp = os.path.join(ROOT, "drive_master.csv")
    before = m573.md5(mp)
    r2 = os.path.join(ROOT, "analyses", "M577_spec_rev2.md")
    r2sha = m573.sha256(r2) if os.path.exists(r2) else None
    if a.pid_class:
        dm = pd.read_csv(mp, low_memory=False)
        d_ = m573.build_frame(dm).dropna(subset=["soc", "socr", "lrest", "I_sample_period_s"]).copy()
        side = pd.read_csv(os.path.join(ROOT, "pid_epoch.csv"))
        ready = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))["pidEpoch"]["q3Readiness"]
        res, _ = pid_class_run(d_, side, ready, before, master=dm[["file", "date"]], spec_sha=r2sha)
        out_path = a.out if a.out != os.path.join(ROOT, "analyses", "M577_levels.json") else os.path.join(ROOT, "analyses", "M577_pid_class.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)
        print(json.dumps({"status": res.get("status"), "inFrame": res.get("inFrame")}))
        return
    res = run(pd.read_csv(mp))
    res = {"milestone": "M577", "spec": "analyses/M577_spec.md Rev 1", "specSha256": m573.sha256(os.path.join(ROOT, "analyses", "M577_spec.md")), "masterMd5": before, "masterMd5After": m573.md5(mp),
           "specRev2": "analyses/M577_spec_rev2.md", "specRev2Sha256": r2sha, "scriptSha256": m573.sha256(os.path.abspath(__file__)), "seed": SEED, "draws": NBOOT, **res}
    assert res["masterMd5"] == res["masterMd5After"]
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    print(json.dumps({"n": res["frame"]["nAnalysis"], "days": res["frame"]["days"], "labels": res["labels"], "q3": res["q3Pid"]["label"]}, indent=1))


if __name__ == "__main__":
    main()
