"""M614 descriptive replay (spec analyses/M614_spec.md Rev 1 section 5 and R8). Declared before it was run; it never selects or tunes a threshold, it may only veto (section 8 / R9, R10).
Prefixes of the corpus end on whole calendar days. Grid: the first calendar day at which the cumulative count of eligible resistanceVreg drives (canonical-clean, non-null outcome and covariates)
reaches 100, 110, ..., up to the current eligible count; plus the historic corpora of 289, 632 and 665 drives (first N master rows by date, extended to the end of that calendar day).
For each prefix: the RETIRED rule (degradation_trends.legacy_primary) and its components, group variance, variance ratio, SE ratio, both slopes and 95 % intervals, headlineVsMixed.
Flips = grid points at which the retired rule's primary differs from the previous point; under the shipped rule (fixed OLS) the count is zero by construction.
Prefixes are cumulative, not independent: counts are descriptive, no interval is attached. Output: analyses/M614_replay.json."""
import json, os, sys, warnings
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import numpy as np, pandas as pd, scipy, statsmodels
import degradation_trends as DT

YCOL, ICOL, COVARS = "vreg_R_pack_mohm", "vreg_I_p95_A", ("T", "I")
MIN_DAYS_BINDING = 30          # R9: the divergence criterion binds at the current corpus and at points with at least this many eligible days
DIV_LIMIT = 1.0                # R9: one OLS standard error


def point(dm, end_day, label):
    sub = dm[pd.to_datetime(dm["date"]) <= end_day]
    d = DT._prep(sub, YCOL, icol=ICOL)
    d = d.dropna(subset=["T", "I"])
    if d.shape[0] < 12:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mm = DT._mixedlm(d, COVARS)
        co = DT._cluster_ols(d, COVARS)
    prim, me_ok = DT.legacy_primary(mm, co)
    comp, re_sing = DT.validity_components(mm, co)
    gv, rv = mm.get("groupVar"), mm.get("residVar")
    return {"label": label, "endDay": str(end_day.date()), "nDrives": int(d.shape[0]), "nDays": int(d["day"].nunique()), "legacyPrimary": prim, "legacyMeOk": me_ok, "components": comp,
            "reCovarianceSingular": re_sing, "mixedError": mm.get("error"), "mixedConverged": mm.get("converged"), "groupVar": gv, "varianceRatio": (round(gv / rv, 4) if gv is not None and rv else None),
            "seRatioToOLS": (round(mm["se"] / co["se"], 3) if comp["seFinitePositive"] and co.get("se") else None),
            "olsSlope": co["slope"], "olsCI95": co["ci95"], "mixedSlope": mm.get("slope"), "mixedCI95": mm.get("ci95"),
            "headlineVsMixed": (round((mm["slope"] - co["slope"]) / co["se"], 3) if comp["fitted"] and co["se"] else None),
            "ciDisagreeOnZero": (None if not comp["fitted"] else bool((mm["ci95"][0] > 0 or mm["ci95"][1] < 0) != (co["ci95"][0] > 0 or co["ci95"][1] < 0)))}


def main():
    dm = pd.read_csv("drive_master.csv")
    dm["date"] = pd.to_datetime(dm["date"])
    elig = dm[~dm["ens_outlier_v2"].astype(str).str.lower().isin(["true", "1"])].dropna(subset=[YCOL, "T_pack_mean_avg", ICOL]).sort_values("date")
    n_elig = len(elig)
    pts = []
    daily = elig.groupby(elig["date"].dt.normalize()).size().cumsum()
    for target in list(range(100, n_elig, 10)) + [n_elig]:
        end = daily[daily >= target].index[0]
        pts.append(point(dm, end, "eligible>=%d" % target))
    ordered = dm.sort_values("date").reset_index(drop=True)
    hist = {}
    for n in (289, 632, 665):
        if n <= len(ordered):
            end = pd.to_datetime(ordered.loc[n - 1, "date"]).normalize()
            hist[str(n)] = point(dm, end, "master first %d drives (to end of day)" % n)
    pts = [p for p in pts if p]
    uniq, last = [], None
    for p in pts:
        key = (p["endDay"], p["nDrives"])
        if key != last:
            uniq.append(p); last = key
    prim = [p["legacyPrimary"] for p in uniq]
    flips = sum(1 for a, b in zip(prim, prim[1:]) if a != b)
    binding = [p for p in uniq if p["nDays"] >= MIN_DAYS_BINDING]
    cur = uniq[-1]
    maxdiv = max((abs(p["headlineVsMixed"]) for p in binding if p["headlineVsMixed"] is not None), default=None)
    res = {"milestone": "M614", "spec": "analyses/M614_spec.md Rev 1", "masterMd5": __import__("hashlib").md5(open("drive_master.csv", "rb").read()).hexdigest(),
           "versions": {"statsmodels": statsmodels.__version__, "scipy": scipy.__version__, "numpy": np.__version__, "pandas": pd.__version__},
           "nEligible": n_elig, "grid": uniq, "historic": hist, "flipsRetiredRule": flips, "flipsShippedRule": 0,
           "maxAbsHeadlineVsMixedBinding": maxdiv, "bindingPoints": len(binding), "criterion": {"limitOLSse": DIV_LIMIT, "minDaysBinding": MIN_DAYS_BINDING},
           "currentCorpus": {"headlineVsMixed": cur["headlineVsMixed"], "ciDisagreeOnZero": cur["ciDisagreeOnZero"]},
           "veto": bool((maxdiv is not None and maxdiv > DIV_LIMIT) or cur["ciDisagreeOnZero"]),
           "note": "descriptive; cumulative prefixes are not independent; no threshold is read off these counts"}
    json.dump(res, open("analyses/M614_replay.json", "w", encoding="utf-8", newline="\n"), indent=1, default=float)
    print(json.dumps({k: res[k] for k in ("nEligible", "flipsRetiredRule", "maxAbsHeadlineVsMixedBinding", "bindingPoints", "currentCorpus", "veto")}, default=float))
    print(json.dumps({k: (v and {x: v[x] for x in ("nDrives", "nDays", "legacyPrimary", "reCovarianceSingular", "varianceRatio", "headlineVsMixed")}) for k, v in hist.items()}, default=float))


if __name__ == "__main__":
    main()
