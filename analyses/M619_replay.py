"""M619 replay (spec analyses/M618_spec.md Rev 1 section 5 and R7-R9): the multi-solver mixed-effects sensitivity fit on whole-calendar-day prefixes of the corpus, for BOTH metrics. Declared before the
replay was run (only the current-corpus table of the resistance metric was seen during implementation, after the tolerances were fixed). It may VETO the procedure (degradation_trends.mixed_veto), never tune it.
Grid per metric: the first calendar day at which the cumulative count of that metric's eligible drives (canonical-clean, non-null outcome and covariates) reaches 100, 110, ... up to the current
eligible count, plus the current corpus; plus the historic corpora of 289, 632 and 665 master drives (first N master rows by date, extended to the end of that calendar day).
Per prefix and metric: every solver's outcome and failure stage, the reported solver, the agreement, the mixed-minus-OLS slope in OLS standard errors, whether the two 95 % intervals agree on excluding zero.
Prefixes are cumulative, not independent: shares are descriptive, no error rate is claimed. Output: analyses/M619_replay.json."""
import hashlib, json, os, sys, warnings
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import numpy as np, pandas as pd, scipy, statsmodels
import degradation_trends as DT

METRICS = {"resistanceVreg": ("vreg_R_pack_mohm", "vreg_I_p95_A"), "cellSpread": ("cell_spread_loaded_p95_mv", "peak_I_discharge")}
COVARS = ("T", "I")


def point(dm, ycol, icol, end_day, label):
    sub = dm[pd.to_datetime(dm["date"]) <= end_day]
    d = DT._prep(sub, ycol, icol=icol).dropna(subset=["T", "I"])
    if d.shape[0] < 12:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mm = DT._mixedlm(d, COVARS)
        co = DT._cluster_ols(d, COVARS)
    ex = lambda ci: bool(ci[0] > 0 or ci[1] < 0)
    fitted = "slope" in mm
    return {"label": label, "endDay": str(end_day.date()), "nObs": int(d.shape[0]), "nDays": int(d["day"].nunique()), "reported": mm.get("solver"), "agreement": mm.get("solverAgreement"),
            "maxSlopeDiffInOLSse": mm.get("maxSlopeDiffInOLSse"), "maxGroupVarOverResid": mm.get("maxGroupVarOverResid"),
            "solvers": [{k: t[k] for k in ("solver", "counts", "converged", "stage", "error", "logLik", "scoreNorm", "slope", "groupVar")} for t in mm["solversTried"]],
            "mixedSlope": mm.get("slope"), "olsSlope": co["slope"], "mixedCI95": mm.get("ci95"), "olsCI95": co["ci95"],
            "mixedMinusOlsInOlsSe": (round((mm["slope"] - co["slope"]) / co["se"], 3) if fitted and co["se"] else None),
            "intervalsAgreeOnExcludingZero": (ex(mm["ci95"]) == ex(co["ci95"])) if fitted else None}


def main():
    dm = pd.read_csv("drive_master.csv")
    dm["date"] = pd.to_datetime(dm["date"])
    per, veto_in, hist = {}, {}, {}
    ordered = dm.sort_values("date").reset_index(drop=True)
    for m, (ycol, icol) in METRICS.items():
        elig = dm[~dm["ens_outlier_v2"].astype(str).str.lower().isin(["true", "1"])].dropna(subset=[ycol, "T_pack_mean_avg", icol]).sort_values("date")
        daily = elig.groupby(elig["date"].dt.normalize()).size().cumsum()
        pts, last = [], None
        for target in list(range(100, len(elig), 10)) + [len(elig)]:
            end = daily[daily >= target].index[0]
            p = point(dm, ycol, icol, end, "eligible>=%d" % target)
            if p and (p["endDay"], p["nObs"]) != last:
                pts.append(p)
                last = (p["endDay"], p["nObs"])
        per[m] = pts
        hist[m] = {}
        for n in (289, 632, 665):
            if n <= len(ordered):
                hist[m][str(n)] = point(dm, ycol, icol, pd.to_datetime(ordered.loc[n - 1, "date"]).normalize(), "master first %d drives (to end of day)" % n)
        veto_in[m] = {"current": pts[-1]["agreement"], "points": [(p["nDays"], p["agreement"]) for p in pts]}
    v = DT.mixed_veto(veto_in)
    cur = {m: per[m][-1] for m in per}
    r9 = {"intervalsAgreeOnExcludingZeroBothMetrics": all(c["intervalsAgreeOnExcludingZero"] is True for c in cur.values()),
          "maxAbsMixedMinusOlsInOlsSeAtCurrent": max((abs(c["mixedMinusOlsInOlsSe"]) for c in cur.values() if c["mixedMinusOlsInOlsSe"] is not None), default=None)}
    res = {"milestone": "M619", "spec": "analyses/M618_spec.md Rev 1", "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(),
           "versions": {"statsmodels": statsmodels.__version__, "scipy": scipy.__version__, "numpy": np.__version__, "pandas": pd.__version__},
           "constants": {"solvers": list(DT.MIXED_SOLVERS), "maxiter": DT.MIXED_MAXITER, "llTol": DT.MIXED_LL_TOL, "scoreNormMax": DT.MIXED_SCORE_NORM_MAX, "agreeSlopeOlsSe": DT.MIXED_AGREE_SLOPE_OLS_SE, "agreeVarOverResid": DT.MIXED_AGREE_VAR_OVER_RESID},
           "grid": per, "historic": hist, "veto": v, "r9": r9, "noSignoffCondition": bool((not v["veto"]) and r9["intervalsAgreeOnExcludingZeroBothMetrics"]),
           "note": "descriptive; cumulative prefixes are not independent; the veto may stop the procedure, never retune it"}
    json.dump(res, open("analyses/M619_replay.json", "w", encoding="utf-8", newline="\n"), indent=1, default=float)
    print(json.dumps({"veto": v["veto"], "reasons": v["reasons"], "perMetric": v["perMetric"], "r9": r9}, default=float))
    for m in per:
        print(m, [(p["nObs"], p["agreement"], p["reported"]) for p in per[m]])


if __name__ == "__main__":
    main()
