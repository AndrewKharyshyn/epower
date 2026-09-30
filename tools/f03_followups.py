#!/usr/bin/env python3
"""M307 F1 / F1b / F2 / F4 (spec incl. Amendment 1: analyses/M307_f03_cellspread_spec.md). Calls degradation_trends.build() UNCHANGED.
Decision estimator for every rule: cluster-robust OLS, t(G-1) (mixed effects reported alongside, never used to decide). No day-bootstrap.
Usage: python tools/f03_followups.py PUBLISHED_MASTER.csv MASTER_A.csv MASTER_B.csv OUT.json   (XT_RAW_DIR for hash status)"""
import hashlib, json, os, re, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
import degradation_trends as dt
from scipy import stats

Y = "cell_spread_loaded_p95_mv"
PUB = {"slope": 0.0115, "ci": [-0.2892, 0.3122]}               # published clusterRobustOLS (analyses/F03; summary_arrays.json)
F1B_COLS = ["n_raw_rows", "duration_s", "distance_km", "gross_throughput_kwh", "gross_discharge_kwh", "gross_charge_kwh",
            "peak_discharge_kw", "peak_charge_kw", "peak_I_discharge", "peak_I_charge", "V_pack_median", "net_draw_kwh"]


def fit(dm):
    r = dt.build(dm)["cellSpread"]
    co, me = r.get("clusterRobustOLS", {}), r.get("mixedEffects", {})
    return {"nObs": r.get("nObs"), "nDays": r.get("nDays"), "windowMonths": r.get("windowMonths"),
            "olsSlope": co.get("slope"), "olsSE": co.get("se"), "olsCI95": co.get("ci95"),
            "mixedDegenerate": bool(me.get("degenerate", False)), "mixedSlope": me.get("slope"),
            "pTOST": (r.get("releasedEquivalence") or {}).get("pTOST"), "error": r.get("error")}


def contains(ci, x):
    return None if not ci or x is None else bool(ci[0] <= x <= ci[1])


def annotate(rec, full_slope):
    rec["ciContainsPublishedSlope"] = contains(rec.get("olsCI95"), PUB["slope"])
    rec["ciContainsOwnFullSlope"] = contains(rec.get("olsCI95"), full_slope)
    return rec


def month_of(dm):
    return dm["date"].astype(str).str[:7]


def run_dataset(dm):
    full = fit(dm)
    m = month_of(dm)
    out = {"full": annotate(full, full["olsSlope"]), "leaveOneMonthOut": {}}
    infl = []
    for mo in sorted(m.unique()):
        f = annotate(fit(dm[m != mo]), full["olsSlope"])
        f["influence_absDeltaSlope_over_fullSE"] = None if f["olsSlope"] is None else round(abs(f["olsSlope"] - full["olsSlope"]) / full["olsSE"], 3)
        infl.append(f["influence_absDeltaSlope_over_fullSE"]); out["leaveOneMonthOut"][mo] = f
    out["maxInfluence"] = max(i for i in infl if i is not None)
    out["excludeMayJun"] = annotate(fit(dm[~m.isin(["2026-05", "2026-06"])]), full["olsSlope"])
    fits = list(out["leaveOneMonthOut"].values()) + [out["excludeMayJun"]]
    out["nFitsCIContainPublished"] = sum(1 for f in fits if f["ciContainsPublishedSlope"])
    out["nFits"] = len(fits)
    out["confoundingNote"] = "month is confounded with hash status (no hash-verified drives in May-Jul): date effect and alteration effect are not separable"
    return out


def hash_status(files):
    raw = os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
    man = {re.sub(r"\D", "", r["raw_name"].rsplit(".", 1)[0]): r["sha256"]
           for r in json.load(open(os.path.join(ROOT, "raw_manifest.json")))["files"] if r["raw_name"] and r["role"] == "canonical"}
    idx = {re.sub(r"\D", "", f.rsplit(".", 1)[0]): f for f in os.listdir(raw) if f.lower().endswith(".csv")}
    ok = {}
    for f in files:
        k = re.sub(r"\D", "", f.rsplit(".", 1)[0])
        ok[f] = hashlib.sha256(open(os.path.join(raw, idx[k]), "rb").read()).hexdigest() == man[k]
    return ok


def subset_report(P, mask, label, own_full):
    S = P[mask.values]
    fitS = annotate(fit(S), own_full)
    clean = S[~S["ens_outlier_v2"].astype(str).eq("True")].dropna(subset=[Y])
    per_month = {mo: {"nDrives": int(len(g)), "nDays": int(g["date"].astype(str).nunique())}
                 for mo, g in clean.groupby(month_of(clean))}
    ci = fitS["olsCI95"]
    return {"label": label, "nDrivesSubset": int(mask.sum()), "nDrivesTotal": int(len(P)), "fit": fitS, "perMonth": per_month,
            "outcomes": {"containsPublishedSlope": contains(ci, PUB["slope"]),
                         "overlapsZero": contains(ci, 0.0),
                         "containsPublishedButExcludesZero": bool(contains(ci, PUB["slope"]) and not contains(ci, 0.0)),
                         "containsBothPublishedAndAFull": None}}


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    P, A, B = (pd.read_csv(a[i], low_memory=False) for i in range(3))
    # exclusion rule (Amendment 1): primary = P's ens_outlier_v2 for all datasets; secondary = A's own
    A_p = A.copy(); A_p["ens_outlier_v2"] = P["ens_outlier_v2"].values
    B_p = B.copy(); B_p["ens_outlier_v2"] = P["ens_outlier_v2"].values
    res = {"published_reference": PUB, "decisionEstimator": "clusterRobustOLS t(G-1); no day-bootstrap", "datasets": {}}
    for name, dm in (("P", P), ("A_Pexcl", A_p), ("A_ownExcl", A), ("B_Pexcl", B_p)):
        res["datasets"][name] = run_dataset(dm)
    a_full = res["datasets"]["A_Pexcl"]["full"]["olsSlope"]
    # F1: coincident-value subset (selected on the outcome difference itself: descriptive)
    same = ((P[Y].astype(float) - A[Y].astype(float)).abs().le(1e-9)) | (P[Y].isna() & A[Y].isna())
    f1 = subset_report(P, same, "identical cell_spread_loaded_p95_mv in P and A", a_full)
    f1["outcomes"]["containsBothPublishedAndAFull"] = bool(contains(f1["fit"]["olsCI95"], PUB["slope"]) and contains(f1["fit"]["olsCI95"], a_full))
    f1["outcomes"]["containsAFull"] = contains(f1["fit"]["olsCI95"], a_full)
    f1["limits"] = "subset selected on the outcome difference itself: descriptive, not a confirmatory test; subset where published and fresh values coincide"
    res["F1"] = f1
    # F1b: outcome-blind subset (hash-verified + hash-failing with zero P/A drift on the fixed column list)
    hv = pd.Series(hash_status(list(P["file"])), index=P["file"]).reindex(P["file"]).values
    drift = np.zeros(len(P), dtype=bool)
    for c in F1B_COLS:
        x, y = P[c].astype(float), A[c].astype(float)
        drift |= ((x - y).abs() > 1e-9).values | (x.isna() != y.isna()).values
    s_prime = pd.Series(hv | (~drift), index=P.index)
    f1b = subset_report(P, s_prime, "hash-verified OR zero drift on fixed non-cell-voltage column list", a_full)
    f1b["outcomes"]["containsBothPublishedAndAFull"] = bool(contains(f1b["fit"]["olsCI95"], PUB["slope"]) and contains(f1b["fit"]["olsCI95"], a_full))
    f1b["outcomes"]["containsAFull"] = contains(f1b["fit"]["olsCI95"], a_full)
    f1b["overlapWithF1"] = {"nBoth": int((s_prime.values & same.values).sum()), "nOnlyS": int((same.values & ~s_prime.values).sum()),
                            "nOnlySprime": int((s_prime.values & ~same.values).sum())}
    f1b["nHashVerified"] = int(hv.sum()); f1b["nHashFailing"] = int((~hv).sum())
    f1b["limits"] = "not conditioned on the outcome value but correlated with the alteration mechanism: descriptive"
    res["F1b"] = f1b
    # F4: hash-verified only, MDE (no slope claim)
    Hv = P[hv]
    f4 = fit(Hv)
    if f4["olsSE"] and f4["nDays"]:
        df = f4["nDays"] - 1
        f4["mde80_mV_per_mo"] = round(float((stats.t.ppf(0.975, df) + stats.t.ppf(0.80, df)) * f4["olsSE"]), 3)
    f4["note"] = "no May-Jul coverage; report MDE only, no trend claim"
    res["F4"] = f4
    json.dump(res, open(a[3], "w"), indent=1)
    print(json.dumps({"F1": {"n": f1["nDrivesSubset"], **f1["outcomes"], "slope": f1["fit"]["olsSlope"], "ci": f1["fit"]["olsCI95"]},
                      "F1b": {"n": f1b["nDrivesSubset"], **f1b["outcomes"], "slope": f1b["fit"]["olsSlope"], "ci": f1b["fit"]["olsCI95"]},
                      "F4": {k: f4.get(k) for k in ("nObs", "nDays", "olsSE", "mde80_mV_per_mo")},
                      "F2": {n: {"nFitsCIContainPublished": d["nFitsCIContainPublished"], "of": d["nFits"], "maxInfluence": d["maxInfluence"],
                                 "fullSlope": d["full"]["olsSlope"]} for n, d in res["datasets"].items()}}, indent=1))


if __name__ == "__main__":
    main()
