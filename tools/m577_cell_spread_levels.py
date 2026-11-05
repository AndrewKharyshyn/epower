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
    return {"est": _r(b), "se": _r(se), "ci95": [_r(b - tc * se), _r(b + tc * se)], "n": int(len(d)), "days": G, "G": G, "dfSatterthwaite": _r(df_sat, 2),
            "mde80": _r((tc + float(stats.t.ppf(0.8, G - 1))) * se), "unitLeverageClusters": fl["clustersWithUnitLeverage"]}


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
        labels[t] = {"label": lab, "modelsNotEvaluable": miss, "mde80_A": A[t]["mde80"], "vif": v[t]}

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "analyses", "M577_levels.json"))
    a = ap.parse_args()
    mp = os.path.join(ROOT, "drive_master.csv")
    before = m573.md5(mp)
    res = run(pd.read_csv(mp))
    res = {"milestone": "M577", "spec": "analyses/M577_spec.md Rev 1", "specSha256": m573.sha256(os.path.join(ROOT, "analyses", "M577_spec.md")), "masterMd5": before, "masterMd5After": m573.md5(mp),
           "scriptSha256": m573.sha256(os.path.abspath(__file__)), "seed": SEED, "draws": NBOOT, **res}
    assert res["masterMd5"] == res["masterMd5After"]
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    print(json.dumps({"n": res["frame"]["nAnalysis"], "days": res["frame"]["days"], "labels": res["labels"], "q3": res["q3Pid"]["label"]}, indent=1))


if __name__ == "__main__":
    main()
