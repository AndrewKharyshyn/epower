#!/usr/bin/env python3
"""M307 F1/F2 (spec: analyses/M307_f03_cellspread_spec.md). Calls degradation_trends._analyse UNCHANGED.
Usage: python tools/f03_followups.py PUBLISHED_MASTER.csv MASTER_A.csv MASTER_B.csv OUT.json [--subset-file SUBSET.json]
Outputs per dataset (P,A,B): full fit, leave-one-month-out (5 fits + max |slope change|), exclude-May-Jun, and for P the F1 stable-subset fit.
Subset definition is supplied by the caller (spec: identical spread in P and A; a Director-approved alternative may be passed)."""
import json, os, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
import degradation_trends as dt

Y = "cell_spread_loaded_p95_mv"


def fit(dm):
    """cellSpread fit = degradation_trends.build(dm)["cellSpread"]; returns the compact record."""
    r = dt.build(dm)["cellSpread"]        # unchanged production path (frozen bounds, covariates T+I)
    co, me = r.get("clusterRobustOLS", {}), r.get("mixedEffects", {})
    return {"nObs": r.get("nObs"), "nDays": r.get("nDays"), "windowMonths": r.get("windowMonths"),
            "primaryEstimator": r.get("primaryEstimator"),
            "olsSlope": co.get("slope"), "olsSE": co.get("se"), "olsCI95": co.get("ci95"),
            "mixedDegenerate": bool(me.get("degenerate", False)), "mixedSlope": me.get("slope"),
            "pTOST": (r.get("releasedEquivalence") or {}).get("pTOST"), "error": r.get("error")}


def month(dm):
    return dm["date"].astype(str).str[:7]


def run_dataset(dm, pub_ci):
    out = {"full": fit(dm), "leaveOneMonthOut": {}, "excludeMayJun": None}
    m = month(dm)
    slopes = []
    for mo in sorted(m.unique()):
        f = fit(dm[m != mo]); f["contains_published_slope"] = None
        out["leaveOneMonthOut"][mo] = f
        slopes.append(f["olsSlope"])
    base = out["full"]["olsSlope"]
    out["maxAbsSlopeChangeLOMO"] = None if base is None else round(max(abs(s - base) for s in slopes if s is not None), 4)
    out["excludeMayJun"] = fit(dm[~m.isin(["2026-05", "2026-06"])])
    for rec in list(out["leaveOneMonthOut"].values()) + [out["excludeMayJun"], out["full"]]:
        ci = rec.get("olsCI95")
        rec["ciContainsPublishedSlope"] = None if not ci else bool(ci[0] <= pub_ci["slope"] <= ci[1])
    n_unstable = sum(1 for r in list(out["leaveOneMonthOut"].values()) + [out["excludeMayJun"]] if r["ciContainsPublishedSlope"] is False)
    out["nSubsetFits"] = len(out["leaveOneMonthOut"]) + 1
    out["nUnstable"] = n_unstable
    return out


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    P, A, B = (pd.read_csv(a[i], low_memory=False) for i in range(3))
    pub_ci = {"slope": 0.0115, "ci": [-0.2892, 0.3122]}
    res = {"published_reference": pub_ci, "datasets": {}}
    for name, dm in (("P", P), ("A", A), ("B", B)):
        res["datasets"][name] = run_dataset(dm, pub_ci)
    # F1: stable subset (identical spread in P and A), selected by the caller-independent rule in the spec
    same = (P[Y].astype(float) - A[Y].astype(float)).abs().le(1e-9) | (P[Y].isna() & A[Y].isna())
    S = P[same.values]
    res["F1"] = {"rule": "identical cell_spread_loaded_p95_mv in P and A (|diff|<=1e-9)", "nDrivesSubset": int(same.sum()),
                 "nDrivesTotal": int(len(P)), "fit": fit(S),
                 "limits": "subset selected on the outcome difference itself: descriptive, not a confirmatory test"}
    ci = res["F1"]["fit"]["olsCI95"]
    res["F1"]["ciContainsPublishedSlope"] = None if not ci else bool(ci[0] <= pub_ci["slope"] <= ci[1])
    res["F1"]["ciOverlapsZero"] = None if not ci else bool(ci[0] <= 0 <= ci[1])
    json.dump(res, open(a[3], "w"), indent=1)
    print(json.dumps({"F1": {k: res["F1"][k] for k in ("nDrivesSubset", "ciContainsPublishedSlope", "ciOverlapsZero")},
                      **{n: {"nUnstable": d["nUnstable"], "of": d["nSubsetFits"], "maxAbsSlopeChangeLOMO": d["maxAbsSlopeChangeLOMO"]}
                         for n, d in res["datasets"].items()}}, indent=1))


if __name__ == "__main__":
    main()
