#!/usr/bin/env python3
"""M499 (spec analyses/M499_spec.md Rev 2): temperature-specification sensitivity of the resistance-proxy trend (powerFade S1) and a tipping row.
Reads drive_master.csv, seasonal_drive_master.csv, powerfade_density.csv, summary_arrays.json (fidelity only). Read-only: writes only analyses/M499_result.json.
Usage: python tools/m499_temp_spec.py [--out analyses/M499_result.json] [--nb 4000]   |   --splice (ingestion stage: compute and write the additive payload block powerFadeTemperatureSpecs + stamp; does not write analyses/M499_result.json)"""
import datetime, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import powerfade_equivalence as PE
import day_bootstrap as DB

SEED, NB_DEFAULT, MONTH_DAYS = 42, 4000, 30.44
MIN_DRIVES, MIN_DAYS = 150, 50
TREF = "T_pack_mean_avg"
SPECS = ["T0", "T1", "T2", "T3", "T4", "T5"]


def cluster_boot(X, y, labels, coef, nb, seed):
    """Cluster percentile bootstrap of one OLS coefficient from per-cluster sufficient statistics (used for the ISO-week sensitivity, where t varies within a cluster, so
    tools/day_bootstrap.ols_boot_slopes does not apply). A draw whose normal equations are singular or whose cluster draw has fewer than 3 distinct clusters is dropped and counted."""
    uniq, di = np.unique(np.asarray(labels), return_inverse=True)
    G, p = len(uniq), X.shape[1]
    sc = np.sqrt((X ** 2).mean(axis=0)); sc[sc == 0] = 1.0
    Xs = X / sc
    A = np.zeros((G, p, p)); Bv = np.zeros((G, p))
    for g in range(G):
        r = di == g
        A[g] = Xs[r].T @ Xs[r]; Bv[g] = Xs[r].T @ y[r]
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(nb):
        pick = rng.integers(0, G, G)
        if len(set(pick.tolist())) < 3:
            continue
        XtX, Xty = A[pick].sum(axis=0), Bv[pick].sum(axis=0)
        if not np.isfinite(np.linalg.cond(XtX)) or np.linalg.cond(XtX) > 1e9:
            continue
        out.append(float(np.linalg.solve(XtX, Xty)[coef] / sc[coef]))
    return np.asarray(out)


def design(d, spec, t, knots=None):
    """Columns: const, months, <temperature terms>, I, de, dc. The months coefficient is column 1."""
    I, de, dc = d[PE.ICOL].values.astype(float), d["_de"].values.astype(float), d["_dc"].values.astype(float)
    T = d[TREF].values.astype(float)
    one = np.ones(len(d))
    if spec == "T0":
        tcols, names = [T], ["T"]
    elif spec == "T1":
        Tc = T - T.mean(); tcols, names = [Tc, Tc ** 2], ["T", "T2"]
    elif spec == "T2":
        k1, k2 = knots
        tcols, names = [T, np.maximum(T - k1, 0), np.maximum(T - k2, 0)], ["T", "hinge1", "hinge2"]
    elif spec == "T3":
        tcols, names = [d["pack_temp_start_c"].values.astype(float)], ["Tstart"]
    elif spec == "T4":
        tcols, names = [d["ambient_time_mean_c"].values.astype(float)], ["Tamb"]
    elif spec == "T5":
        tcols, names = [T, d["ambient_time_mean_c"].values.astype(float)], ["T", "Tamb"]
    X = np.column_stack([one, t] + tcols + [I, de, dc])
    return X, ["const", "months"] + names + ["I", "de", "dc"]


def fit(d, spec, t0, knots, nb):
    t = ((pd.to_datetime(d["date"]) - t0).dt.days / MONTH_DAYS).values
    X, names = design(d, spec, t, knots)
    y = d[PE.RCOL].values.astype(float)
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    out = {"spec": spec, "n": int(len(d)), "nDays": int(d["date"].nunique()), "slope": float(b[1]), "coefNames": names}
    iso = pd.to_datetime(d["date"]).dt.isocalendar()
    wk = (iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)).values
    out["nWeeks"] = int(len(set(wk)))
    for label, cl in (("day", d["date"].values), ("isoWeek", wk)):
        draws = DB.ols_boot_slopes(X, y, cl, coef=1, nb=nb, seed=SEED, t=t)[0] if label == "day" else cluster_boot(X, y, cl, 1, nb, SEED)
        q = np.percentile(draws, [2.5, 97.5])
        dropped = int(nb - len(draws))
        out[label] = {"ci95": [float(q[0]), float(q[1])], "includesZero": bool(q[0] <= 0 <= q[1]), "drawsUsed": int(len(draws)), "drawsDropped": dropped,
                      "nonDecisiveFailedDraws": bool(dropped > 0.01 * nb)}
    return out, X, y, t, names


def build_block(res):
    """Compact payload block (no bootstrap draws). Window dates and span are script-written."""
    specs = {}
    for k, v in res["specs"].items():
        specs[k] = {"n": v["n"], "nDays": v["nDays"], "nWeeks": v["nWeeks"], "slope": round(v["slope"], 4), "dayCi95": [round(x, 4) for x in v["day"]["ci95"]], "dayIncludesZero": v["day"]["includesZero"],
                    "weekCi95": [round(x, 4) for x in v["isoWeek"]["ci95"]], "weekIncludesZero": v["isoWeek"]["includesZero"], "decisive": bool(v.get("decisive", True)),
                    "temperatureTerms": [n for n in v["coefNames"] if n not in ("const", "months", "I", "de", "dc")]}
        if "pack_ambient" in v:
            specs[k]["packAmbient"] = v["pack_ambient"]
    t = res["tipping"]
    return {"label": "temperature-specification sensitivity of the resistance-proxy (vreg_R_pack_mohm) months coefficient, powerFade S1 design; estimated proxy, an association within one warm-season window, not a degradation rate",
            "spec": res["spec"], "specSha256": res["provenance"]["specSha256"], "scriptSha256": res["provenance"]["scriptSha256"], "masterMd5": res["provenance"]["masterMd5"],
            "seasonalMasterMd5": res["provenance"]["seasonalMasterMd5"], "seed": res["provenance"]["seed"], "nBoot": res["provenance"]["nBoot"], "window": res["window"], "fidelity": res["fidelity"], "specs": specs,
            "pairedT0": {k: {"slope": round(v["slope"], 4), "n": v["n"], "dayCi95": [round(x, 4) for x in v["day"]["ci95"]]} for k, v in res["pairedT0"].items()},
            "tipping": {"tauDegCPerMonth": t["tauDegCPerMonth"], "bT": t["bT"], "bTDayCi95": t["bTDayCi95"], "dZero": t["dZero"], "dZeroFractionOfAbsBT": None if t["dZero"] is None else round(abs(t["dZero"]) / abs(t["bT"]), 3),
                        "dZeroWithinBTDayCi": t["dZeroWithinBTDayCi"], "grid": {k: {"slope": g["slopeRefit"], "fractionOfAbsBT": g["fractionOfAbsBT"]} for k, g in t["grid"].items()}, "identity": t["identity"]},
            "decision": res["decision"], "decisionRule": "day-bootstrap interval of each decisive specification governs; week interval is a labelled sensitivity; 12 intervals, no multiplicity adjustment"}


def splice(res):
    import copy
    P = "summary_arrays.json"
    raw = open(P, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    blk = json.loads(json.dumps(build_block(res)))
    md5 = res["provenance"]["masterMd5"]
    old = (A.get("_artifactStamps") or {}).get("powerFadeTemperatureSpecs")
    coherent = old and old.get("includedInReleaseAt") == old.get("computedAt") == old.get("generatedAt")
    if A.get("powerFadeTemperatureSpecs") == blk and coherent and old.get("corpusHash") == md5:
        print(json.dumps({"changed": False}))
        return
    A["powerFadeTemperatureSpecs"] = blk
    st = copy.deepcopy(A["_artifactStamps"]["powerFadeEquivalence"])
    st.update(corpusHash=md5, generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M499: derived by tools/m499_temp_spec.py from drive_master.csv, seasonal_drive_master.csv and the tracked powerfade_density.csv (spec analyses/M499_spec.md Rev 2)", upstreamHashes={"driveMasterMd5": md5})
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A["_artifactStamps"]["powerFadeTemperatureSpecs"] = st
    with open(P, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print(json.dumps({"changed": True, "outcome": blk["decision"]["outcome"]}))


def main():
    out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "analyses/M499_result.json"
    nb = int(sys.argv[sys.argv.index("--nb") + 1]) if "--nb" in sys.argv else NB_DEFAULT
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False)[["file", "pack_temp_start_c", "ambient_time_mean_c"]]
    side = PE._read(PE.SIDECAR)
    dens = {r["file"]: (float(r["eff_dt_s"]) if pd.notna(r["eff_dt_s"]) else np.nan, float(r["coverage_frac"]) if pd.notna(r["coverage_frac"]) else np.nan) for r in side.to_dict("records")}
    cc, have_d = PE.s1_rows(dm, dens)
    t0 = pd.to_datetime(cc["date"]).min()
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    pf, pe = A["powerFade"], A["powerFadeEquivalence"]
    d = have_d.merge(sdm, on="file", how="left")
    knots = tuple(np.quantile(d[TREF].values.astype(float), [1 / 3, 2 / 3]))
    res = {"spec": "analyses/M499_spec.md",
           "provenance": {"masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(),
                          "seasonalMasterMd5": hashlib.md5(open("seasonal_drive_master.csv", "rb").read()).hexdigest(),
                          "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "specSha256": hashlib.sha256(open("analyses/M499_spec.md", "rb").read()).hexdigest(),
                          "seed": SEED, "nBoot": nb, "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "monthsScale": "days / 30.44 from the minimum date of the clean complete cases"}}
    # ---- T0 fit and fidelity stop
    f0, X0, y0, tt0, n0 = fit(d, "T0", t0, knots, nb)
    bT = float(np.linalg.lstsq(X0, y0, rcond=None)[0][2])
    chk = {"slope": round(f0["slope"], 4), "publishedSlope": pe["s1"]["slope"], "n": f0["n"], "publishedN": pf["nClean"], "nDays": f0["nDays"], "bT": round(bT, 3), "publishedBT": pf["bTMohmPerDegC"],
           "dayCi95": [round(x, 4) for x in f0["day"]["ci95"]], "publishedDayCi95": pf["ci95MohmPerMo"]}
    ok = (chk["slope"] == round(chk["publishedSlope"], 4) and chk["n"] == chk["publishedN"] and chk["nDays"] == 98 and chk["bT"] == round(chk["publishedBT"], 3)
          and [round(x, 3) for x in chk["dayCi95"]] == [round(x, 3) for x in chk["publishedDayCi95"]])
    res["fidelity"] = {**chk, "passed": bool(ok)}
    if not ok:
        print(json.dumps({"STOP": "fidelity", **chk}))
        sys.exit(2)
    rows = {"T0": f0}
    # ---- specifications on the full S1 population
    for s in ("T1", "T2"):
        rows[s] = fit(d, s, t0, knots, nb)[0]
    # ---- subset specifications with paired T0
    paired = {}
    for s, need in (("T3", ["pack_temp_start_c"]), ("T4", ["ambient_time_mean_c"]), ("T5", ["ambient_time_mean_c"])):
        sub = d.dropna(subset=need)
        r = fit(sub, s, t0, knots, nb)[0]
        r["decisive"] = bool(r["n"] >= MIN_DRIVES and r["nDays"] >= MIN_DAYS)
        r["overlapWithS1"] = {"nSubset": int(len(sub)), "nS1": int(len(d))}
        key = "T0_on_" + ("T3subset" if s == "T3" else "ambientSubset")
        if key not in paired:
            paired[key] = fit(sub, "T0", t0, knots, nb)[0]
        r["pairedT0"] = key
        rows[s] = r
        if s == "T5":
            a, b = sub[TREF].values.astype(float), sub["ambient_time_mean_c"].values.astype(float)
            r["pack_ambient"] = {"corr": round(float(np.corrcoef(a, b)[0, 1]), 3), "vif": round(float(1 / (1 - np.corrcoef(a, b)[0, 1] ** 2)), 2)}
    for r in rows.values():
        r.setdefault("decisive", True)
    res["specs"], res["pairedT0"] = rows, paired
    dts = pd.to_datetime(d["date"])
    res["window"] = {"firstDate": str(dts.min().date()), "lastDate": str(dts.max().date()), "spanDays": int((dts.max() - dts.min()).days) + 1, "spanMonths": round(float((dts.max() - dts.min()).days / MONTH_DAYS), 2)}
    # ---- tipping row (T0 design)
    Z = np.column_stack([np.ones(len(d)), tt0, d[PE.ICOL].values.astype(float), d["_de"].values.astype(float), d["_dc"].values.astype(float)])
    tau = float(np.linalg.lstsq(Z, d[TREF].values.astype(float), rcond=None)[0][1])
    bT_draws = DB.ols_boot_slopes(X0, y0, d["date"].values, coef=2, nb=nb, seed=SEED, t=tt0)[0]
    bq = np.percentile(bT_draws, [2.5, 97.5])
    s0 = f0["slope"]
    grid = {}
    for dd in (-1.0, -0.5, 0.5, 1.0):
        Zd = np.delete(X0, 2, axis=1); yd = y0 - (bT + dd) * X0[:, 2]            # T dropped, its coefficient fixed at bT + d (restricted refit)
        refit = float(np.linalg.lstsq(Zd, yd, rcond=None)[0][1])
        grid[str(dd)] = {"slopeFormula": round(s0 - dd * tau, 4), "slopeRefit": round(refit, 4), "fractionOfAbsBT": round(dd / abs(bT), 3), "fractionOfBTHalfWidth": round(dd / ((bq[1] - bq[0]) / 2), 3)}
    dz = None if abs(tau) < 0.05 else s0 / tau
    res["tipping"] = {"tauDegCPerMonth": round(tau, 4), "bT": round(bT, 4), "bTDayCi95": [round(float(bq[0]), 3), round(float(bq[1]), 3)], "grid": grid,
                      "dZero": None if dz is None else round(float(dz), 3), "dZeroWithinBTDayCi": None if dz is None else bool((bT + dz) >= bq[0] and (bT + dz) <= bq[1]),
                      "identity": "slope(bT + d) = slope0 - d * tau; tau = months coefficient of T_pack_mean_avg on months + I + de + dc (same rows)"}
    # ---- decision rules (frozen)
    H0 = (f0["day"]["ci95"][1] - f0["day"]["ci95"][0]) / 2
    decisive = {s: r for s, r in rows.items() if r.get("decisive", True) and not r["day"]["nonDecisiveFailedDraws"]}
    excl = [s for s, r in decisive.items() if not r["day"]["includesZero"]]
    base = {s: (paired[rows[s]["pairedT0"]] if "pairedT0" in rows[s] else f0) for s in decisive}
    cond_a = all(abs(r["slope"] - base[s]["slope"]) <= 0.25 * H0 for s, r in decisive.items())
    cond_b = max(abs(-1.0), abs(1.0)) * abs(tau) < 0.25 * H0
    res["decision"] = {"outcome": "dependent" if excl else "robust", "specificationsExcludingZero": excl, "decisiveSpecs": sorted(decisive),
                       "nonDecisive": sorted(set(rows) - set(decisive)),
                       "tippingSensitive": bool(any(g["slopeFormula"] <= 0 for g in grid.values()) or (res["tipping"]["dZeroWithinBTDayCi"] is True)),
                       "falsificationClause": {"allSlopesWithinQuarterHalfWidth": bool(cond_a), "tippingShiftBelowQuarterHalfWidth": bool(cond_b), "T0DayHalfWidth": round(H0, 4),
                                               "reading": "temperature-specification sensitivity not detected" if (cond_a and cond_b) else "sensitivity to temperature specification or to its coefficient is present"},
                       "multiplicity": "12 intervals (6 day, 6 isoWeek); the any-exclusion rule leans conservative; no adjustment"}
    if "--splice" in sys.argv:
        splice(res)
        return
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1)
    print(json.dumps({"fidelity": res["fidelity"], "slopes": {s: [round(r["slope"], 4), [round(x, 3) for x in r["day"]["ci95"]], [round(x, 3) for x in r["isoWeek"]["ci95"]], r["n"]] for s, r in rows.items()},
                      "paired": {k: [round(r["slope"], 4), r["n"], [round(x, 3) for x in r["day"]["ci95"]]] for k, r in paired.items()}, "tipping": res["tipping"], "decision": res["decision"]}, indent=1))


if __name__ == "__main__":
    main()
