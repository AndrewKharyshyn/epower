#!/usr/bin/env python3
"""M709 (spec analyses/M708_spec.md Rev 2): parked-cooling model of the restart pack temperature (E3, E4) and its gates P-R3 / P-R4.
Reads the production census endpoints (analyses/M709/restart_endpoints.csv from tools/restart_census.py) and rebuilds the pair table with the census code and the driver-recorded vehicle-sensor ambient (summary_config.json
ambientByDrive: start and end reading per drive; uncalibrated, heat-soaked while parked, read only while driving). All temperatures at restart predicted here are model-derived; MAE is against the
logged probe readings (4-probe mean). Fresh code: nothing is imported from analyses/ (the exploratory ambient CSV may be read as comparison-only data).
Models: M1 persistence; M1b exponential to the recorded ambient (reported); M2 one state, diurnal-sinusoid boundary with a linear ambient trend and a fitted offset (spec section 3):
  G = 1/sqrt(1+(W tau)^2), phi = arctan(W tau), W = 2 pi/24 per h; part(x) = Abar0 + slope x + offset - slope tau + G amp cos(W (clock0 + x - hpk) - phi);
  T_start = part(g) + (T_end - part(0)) exp(-g/tau). The two-state model M3 (P-R2) is NOT part of this module yet (open item of milestone M709).
Fit: least squares on non-flagged eligible pairs, bounds tau [0.5, 60] h, offset [-10, 15] C; day-clustered bootstrap (seed 42) for the parameters; validation fit May-Aug, test Sep-Nov (NOT a clean
hold-out: spec section 3, C2). Usage: python tools/park_model.py [--dir analyses/M709] [--exploratory-ambient CSV]"""
import argparse, json, os, sys
import numpy as np
import pandas as pd
from scipy.optimize import least_squares

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import restart_census as RC

W = 2 * np.pi / 24.0
LO, HI, X0 = np.array([0.5, -10.0]), np.array([60.0, 15.0]), np.array([8.0, 1.0])
SEED, NBOOT = RC.SEED, RC.NBOOT
GC = RC.GAP_LAB


def park_T(T0, g, clock0, Abar0, slope, amp, hpk, tau, off):
    G = 1.0 / np.sqrt(1 + (W * tau) ** 2)
    phi = np.arctan(W * tau)
    part = lambda x: Abar0 + slope * x + off - slope * tau + G * amp * np.cos(W * (clock0 + x - hpk) - phi)
    return part(g) + (T0 - part(0.0)) * np.exp(-g / tau)


# ---------------------------------------------------------------- ambient reconstruction (model-derived) ----------------------------------------
def ambient_samples(E):
    """Per drive: ambient at start (clock h0) and at end (clock h1 = h0 + duration) from summary_config ambientByDrive; day label = local start date."""
    cfg = json.load(open(os.path.join(ROOT, "summary_config.json"), encoding="utf-8"))
    amb = {RC.key14(f): v for f, v in cfg.get("ambientByDrive", {}).items()}
    rows = []
    for _, r in E.iterrows():
        v = amb.get(r["key"])
        if isinstance(v, (int, float)) and not isinstance(v, bool):      # a single reading per drive (66 entries): start = end
            v = [v]
        if not isinstance(v, list) or len(v) < 1 or v[0] is None:
            continue
        a0 = float(v[0]); a1 = float(v[-1]) if v[-1] is not None else a0
        h0 = r["local0"].hour + r["local0"].minute / 60 + r["local0"].second / 3600
        rows.append({"key": r["key"], "day": r["day"], "month": int(r["day"][5:7]), "h0": h0, "h1": h0 + r["dur_s"] / 3600, "A0": a0, "A1": a1})
    return pd.DataFrame(rows)


def _fit_diurnal(df):
    """amp, hpk by least squares of the within-day deviation of the ambient on cos/sin of the clock hour (day fixed effects)."""
    x = []
    y = []
    for _, g in df.groupby("day"):
        h = np.r_[g["h0"].values, g["h1"].values]
        a = np.r_[g["A0"].values, g["A1"].values]
        x.append(np.c_[np.cos(W * h), np.sin(W * h)] - np.c_[np.cos(W * h), np.sin(W * h)].mean(0))
        y.append(a - a.mean())
    x, y = np.vstack(x), np.concatenate(y)
    b, *_ = np.linalg.lstsq(x, y, rcond=None)
    return float(np.hypot(*b)), float((np.arctan2(b[1], b[0]) / W) % 24)


def reconstruct_ambient(E):
    """Abar_s, Abar_e per drive (ambient with the diurnal term removed), amp and hpk per season (May-Aug summer, Sep-Nov autumn)."""
    A = ambient_samples(E)
    A["season"] = np.where(A["month"] <= 8, "summer", "autumn")
    par = {}
    for s, g in A.groupby("season"):
        par[s] = _fit_diurnal(g)
    A["amp"] = A["season"].map(lambda s: par[s][0])
    A["hpk"] = A["season"].map(lambda s: par[s][1])
    A["Abar_s"] = A["A0"] - A["amp"] * np.cos(W * (A["h0"] - A["hpk"]))
    A["Abar_e"] = A["A1"] - A["amp"] * np.cos(W * (A["h1"] - A["hpk"]))
    return A, {k: {"amp": round(v[0], 3), "hpk": round(v[1], 3)} for k, v in par.items()}


def model_frame(E, P):
    """One row per eligible, non-flagged-or-flagged pair with the model inputs; `use` marks the fit set (non-flagged, all inputs finite)."""
    A, par = reconstruct_ambient(E)
    Ai = A.set_index("key")
    D = P.copy()
    for c in ("Abar_s", "Abar_e", "amp", "hpk", "h0", "h1", "A0", "A1"):
        D["p_" + c] = D["p_key"].map(Ai[c])
        D["n_" + c] = D["n_key"].map(Ai[c])
    pe = D[["p_%s_e" % p for p in RC.PROBES]].values
    ns = D[["n_%s_s" % p for p in RC.PROBES]].values
    D["x0"] = np.where(np.isfinite(pe).all(1), pe.mean(1), np.nan)
    D["y"] = np.where(np.isfinite(ns).all(1), ns.mean(1), np.nan)
    D["amb_mid"] = (D["p_A1"] + D["n_A0"]) / 2
    D["slope"] = (D["n_Abar_s"] - D["p_Abar_e"]) / D["gap_h"].clip(lower=1e-3)
    D["clock0"] = D["p_h1"] % 24
    D["month"] = D["n_day"].str[5:7].astype(int)
    ok = D[["x0", "y", "p_Abar_e", "n_Abar_s", "p_amp", "p_hpk", "p_h1", "gap_h"]].notna().all(axis=1)
    D["usable"] = D["elig"] & ok
    D["use"] = D["usable"] & ~D["flagged"]
    return D, par


def predict(D, tau, off):
    return park_T(D["x0"].values, D["gap_h"].values, D["clock0"].values, D["p_Abar_e"].values, D["slope"].values, D["p_amp"].values, D["p_hpk"].values, tau, off)


def fit(D, w=None):
    sw = np.ones(len(D)) if w is None else np.sqrt(w)
    f = lambda th: (predict(D, th[0], th[1]) - D["y"].values) * sw
    o = least_squares(f, X0, bounds=(LO, HI))
    return o.x


def boot_params(D, nboot=NBOOT, seed=SEED):
    """Day-clustered bootstrap of (tau, offset): whole days resampled (as integer day weights in a weighted least squares)."""
    days, inv = np.unique(D["day"].values, return_inverse=True)
    Wt = np.random.default_rng(seed).multinomial(len(days), np.ones(len(days)) / len(days), size=nboot)
    out = np.empty((nboot, 2))
    for b in range(nboot):
        w = Wt[b][inv].astype(float)
        keep = w > 0
        out[b] = fit(D[keep], w[keep])
    return out


def mae_by_class(D, pred):
    e = np.abs(pred - D["y"].values)
    r = {}
    for lab in GC:
        m = (D["gc"] == lab).values
        r[lab] = round(float(e[m].mean()), 4) if m.any() else None
    m = D["gc"].isin(GC[:2]).values
    r["<1 h"] = round(float(e[m].mean()), 4) if m.any() else None
    r["n"] = {lab: int((D["gc"] == lab).sum()) for lab in GC}
    return r


def paired_mae_diff(D, pa, pb, nboot=NBOOT, seed=SEED):
    """Day-clustered interval of mean(|pa - y|) - mean(|pb - y|) on pooled pairs of the given frame (negative = a better)."""
    d = np.abs(pa - D["y"].values) - np.abs(pb - D["y"].values)
    r = RC.boot_mean(D["day"].values, d, nboot, seed)
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}


def evaluate(E, P, exploratory_ambient=None):
    D, par = model_frame(E, P)
    F = D[D["use"]].copy()
    res = {"ambientReconstruction": par, "support": {"pairsEligible": int(D["elig"].sum()), "flaggedUnloggedUseAmongEligible": int((D["elig"] & D["flagged"]).sum()),
                                                    "removedNoAmbientOrInput": int((D["elig"] & ~D["usable"]).sum()), "modelPairs": int(len(F)), "modelDays": int(F["day"].nunique()),
                                                    "byGapClass": {k: int(v) for k, v in F.groupby("gc").size().items()}}}
    th = fit(F)
    bp = boot_params(F)
    res["M2_fullSample_nonFlagged"] = {"tau_h": round(float(th[0]), 3), "tauCi": [round(float(np.percentile(bp[:, 0], 2.5)), 3), round(float(np.percentile(bp[:, 0], 97.5)), 3)],
                                      "offset_C": round(float(th[1]), 3), "offsetCi": [round(float(np.percentile(bp[:, 1], 2.5)), 3), round(float(np.percentile(bp[:, 1], 97.5)), 3)],
                                      "nPairs": int(len(F)), "nDays": int(F["day"].nunique()), "bootDraws": NBOOT}
    K = D[D["usable"]].copy()                                  # flagged pairs kept (contamination check)
    thk = fit(K)
    res["M2_flaggedKept"] = {"tau_h": round(float(thk[0]), 3), "offset_C": round(float(thk[1]), 3), "nPairs": int(len(K)), "nDays": int(K["day"].nunique())}
    # validation: fit May-Aug, test Sep-Nov (not a clean hold-out)
    tr, te = F[F["month"] <= 8], F[F["month"] >= 9]
    tho = fit(tr)
    p2, p1 = predict(te, *tho), te["x0"].values
    res["validation_fitMayAug_testSepNov"] = {"tau_h": round(float(tho[0]), 3), "offset_C": round(float(tho[1]), 3), "nTrain": int(len(tr)), "nTest": int(len(te)), "nTestDays": int(te["day"].nunique()),
                                              "MAE_M2": mae_by_class(te, p2), "MAE_persistence": mae_by_class(te, p1),
                                              "M2_minus_persistence_lt1h": paired_mae_diff(te[te["gc"].isin(GC[:2])], p2[te["gc"].isin(GC[:2]).values], p1[te["gc"].isin(GC[:2]).values]),
                                              "note": "not a clean hold-out: ambient amp/hpk fitted on the whole corpus; model form and gap classes chosen after full-sample results; split confounded with slow polling and the software update"}
    # E4 cold-start counts (full-sample fit, all model pairs)
    pf = predict(F, *th)
    cnt = {}
    for lab, op in (("below15C", lambda a: a < 15), ("below10C", lambda a: a < 10), ("atOrAbove35C", lambda a: a >= 35)):
        cnt[lab] = {"predicted": int(op(pf).sum()), "logged": int(op(F["y"].values).sum())}
    near = F[(F["y"] >= 12) & (F["y"] <= 18)]
    cnt["biasNear15C_C"] = round(float((predict(near, *th) - near["y"].values).mean()), 3) if len(near) else None
    res["E4_coldStartCounts"] = cnt
    # gates
    te_m = res["validation_fitMayAug_testSepNov"]
    pers, m2 = te_m["MAE_persistence"], te_m["MAE_M2"]
    red = lambda lab: None if pers[lab] in (None, 0) or m2[lab] is None else round(1 - m2[lab] / pers[lab], 3)
    four12 = [red("1-4 h")]
    ge4 = {"4-12 h": red("4-12 h"), ">=12 h": red(">=12 h")}
    p3b = {"reductionVsPersistence": {"1-4 h": red("1-4 h"), **ge4}, "lt1h": {"M2": m2["<1 h"], "persistence": pers["<1 h"]}}
    p3b["pass"] = bool(four12[0] is not None and four12[0] >= 0.30 and all(v is not None and v >= 0.70 for v in ge4.values()) and m2["<1 h"] is not None and m2["<1 h"] <= pers["<1 h"])
    amb_match = None
    if exploratory_ambient and os.path.exists(exploratory_ambient):
        X = pd.read_csv(exploratory_ambient, dtype={"key": str}).set_index("key")
        A, _ = reconstruct_ambient(E)
        J = A.set_index("key").join(X[["Abar_s", "Abar_e", "amp", "hpk"]], rsuffix="_x", how="inner")
        d = {"nDrives": int(len(J)), "maxAbsAbar_s": round(float((J["Abar_s"] - J["Abar_s_x"]).abs().max()), 3), "maxAbsAbar_e": round(float((J["Abar_e"] - J["Abar_e_x"]).abs().max()), 3),
             "medianAbsAbar_s": round(float((J["Abar_s"] - J["Abar_s_x"]).abs().median()), 3), "ampDiffMax": round(float((J["amp"] - J["amp_x"]).abs().max()), 3), "hpkDiffMax": round(float((J["hpk"] - J["hpk_x"]).abs().max()), 3)}
        amb_match = bool(d["maxAbsAbar_s"] <= 0.25 and d["maxAbsAbar_e"] <= 0.25 and d["ampDiffMax"] <= 0.1 and d["hpkDiffMax"] <= 0.25)
        d["matches(maxAbsAbar<=0.25C, amp<=0.1C, hpk<=0.25h)"] = amb_match
        res["ambientComparisonWithExploratory"] = d
    t = json.load(open(os.path.join(ROOT, "analyses", "M708_targets.json"), encoding="utf-8"))["E3"]
    p3a = None
    if amb_match:
        p3a = {"pass": all(abs(m2[k] - t["holdoutMAE_C"][k]) <= 0.05 for k in t["holdoutMAE_C"] if m2.get(k) is not None), "target": t["holdoutMAE_C"], "production": {k: m2[k] for k in t["holdoutMAE_C"]}}
    dirn = bool(thk[0] < th[0] and thk[1] > th[1])
    band = bool(8.0 <= th[0] <= 10.5)
    res["gates"] = {"P-R3a": p3a if p3a is not None else {"pass": None, "note": "non-binding: production ambient reconstruction does not match the exploratory file or no comparison file given"},
                    "P-R3b": p3b,
                    "P-R4": {"contaminationDirection": {"pass": dirn, "nonFlagged": [round(float(th[0]), 3), round(float(th[1]), 3)], "flaggedKept": [round(float(thk[0]), 3), round(float(thk[1]), 3)]},
                             "tauBand8to10.5h": {"pass": band if amb_match else None, "tau_h": round(float(th[0]), 3), "binding": bool(amb_match)}},
                    "P-R2": {"pass": None, "note": "two-state model M3 not implemented in this module yet; gate not evaluated"}}
    res["target_E3_exploratory"] = t
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(ROOT, "analyses", "M709"))
    ap.add_argument("--exploratory-ambient", default=os.path.join(ROOT, "analyses", "exposure_scenarios_2026-11-16", "results", "drive_ambient_recon.csv"))
    a = ap.parse_args(argv)
    E = pd.read_csv(os.path.join(a.dir, "restart_endpoints.csv"), dtype={"key": str}, low_memory=False)
    E["local0"] = pd.to_datetime(E["local0"], format="ISO8601")
    P = RC.build_pairs(E, RC.ambient_start_map())          # same pair table as the census (deterministic from the endpoints)
    res = evaluate(E, P, a.exploratory_ambient)
    res.update({"milestone": "M709", "spec": "analyses/M708_spec.md"})
    json.dump(res, open(os.path.join(a.dir, "park_model.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps({"M2": res["M2_fullSample_nonFlagged"], "flaggedKept": res["M2_flaggedKept"], "gates": {k: (v.get("pass") if "pass" in v else v) for k, v in res["gates"].items()}}, indent=1)[:2500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
