#!/usr/bin/env python3
"""Regime-stratified view and regime-covariate re-run of the gross-throughput decision figures (M380; analyses/M380_spec.md Rev 2, frozen before the run).
Read-only scratch analysis; nothing in the payload, the master or any estimator is changed. The logger-cadence regime comes from cadence_regime.csv (M379a);
the slow-equivalent ratios r come from analyses/M379_cadence_sensitivity.json (emulated sampling sensitivity, NOT a correction).
P1 cohort x regime table; P2 regime-stratified EnergyIntensity; P3 covariate re-run of the adjusted warm-vs-shoulder contrast (binary and 3-level regime indicator) with
identifiability diagnostics and within-regime contrasts; P4 slow-equivalent sensitivity (central r, r CI endpoints, stress bound, reverse direction) for EnergyIntensity and the contrasts;
P5 arithmetic only; P6 the cold-vs-warm Mann-Whitney on gtc per 100 km; P7 flip classification. Output: analyses/M380_regime_stratified.json.
Usage: python tools/regime_stratified.py [--out PATH]"""
import argparse, copy, glob, hashlib, json, os, re, sys, time
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.chdir(ROOT)
import cohort_arrays as CA
import seasonal_adjust as SA
import refresh_seasonal_kpis as RK
import m377_pin

dig = lambda s: re.sub(r"\D", "", str(s).rsplit(".", 1)[0])[:14]
RUN1_END = "2026-09-06"
OUTCOME = "gross_throughput_kwh_per100km"
QUARTER = 0.25


def regime_map():
    cr = pd.read_csv(os.path.join(ROOT, "cadence_regime.csv"))
    return {dig(f): r for f, r in zip(cr["file"], cr["regime"]) if isinstance(r, str)}


def attach(drives, rmap):
    for d in drives:
        r = rmap.get(dig(d["file"]))
        d["cad_regime"] = r
        d["cad_fast"] = None if r is None else (1.0 if r == "fast" else 0.0)
        d["cad_run1"] = None if r is None else (1.0 if (r == "fast" and str(d["date"])[:10] <= RUN1_END) else 0.0)
        d["cad_run2"] = None if r is None else (1.0 if (r == "fast" and str(d["date"])[:10] > RUN1_END) else 0.0)
    return drives


def scaled(drives, rmap_vals, which, r):
    """Copy of the drives with the gross throughput of one regime scaled by r (fast x r, or slow x 1/r for the reverse direction)."""
    out = copy.deepcopy(drives)
    for d in out:
        sel = (d.get("cad_regime") == "fast") if which == "fast" else (d.get("cad_regime") == "slow")
        if sel:
            for k in ("gross_throughput_kwh", OUTCOME):
                if d.get(k) is not None:
                    d[k] = d[k] * r
    return out


def ei_rows(rk_rows, rmap, factor_fast=1.0, factor_slow=1.0):
    rows = []
    for r in rk_rows:
        x = dict(r)
        g = rmap.get(dig(r["file"]))
        x["cad_regime"] = g
        if x["gross_throughput_kwh"] is not None:
            x["gross_throughput_kwh"] = x["gross_throughput_kwh"] * (factor_fast if g == "fast" else factor_slow if g == "slow" else 1.0)
        rows.append(x)
    return rows


def ei_block(rows):
    out = {}
    for key, pred in RK.COH:
        pool = [r for r in rows if pred(r)]
        c = RK.ratio_ci(RK.clean(pool)) if pool else None
        out[key] = None if c is None else {"value": c["point"], "lo": c["lo"], "hi": c["hi"], "n": c["n"], "clusters": c["clusters"]}
    return out


def ei_by_regime(rows):
    out = {}
    for key, pred in RK.COH:
        out[key] = {}
        for g in ("fast", "slow"):
            pool = [r for r in rows if pred(r) and r.get("cad_regime") == g]
            c = RK.ratio_ci(RK.clean(pool)) if pool else None
            out[key][g] = None if c is None else {"value": c["point"], "ci95": [c["lo"], c["hi"]], "nDrives": c["n"], "nDays": c["clusters"], "km": c["km"]}
    return out


def contrast(drives, covs, a="warm", b="shoulder", n_boot=2000, cohort_key="thermal_regime"):
    r = SA.adjusted_contrast(drives, OUTCOME, cohort_key, a, b, covariates=covs, n_boot=n_boot)
    keep = ("status", "reasonCode", "adjustedDiff", "rawDiff", "ci95", "nA", "nB", "nDays", "nDaysA", "nDaysB", "commonSupport", "nBoot", "covariates", "inputAudit")
    return {k: r.get(k) for k in keep}


def design_diag(drives, covs):
    P = SA._prepare(drives, OUTCOME, "thermal_regime", "warm", "shoulder", covs, "date", "drive_type")
    Z = P["Z"]
    if len(Z) < len(covs) + 3:
        return {"note": "too few rows"}
    Zs = (Z - Z.mean(0)) / np.where(Z.std(0) == 0, 1, Z.std(0))
    vif = {}
    for j, c in enumerate(covs):
        others = np.delete(Zs, j, axis=1)
        if others.shape[1] == 0:
            vif[c] = 1.0
            continue
        X = np.c_[np.ones(len(Zs)), others]
        beta, *_ = np.linalg.lstsq(X, Zs[:, j], rcond=None)
        res = Zs[:, j] - X @ beta
        r2 = 1 - res.var() / Zs[:, j].var() if Zs[:, j].var() > 0 else 0.0
        vif[c] = float(1 / (1 - r2)) if r2 < 1 else float("inf")
    return {"nRows": int(len(Z)), "conditionNumber": float(np.linalg.cond(Zs)), "vif": vif}


def cells(drives):
    d = pd.DataFrame([{"coh": x["thermal_regime"], "reg": x.get("cad_regime"), "date": str(x["date"])[:10], "thr": x.get("gross_throughput_kwh"), "km": x.get("distance_km")} for x in drives
                      if x.get("gross_throughput_kwh") is not None and (x.get("distance_km") or 0) > 0])
    t = d["thr"].sum()
    kmt = d["km"].sum()
    rows = []
    for (c, g), f in d.groupby(["coh", d["reg"].fillna("none")]):
        rows.append({"cohort": c, "regime": g, "nDrives": int(len(f)), "nDays": int(f["date"].nunique()), "shareOfCohortGrossThroughput": float(f["thr"].sum() / d[d.coh == c]["thr"].sum()),
                     "shareOfCohortKm": float(f["km"].sum() / d[d.coh == c]["km"].sum()), "nonIdentifiableCell": bool(f["date"].nunique() < 5)})
    return rows


def flips(orig, var):
    """Flip classification of a contrast variant against the original (Rev 2 P7)."""
    out = {"estimateDriven": [], "supportDriven": []}
    if orig["status"] != var["status"]:
        (out["supportDriven"] if (var.get("reasonCode") or orig.get("reasonCode")) else out["estimateDriven"]).append("status change %s -> %s" % (orig["status"], var["status"]))
        return out
    if var["status"] != "available":
        return out
    o_sig = not (orig["ci95"][0] <= 0 <= orig["ci95"][1])
    v_sig = not (var["ci95"][0] <= 0 <= var["ci95"][1])
    if o_sig != v_sig:
        out["estimateDriven"].append("CI side of 0 changes (%s -> %s)" % ("excludes 0" if o_sig else "includes 0", "excludes 0" if v_sig else "includes 0"))
    if np.sign(orig["adjustedDiff"]) != np.sign(var["adjustedDiff"]):
        out["estimateDriven"].append("sign of the adjusted difference changes")
    return out


def quarter_flag(orig_point, orig_lo, orig_hi, new_point):
    """Shift in units of the half-width on the side the estimate moves toward (Rev 2)."""
    shift = new_point - orig_point
    hw = (orig_hi - new_point * 0 - orig_point) if shift > 0 else (orig_point - orig_lo)
    return {"shift": float(shift), "halfWidthOnMovedSide": float(hw), "shiftOverHalfWidth": float(shift / hw) if hw else None,
            "class": "material to report (above the quarter-half-width rule)" if hw and abs(shift) > QUARTER * hw else "below the quarter-half-width rule (necessary, not sufficient)"}


def scan_inventory():
    """Script-written inventory claim: which files reference the gross-throughput family and which lines combine it with a trend / test token."""
    fam = re.compile(r"gross_throughput_kwh|\bgtc\b|\bfce\b|rf_efc|gross_discharge_kwh|gross_charge_kwh")
    trend = re.compile(r"polyfit|linregress|\bslope|cumsum|\bTOST\b|tost|mannwhitney|\bOLS\b|spearman|adjusted_contrast")
    files = sorted(glob.glob(os.path.join(ROOT, "*.py")) + glob.glob(os.path.join(ROOT, "tools", "*.py")))
    out = {"filesScanned": 0, "filesReferencingFamily": {}, "linesFamilyAndTrendOrTest": []}
    for p in files:
        try:
            lines = open(p, encoding="utf-8").read().split("\n")
        except Exception:
            continue
        out["filesScanned"] += 1
        n = 0
        for i, ln in enumerate(lines, 1):
            if ln.lstrip().startswith("#"):
                continue
            if fam.search(ln):
                n += 1
                near = chr(10).join(x for x in lines[max(0, i - 1 - 6):i + 6] if not x.lstrip().startswith("#"))      # +-6 lines: multi-line calls are common
                if trend.search(near):
                    out["linesFamilyAndTrendOrTest"].append("%s:%d" % (os.path.relpath(p, ROOT).replace(os.sep, "/"), i))
        if n:
            out["filesReferencingFamily"][os.path.relpath(p, ROOT).replace(os.sep, "/")] = n
    return out


def mwu_block(dm, rmap, f_fast=1.0, f_slow=1.0, regime=None):
    from scipy import stats as st
    d = dm[~(dm["ens_outlier_v2"].astype(str).str.strip().str.lower() == "true")].copy()
    d["reg"] = d["file"].map(lambda f: rmap.get(dig(f)))
    s = d[(d["distance_km"] < 5) & (d["distance_km"] > 0) & d["T_eng_coolant_max"].notna()].copy()
    s["gtc_s"] = s["gtc"] * np.where(s["reg"] == "fast", f_fast, np.where(s["reg"] == "slow", f_slow, 1.0))
    if regime:
        s = s[s["reg"] == regime]
    cold, warm = s[s["T_eng_coolant_max"] < 80], s[s["T_eng_coolant_max"] >= 80]
    a, b = (cold["gtc_s"] / cold["distance_km"] * 100).dropna(), (warm["gtc_s"] / warm["distance_km"] * 100).dropna()
    if len(a) < 5 or len(b) < 5:
        return {"nCold": int(len(a)), "nWarm": int(len(b)), "note": "fewer than 5 per arm"}
    return {"nCold": int(len(a)), "nWarm": int(len(b)), "medianCold": float(a.median()), "medianWarm": float(b.median()), "p": float(st.mannwhitneyu(a, b).pvalue),
            "descriptiveOnly": bool(min(len(a), len(b)) < 10)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "analyses", "M380_regime_stratified.json"))
    a = ap.parse_args()
    t0 = time.time()
    rmap = regime_map()
    study = json.load(open(os.path.join(ROOT, "analyses", "M379_cadence_sensitivity.json"), encoding="utf-8"))
    g2t = study["emulation"]["fast_to_slow"]["keys"]["gross_throughput_kwh"]
    r_c, r_lo, r_hi = g2t["estimate"], g2t["ci95"][0], g2t["ci95"][1]
    r_stress = study["emulation"]["fast_to_slower"]["keys"]["gross_throughput_kwh"]["estimate"]
    drives = attach(CA.load_drives(), rmap)
    rk_rows = RK.load()
    A = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
    pay_ei = A["seasonalCharts"]["charts"]["EnergyIntensity"]["data"]
    pay_adj = json.load(open(os.path.join(ROOT, "cohort_arrays.json"), encoding="utf-8"))["charts"]["EfficChart"]["adjusted"]     # the contrasts live in cohort_arrays.json (embedded by the build)
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    covs0 = list(CA.ADJ_COVARIATES)
    covs_b = covs0 + ["cad_fast"]
    covs_3 = covs0 + ["cad_run1", "cad_run2"]
    out = {"meta": {"milestone": "M380", "specSha256Frozen": m377_pin.spec_sha(os.path.join(ROOT, "analyses", "M380_spec.md")), "masterMd5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest(),
                    "ratios": {"central": r_c, "ciEndpoints": [r_lo, r_hi], "stressBound": r_stress, "source": "analyses/M379_cadence_sensitivity.json (emulated sampling sensitivity; uniform r over fast drives; not a correction)"},
                    "bootstrap": {"EI": {"B": RK.B, "seed": RK.SEED}, "contrast": {"nBoot": 2000, "seed": SA.BOOT_SEED}},
                    "scriptSha256": {"regime_stratified.py": hashlib.sha256(open(__file__, "rb").read()).hexdigest()[:16]}}}
    out["inventory"] = scan_inventory()
    # ---- P1 ----
    out["P1_cohortByRegime"] = cells(drives)
    # ---- reproduction of the published values ----
    ei0 = ei_block(ei_rows(rk_rows, rmap))
    out["reproduction"] = {"EI": {k: {"computed": ei0[k]["value"], "payload": pay_ei[k]["value"], "equal": abs(ei0[k]["value"] - pay_ei[k]["value"]) < 1e-9} for k in ("all", "warm", "shoulder") if ei0.get(k) and pay_ei.get(k)}}
    c0 = contrast(drives, covs0)
    pw = pay_adj["warm_vs_shoulder"]
    out["reproduction"]["warm_vs_shoulder"] = {"computedAdjustedDiff": c0["adjustedDiff"], "payloadAdjustedDiff": pw.get("adjustedDiff"), "equal": c0["adjustedDiff"] is not None and abs(c0["adjustedDiff"] - pw["adjustedDiff"]) < 1e-9,
                                               "computedCi95": c0["ci95"], "payloadCi95": pw.get("ci95")}
    out["warm_vs_cold"] = {"payloadStatus": pay_adj["warm_vs_cold"].get("status"), "payloadReason": pay_adj["warm_vs_cold"].get("reasonCode"), "note": "not available: the cold cohort is suppressed; no substitute is built"}
    # ---- P2 ----
    out["P2_regimeStratifiedEI"] = {"label": "observational; confounded by season, ambient and drive mix", "values": ei_by_regime(ei_rows(rk_rows, rmap)), "pooled": ei0}
    # ---- P3 ----
    p3 = {"original": c0, "binaryRegime": contrast(drives, covs_b), "threeLevelRegime": contrast(drives, covs_3),
          "diagnostics": {"originalDesign": design_diag(drives, covs0), "binaryDesign": design_diag(drives, covs_b), "threeLevelDesign": design_diag(drives, covs_3)}}
    p3["flips"] = {"binaryRegime": flips(c0, p3["binaryRegime"]), "threeLevelRegime": flips(c0, p3["threeLevelRegime"])}
    p3["withinRegime"] = {"label": "descriptive (secondary)", "fastOnly": contrast([d for d in drives if d.get("cad_regime") == "fast"], covs0), "slowOnly": contrast([d for d in drives if d.get("cad_regime") == "slow"], covs0)}
    p3["withinRegimeFlags"] = {"label": "descriptive flags only: a subset is a different population, not a variant of the same estimate; reported so that the Director can rule on them",
                               "fastOnly": flips(c0, p3["withinRegime"]["fastOnly"]), "slowOnly": flips(c0, p3["withinRegime"]["slowOnly"])}
    p3["regimePeriodContrast"] = {"label": "descriptive: composition-adjusted (speed, stationary %, % highway, distance, drive type) fast minus slow difference of gross throughput per 100 km WITHIN a thermal cohort; carries the regime period (within-season time, ambient, route), never a cadence effect",
                                  "warm": contrast([d for d in drives if d["thermal_regime"] == "warm"], covs0, "slow", "fast", cohort_key="cad_regime"),
                                  "shoulder": contrast([d for d in drives if d["thermal_regime"] == "shoulder"], covs0, "slow", "fast", cohort_key="cad_regime")}
    p3["interpretation"] = "the regime term carries a regime period (contiguous date block: within-season time, ambient and route), never a cadence effect"
    out["P3_covariateRerun"] = p3
    # ---- P4 ----
    variants = {"central_fastXr": ("fast", r_c), "ciLow_fastXr": ("fast", r_lo), "ciHigh_fastXr": ("fast", r_hi), "stress_fastXr": ("fast", r_stress),
                "reverse_central_slowX1overR": ("slow", 1.0 / r_c), "reverse_stress_slowX1overR": ("slow", 1.0 / r_stress)}
    p4 = {"label": "slow-equivalent / harmonisation sensitivity (emulated), not a correction; the stress bound is not a plausible range; uniform r over fast drives", "variants": {}}
    for name, (which, r) in variants.items():
        rows = ei_rows(rk_rows, rmap, factor_fast=r if which == "fast" else 1.0, factor_slow=r if which == "slow" else 1.0)
        eib = ei_block(rows)
        v = {"r": r, "EI": {}}
        for k in ("all", "warm", "shoulder"):
            if eib.get(k) and ei0.get(k):
                v["EI"][k] = {"value": eib[k]["value"], "ci95": [eib[k]["lo"], eib[k]["hi"]], **quarter_flag(ei0[k]["value"], ei0[k]["lo"], ei0[k]["hi"], eib[k]["value"])}
        dsc = scaled(drives, None, which, r)
        v["contrast_original_covariates"] = contrast(dsc, covs0)
        v["contrast_binaryRegime"] = contrast(dsc, covs_b)
        v["flips_original_covariates"] = flips(c0, v["contrast_original_covariates"])
        v["flips_binaryRegime_vs_binaryOriginal"] = flips(p3["binaryRegime"], v["contrast_binaryRegime"])
        if c0["status"] == "available" and v["contrast_original_covariates"]["status"] == "available":
            v["contrastShift"] = quarter_flag(c0["adjustedDiff"], c0["ci95"][0], c0["ci95"][1], v["contrast_original_covariates"]["adjustedDiff"])
        p4["variants"][name] = v
        print("P4", name, round(time.time() - t0), "s", flush=True)
    out["P4_slowEquivalent"] = p4
    # ---- P5 arithmetic ----
    ok = dm["gross_throughput_kwh"].notna() & (dm["distance_km"] > 0) & (dm["ens_outlier_v2"].astype(str).str.lower() != "true")
    dm["reg"] = dm["file"].map(lambda f: rmap.get(dig(f)))
    tot = float(dm.loc[ok, "gross_throughput_kwh"].sum())
    fast_share = float(dm.loc[ok & (dm["reg"] == "fast"), "gross_throughput_kwh"].sum() / tot)
    byc = {}
    for t, f in dm[ok].groupby("drive_type"):
        sh = float(f.loc[f["reg"] == "fast", "gross_throughput_kwh"].sum() / f["gross_throughput_kwh"].sum())
        byc[t] = {"nDrives": int(len(f)), "fastShareOfGrossThroughput": sh, "rateChangeIfFastXr_central": sh * (r_c - 1.0), "rateChangeIfSlowX1overR_central": (1 - sh) * (1.0 / r_c - 1.0)}
    out["P5_arithmetic"] = {"label": "arithmetic only; nothing recomputed; descriptive under the emulation", "corpusFastShareOfGrossThroughput": fast_share,
                            "corpusSumChange_fastXr": {"central": fast_share * (r_c - 1.0), "ciEndpoints": [fast_share * (r_lo - 1.0), fast_share * (r_hi - 1.0)], "stress": fast_share * (r_stress - 1.0)},
                            "corpusSumChange_reverse_slowX1overR": {"central": (1 - fast_share) * (1.0 / r_c - 1.0), "stress": (1 - fast_share) * (1.0 / r_stress - 1.0)},
                            "byDriveType": byc,
                            "projectionNote": "cycleLife / seasonalLife / fadeModes crossing years are driven by gtc per km times annual km: a relative change x of the rate scales a crossing year by about 1/(1+x) (proportionality, not a recompute)"}
    # ---- P6 ----
    base = mwu_block(dm.assign(), rmap)
    pay_cmp = A["riskColdEngineBattery"]["compare"]["gtcPer100km"]
    s = dm[~(dm["ens_outlier_v2"].astype(str).str.lower() == "true")]
    s = s[(s["distance_km"] < 5) & (s["distance_km"] > 0) & s["T_eng_coolant_max"].notna()].copy()
    s["reg"] = s["file"].map(lambda f: rmap.get(dig(f)))
    s["arm"] = np.where(s["T_eng_coolant_max"] < 80, "cold", "warm")
    ct = s.groupby(["arm", s["reg"].fillna("none")]).size().unstack(fill_value=0)
    p6 = {"reproduction": {"computedP": base.get("p"), "payloadP": pay_cmp.get("p"), "mediansComputed": [base.get("medianCold"), base.get("medianWarm")], "mediansPayload": [pay_cmp.get("cold"), pay_cmp.get("warm")]},
          "coolantByRegimeCrossTable": {a_: {b_: int(ct.loc[a_, b_]) for b_ in ct.columns} for a_ in ct.index},
          "variants": {"original": base, "fastXr_central": mwu_block(dm, rmap, f_fast=r_c), "fastXr_stress": mwu_block(dm, rmap, f_fast=r_stress), "reverse_central": mwu_block(dm, rmap, f_slow=1.0 / r_c),
                       "fastOnly": mwu_block(dm, rmap, regime="fast"), "slowOnly": mwu_block(dm, rmap, regime="slow")},
          "partialSpearmanBlock": {"included": False, "reason": "its inputs (T_eng_coolant_max, cell_spread_loaded_p95_adj_mv, vreg_R_pack_mohm, T_pack_mean_max) contain no gross-throughput column (script-listed)"},
          "damageK2PerKm": "not scaled: rf_damage_k2 is not covered by the emulation"}
    p6["flips"] = {k: (["p side of 0.05 changes"] if (v.get("p") is not None and base.get("p") is not None and ((v["p"] < 0.05) != (base["p"] < 0.05))) else []) for k, v in p6["variants"].items() if k != "original"}
    out["P6_mannWhitneyGtcPer100km"] = p6
    # ---- P7 classification ----
    allflips = []
    for k, v in p3["flips"].items():
        allflips += [("P3 " + k, x) for x in v["estimateDriven"] + v["supportDriven"]]
    for n_, v in p4["variants"].items():
        for fk in ("flips_original_covariates", "flips_binaryRegime_vs_binaryOriginal"):
            allflips += [("P4 %s %s" % (n_, fk), x) for x in v[fk]["estimateDriven"] + v[fk]["supportDriven"]]
    for k, v in p6["flips"].items():
        allflips += [("P6 " + k, x) for x in v]
    out["P7_classification"] = {"nFlips": len(allflips), "flips": allflips, "stopForDirector": bool(allflips),
                                "rule": "a flip in any direction (CI side of 0, sign, status; Mann-Whitney p side of 0.05), including a newly significant result, is a STOP for the Director"}
    out["meta"]["runtimeS"] = round(time.time() - t0)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, indent=1, ensure_ascii=False, default=float) + "\n")
    print("wrote", a.out, "flips:", len(allflips), "in", round(time.time() - t0), "s")


if __name__ == "__main__":
    main()
