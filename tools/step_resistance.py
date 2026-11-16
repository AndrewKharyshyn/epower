#!/usr/bin/env python3
"""M702 (spec analyses/M702_spec.md Rev 1 + errata 12): apparent short-horizon step resistance per drive, the cadence-stratified trend (M634 analyse_metric, CR1 + day bootstrap),
comparison with the vreg proxy, structural-break sensitivities and a semi-synthetic known-answer simulation.
Modes: --study OUT.json [--nb N] | --sim OUT.json [--reps R --workers W]"""
import os, sys, json, hashlib, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import step_events as SE
import m634_winter_controls as M6

SEED = 42
BREAKS = ("2026-08-14", "2026-10-01")
SW_UPDATE = "2026-08-25"          # battery software update (owner), date-split sensitivity only


def load_tables(step_a=SE.STEP_A, direction="discharge"):
    import ah_throughput as AH
    m = pd.read_csv("drive_master.csv", low_memory=False)
    m = m[m["ens_outlier_v2"].astype(str) == "False"].reset_index(drop=True)
    cad = pd.read_csv("cadence_regime.csv").set_index("file")["regime"]
    loader = AH.raw_loader(os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    evs = []
    for _, r in m.iterrows():
        b = loader(r["file"])
        if b is None:
            continue
        ev, _exc, _med = SE.drive_events(b, step_a=step_a, direction=direction)
        if len(ev):
            c = cad.get(r["file"]); c = c if isinstance(c, str) else "unknown"
            evs.append(ev.assign(file=r["file"], date=str(r["date"])[:10], cadence=c))
    ev = pd.concat(evs, ignore_index=True)
    return m, ev


def per_drive(ev, m, min_events=3, weight="drive"):
    e = ev[ev["plausible"]]
    g = e.groupby("file")
    d = pd.DataFrame({"y": g["R_sh_ohm"].median() * 1000.0, "n": g.size(), "I": g["dI"].median(), "gap": g["gapS"].median()})
    d = d[d["n"] >= min_events].reset_index()
    d = d.merge(m[["file", "date", "T_pack_mean_avg"]], on="file", how="left").rename(columns={"T_pack_mean_avg": "T"})
    d["date"] = d["date"].astype(str).str[:10]
    cad = pd.read_csv("cadence_regime.csv").set_index("file")["regime"]
    d["cadence"] = d["file"].map(cad)
    d["post1"] = (d["date"] >= BREAKS[0]).astype(float); d["post2"] = (d["date"] >= BREAKS[1]).astype(float); d["postSw"] = (d["date"] >= SW_UPDATE).astype(float)
    return d.dropna(subset=["y", "T", "I"]).reset_index(drop=True)


def trend(d, label, nb, extra=("I",)):
    return M6.analyse_metric(label, d, "y", "I", list(extra), nb, unit="mOhm")


def brief(b):
    p = b["specs"]["T-lin"]
    return {"nDrives": b["nDrives"], "nDays": b["nDays"], "slopeMohmPerMonthTlin": p["slope"], "dayBootstrapCi95": p["dayBootstrap"]["ci95"], "cr1Ci95": (p["cr1"] or {}).get("ci95"), "cr1Se": (p["cr1"] or {}).get("se"),
            "includesZero": p["includesZero"], "otherSpecs": {s: {"slope": b["specs"][s]["slope"], "dayBootstrapCi95": b["specs"][s]["dayBootstrap"]["ci95"]} for s in ("T-quad", "T-arr", "T-spl")}}


def run_study(out, nb=4000):
    t0 = time.time()
    m, ev = load_tables()
    res = {"spec": "analyses/M702_spec.md Rev 1 + errata 12", "seed": SEED, "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "stepEventsSha256": hashlib.sha256(open("tools/step_events.py", "rb").read()).hexdigest(),
           "constants": {"STEP_A": SE.STEP_A, "PRE_BAND_A": SE.PRE_BAND_A, "POST_STAB": SE.POST_STAB, "SKEW_MAX_S": SE.SKEW_MAX_S}, "strata": {}}
    vreg = m.set_index("file")["vreg_R_pack_mohm"] if "vreg_R_pack_mohm" in m else None
    for c in ("fast", "slow"):
        d = per_drive(ev[ev["cadence"] == c], m)
        s = {"nEvents": int((ev["cadence"] == c).sum()), "eventGapMedianS": float(ev[ev["cadence"] == c]["gapS"].median())}
        if d["file"].nunique() < 10 or d["date"].nunique() < 5:
            s["status"] = "not estimable"; res["strata"][c] = s; continue
        b = trend(d, "R_sh %s" % c, nb)
        s["primary"] = brief(b); s["median_mOhm"] = float(d["y"].median()); s["iqr_mOhm"] = [float(d["y"].quantile(.25)), float(d["y"].quantile(.75))]
        s["stepSize"] = {"medianA": float(d["I"].median())}
        s["sensitivities"] = {}
        # structural-break dummies as extra covariates
        for nm, ex in (("cadenceBreaks", ["I", "post1", "post2"]), ("softwareUpdate", ["I", "postSw"])):
            dd = d.copy()
            ex = [x for x in ex if x == "I" or dd[x].std() > 0]            # a break dummy that is constant inside the stratum is collinear with the intercept and is dropped (stated)
            try:
                s["sensitivities"][nm] = brief(trend(dd, "R_sh %s %s" % (c, nm), 1000, ex))
            except Exception as e_:
                s["sensitivities"][nm] = {"status": "failed: %s" % type(e_).__name__}
        # gap stratification (lower / upper half of the event gaps)
        e = ev[(ev["cadence"] == c) & ev["plausible"]].copy(); gm = e["gapS"].median()
        for nm, mask in (("gapBelowMedian", e["gapS"] <= gm), ("gapAboveMedian", e["gapS"] > gm)):
            dd = per_drive(e[mask], m)
            s["sensitivities"][nm] = brief(trend(dd, "R_sh %s %s" % (c, nm), 1000)) if (dd["file"].nunique() >= 10 and dd["date"].nunique() >= 5) else {"status": "not estimable"}
        # event-weighted: weight by repeating drive medians by event count is replaced by the median over all events of the day (cluster)
        # comparison with vreg
        if vreg is not None:
            j = d.assign(vreg=d["file"].map(vreg)).dropna(subset=["vreg"])
            if len(j) >= 10:
                from scipy.stats import spearmanr
                rho = float(spearmanr(j["y"], j["vreg"]).correlation)
                diff = j["y"] - j["vreg"]
                days = j["date"].values; ud = np.unique(days); rng = np.random.default_rng(SEED)
                dm_ = j.assign(diff=diff).groupby("date")["diff"].mean()
                bs = [dm_.values[rng.integers(0, len(dm_), len(dm_))].mean() for _ in range(2000)]
                s["vregComparison"] = {"sharedDrives": int(len(j)), "sharedDays": int(len(ud)), "spearman": rho, "meanDifferenceMohm": float(diff.mean()), "dayClusteredCi95": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]}
        res["strata"][c] = s
    # step-size sensitivities (re-extract events)
    res["stepThresholdSensitivity"] = {}
    for A_ in (15.0, 30.0):
        _m, ev2 = load_tables(step_a=A_)
        res["stepThresholdSensitivity"][str(int(A_))] = {}
        for c in ("fast", "slow"):
            d = per_drive(ev2[ev2["cadence"] == c], m)
            res["stepThresholdSensitivity"][str(int(A_))][c] = brief(trend(d, "R_sh %s %g" % (c, A_), 1000)) if (d["file"].nunique() >= 10 and d["date"].nunique() >= 5) else {"status": "not estimable"}
    _m, ev3 = load_tables(direction="charge")
    res["chargeDirectionSensitivity"] = {}
    for c in ("fast", "slow"):
        d = per_drive(ev3[ev3["cadence"] == c], m)
        res["chargeDirectionSensitivity"][c] = brief(trend(d, "R_sh %s charge" % c, 1000)) if (d["file"].nunique() >= 10 and d["date"].nunique() >= 5) else {"status": "not estimable"}
    res["runtimeSeconds"] = round(time.time() - t0)
    json.dump(res, open(out, "w", encoding="utf-8"), indent=1, default=str)
    return res


# ---------------------------------------------------------------- semi-synthetic simulation
R0_MOHM, R1_MOHM, TAU_S = 60.0, 80.0, 5.0
V_STEP, ICC = 0.16, 0.3


def rtrue(g):
    return (R0_MOHM + R1_MOHM * (1 - np.exp(-g / TAU_S))) / 1000.0           # Ohm


def sim_rep(args):
    seed, drift_rel_per_month, kind, stratum = args
    rng = np.random.default_rng(seed)
    ev = _EV[_EV["cadence"] == stratum]; m = _M
    pd_ = ev.groupby("file")
    months0 = pd.to_datetime(ev["date"]).min()
    day_eff = {}
    rows = []
    for f, e in pd_:
        if len(e) < 3:
            continue
        date = e["date"].iloc[0]
        T = float(_TMAP.get(f, np.nan))
        if not np.isfinite(T):
            continue
        mo = (pd.Timestamp(date) - months0).days / 30.44
        if date not in day_eff:
            day_eff[date] = rng.normal(0, np.sqrt(ICC / (1 - ICC)) * 0.08)
        tf = 1 - 0.01 * (T - 25.0) if kind != "arrhenius" else np.exp(2800.0 * (1 / (T + 273.15) - 1 / 298.15))
        scale = (1 + drift_rel_per_month * mo) * tf * np.exp(day_eff[date] + rng.normal(0, 0.05))
        g = e["gapS"].values; dI = e["dI"].values
        R = rtrue(g) * scale
        dV = dI * R
        Vpre = 380.0 + rng.uniform(-5, 5, len(g))
        ph = rng.uniform(0, V_STEP, len(g))
        Vq_pre = np.round((Vpre + ph) / V_STEP) * V_STEP; Vq_post = np.round((Vpre - dV + ph) / V_STEP) * V_STEP
        Rest = (Vq_pre - Vq_post) / dI
        ok = (Rest > 0) & (Rest < 0.5)
        if ok.sum() < 3:
            continue
        rows.append({"file": f, "date": date, "y": float(np.median(Rest[ok])) * 1000.0, "truthY": float(np.median(R[ok])) * 1000.0, "T": T, "I": float(np.median(dI[ok])), "gap": float(np.median(g[ok])), "mo": mo})
    d = pd.DataFrame(rows)
    d["rel"] = d["y"] / d["truthY"] - 1.0
    t = d["mo"].values; days = d["date"].values
    import statsmodels.api as sm
    X = np.column_stack([np.ones(len(d)), t, d["T"].values, d["I"].values])
    r = sm.OLS(d["y"].values, X).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(days)[0]})
    G = len(np.unique(days)); from scipy import stats as st
    tc = st.t.ppf(0.975, G - 1); b, se = float(r.params[1]), float(r.bse[1])
    base = float(d["truthY"].mean())
    truth = drift_rel_per_month * base                                    # planted slope in mOhm per month on the mean scale
    gtert = pd.qcut(d["gap"], 3, labels=False, duplicates="drop"); itert = pd.qcut(d["I"], 3, labels=False, duplicates="drop")
    per = np.where(d["date"] < BREAKS[0], 0, np.where(d["date"] < BREAKS[1], 1, 2))
    grp = {"gap": d.groupby(gtert)["rel"].mean().values, "stepSize": d.groupby(itert)["rel"].mean().values, "cadencePeriod": d.groupby(per)["rel"].mean().values}
    spread = max(float(np.max(v) - np.min(v)) for v in grp.values() if len(v) > 1)
    return {"b": b, "lo": b - tc * se, "hi": b + tc * se, "truth": truth, "bias": float(d["rel"].mean()), "spread": spread, "se": se, "n": int(len(d))}


_EV = _M = _TMAP = None


def _init(ev, m, tmap):
    global _EV, _M, _TMAP
    _EV, _M, _TMAP = ev, m, tmap


def run_sim(out, reps=500, workers=6):
    from multiprocessing import Pool
    m, ev = load_tables()
    ev = ev[ev["plausible"] | True]
    tmap = dict(zip(m["file"], m["T_pack_mean_avg"]))
    res = {"spec": "analyses/M702_spec.md Rev 1 item 8 + errata 12", "reps": reps, "design": {"R0_mOhm": R0_MOHM, "R1_mOhm": R1_MOHM, "tau_s": TAU_S, "icc": ICC, "vStepV": V_STEP}, "strata": {}}
    real = json.load(open("analyses/M702_study.json", encoding="utf-8")) if os.path.exists("analyses/M702_study.json") else None
    with Pool(workers, initializer=_init, initargs=(ev, m, tmap)) as pool:
        for c in ("fast", "slow"):
            se_real = ((real or {}).get("strata", {}).get(c, {}).get("primary", {}) or {}).get("cr1Se")
            base = 130.0
            mde_rel = (2.8 * se_real / base) if se_real else 0.02
            out_c = {"mdeRelPerMonth": mde_rel}
            for name, drift, kind in (("null", 0.0, "linear"), ("planted_MDE", mde_rel, "linear"), ("arrhenius_null_diagnostic", 0.0, "arrhenius")):
                rs = pool.map(sim_rep, [(SEED * 1000 + i, drift, kind, c) for i in range(reps)])
                R = pd.DataFrame(rs)
                excl = (R["lo"] > 0) | (R["hi"] < 0)
                blk = {"meanRelBias": float(R["bias"].mean()), "absMeanRelBias": float(abs(R["bias"].mean())), "biasMcSe": float(R["bias"].std() / np.sqrt(len(R))), "maxGroupBiasSpreadMean": float(R["spread"].mean()), "undefined": float(R["lo"].isna().mean())}
                if name == "null":
                    blk.update(falsePositive=float(excl.mean()), criterion="<= 0.075", **{"pass": bool(excl.mean() <= 0.075)})
                elif name == "planted_MDE":
                    cov = float(((R["lo"] <= R["truth"]) & (R["hi"] >= R["truth"])).mean())
                    blk.update(coverage95=cov, criterion=">= 0.90", power=float((R["lo"] > 0).mean()), **{"pass": bool(cov >= 0.90)})
                else:
                    blk.update(falsePositive=float(excl.mean()), diagnostic=True)
                out_c[name] = blk
            out_c["biasPass"] = bool(out_c["null"]["absMeanRelBias"] <= 0.10 and out_c["null"]["maxGroupBiasSpreadMean"] <= 0.05)
            out_c["allGatedPass"] = bool(out_c["null"]["pass"] and out_c["planted_MDE"]["pass"] and out_c["biasPass"])
            res["strata"][c] = out_c
    res["allGatedPass"] = all(v["allGatedPass"] for v in res["strata"].values())
    json.dump(res, open(out, "w", encoding="utf-8"), indent=1)
    return res


# ---------------------------------------------------------------- payload block (additive, no display, no stage)
KEY = "stepResistance"


def gap_date_corr():
    ev = pd.read_csv("analyses/M702_feasibility_events.csv")
    out = {}
    for c in ("fast", "slow"):
        e = ev[ev["cadence"] == c]
        mo = (pd.to_datetime(e["date"]) - pd.to_datetime(e["date"]).min()).dt.days / 30.44
        out[c] = float(np.corrcoef(mo, e["gapS"])[0, 1])
    return out


def assemble(study, sim, feas, md5):
    gc = gap_date_corr()
    strata = {}
    for c, s in study["strata"].items():
        if "primary" not in s:
            strata[c] = {"status": s.get("status")}; continue
        p = s["primary"]
        strata[c] = {"events": s["nEvents"], "drives": p["nDrives"], "days": p["nDays"], "eventGapMedianS": s["eventGapMedianS"], "medianMohm": s["median_mOhm"], "iqrMohm": s["iqr_mOhm"],
                     "trendDescriptive": {"design": "R_sh ~ months + T_pack_mean_avg + step size, calendar-day clusters (M634 T-lin)", "slopeMohmPerMonth": p["slopeMohmPerMonthTlin"], "cr1Ci95": p["cr1Ci95"], "dayBootstrapCi95": p["dayBootstrapCi95"],
                                          "includesZero": p["includesZero"], "otherTemperatureSpecs": p["otherSpecs"]},
                     "sensitivities": {k: ({"status": v["status"]} if "status" in v else {"drives": v["nDrives"], "slopeMohmPerMonth": v["slopeMohmPerMonthTlin"], "cr1Ci95": v["cr1Ci95"]}) for k, v in s["sensitivities"].items()},
                     "vregMethodDisagreement": s.get("vregComparison"), "gapDateCorrelation": gc[c]}
    thr = {a: {c: ({"status": v["status"]} if "status" in v else {"drives": v["nDrives"], "slopeMohmPerMonth": v["slopeMohmPerMonthTlin"], "cr1Ci95": v["cr1Ci95"]}) for c, v in b.items()} for a, b in study["stepThresholdSensitivity"].items()}
    chg = {c: ({"status": v["status"]} if "status" in v else {"drives": v["nDrives"], "slopeMohmPerMonth": v["slopeMohmPerMonthTlin"], "cr1Ci95": v["cr1Ci95"]}) for c, v in study["chargeDirectionSensitivity"].items()}
    simb = {c: {"nullFalsePositive": v["null"]["falsePositive"], "plantedCoverage95": v["planted_MDE"]["coverage95"], "plantedPower": v["planted_MDE"]["power"], "meanRelBiasNull": v["null"]["meanRelBias"],
                "maxGroupBiasSpread": v["null"]["maxGroupBiasSpreadMean"], "biasPass": v["biasPass"], "gatePass": v["allGatedPass"]} for c, v in sim["strata"].items()}
    return {
        "spec": "analyses/M702_spec.md Rev 1 + errata 12", "provisional": True, "gateStatus": "failed",
        "files": {"study": "analyses/M702_study.json", "simulation": "analyses/M702_sim.json", "feasibility": "analyses/M702_feasibility.json", "audit": "analyses/M702_audit.json"},
        "status": "pre-registered simulation gate failed; no trend inference; the slopes below are descriptive and every interval includes zero",
        "estimand": "apparent short-horizon step resistance (R_sh): dV/dI between co-timed pre- and post-step samples of the logged BMS current and pack voltage, discharge-direction steps; it depends on the sampling gap, is estimated, and is never pooled across the fast and slow strata",
        "constants": study["constants"], "feasibility": {"nCleanDrives": feas["nCleanDrives"], "exclusionCounts": feas["exclusionCounts"]},
        "strata": strata, "stepThresholdSensitivity": thr, "chargeDirectionSensitivity": chg,
        "simulation": {"reps": sim["reps"], "design": sim["design"], "strata": simb, "gateReading": "gate failed as pre-registered (null false-positive above 0.075 in both strata; slow coverage below 0.90); the estimator bias criterion passed"},
        "reading": ["a trend in R_sh over dates can partly reflect a trend in the event sampling gap (gap-date correlation per stratum in the strata entries); this is a property of the estimand, not only of the simulation",
                    "a blind audit diagnosed three issues of the simulation generator: the null truth depended on the event gap, which trends with date (so the null carried an implied drift); the realised intraclass correlation was above the intended 0.3; the planted-drift base was fixed at 130 mOhm instead of the observed stratum median; the gate result is kept as run (not rewritten), a corrected re-run was not done because the real intervals include zero either way",
                    "method disagreement between R_sh and the vreg regression proxy (different estimands and time horizons; rank correlation and mean difference shown), not a bias claim and not a validation of either",
                    "no equivalence test, no degradation rate, no fast-versus-slow contrast; the M622 look schedule applies and the block stays provisional",
                    "estimated from logged channels; a time constant was not fitted (not identifiable at the logged cadence)"],
        "followUps": "an optional Rev 2 (gap-free null, realised ICC 0.3, observed-median base, gap covariate as a pre-registered sensitivity) is low value-of-information; a gap-matched primary can be considered at the next M622 look",
        "provenance": {"masterMd5": md5, "scriptSha256": study["scriptSha256"], "stepEventsSha256": study["stepEventsSha256"], "verified": False}}


def splice(A, blk, md5, now=None):
    import copy, datetime
    import stamp_common as _sc
    new = copy.deepcopy(A)
    new[KEY] = blk
    old = (A.get("_artifactStamps") or {}).get(KEY)
    st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
    ts = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat()
    st.update(corpusHash=md5, generatedAt=ts, computationStatus="computed", upstreamHashes={"driveMasterMd5": md5},
              computationStatusNote="M702: derived by tools/step_events.py and tools/step_resistance.py from raw drive CSVs and drive_master.csv (spec analyses/M702_spec.md Rev 1 + errata 12); estimated, provisional, simulation gate failed")
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    new["_artifactStamps"][KEY] = _sc.carry_declared(old, st)
    bad = [k for k in set(A) | set(new) if k not in (KEY, "_artifactStamps") and A.get(k) != new.get(k)]
    bad += [k for k in set(A["_artifactStamps"]) | set(new["_artifactStamps"]) if k != KEY and A["_artifactStamps"].get(k) != new["_artifactStamps"].get(k)]
    return new, bad


def do_splice(dry=False):
    study = json.load(open("analyses/M702_study.json", encoding="utf-8")); sim = json.load(open("analyses/M702_sim.json", encoding="utf-8"))
    feas = json.load(open("analyses/M702_feasibility.json", encoding="utf-8"))
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    blk = assemble(study, sim, feas, md5)
    raw = open("summary_arrays.json", encoding="utf-8", newline="").read()
    new, bad = splice(json.loads(raw), blk, md5)
    print(json.dumps({"outsideKey": bad}))
    if bad:
        return 1
    if not dry:
        open("summary_arrays.json", "w", encoding="utf-8", newline="").write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


def main(argv):
    if "--study" in argv:
        nb = int(argv[argv.index("--nb") + 1]) if "--nb" in argv else 4000
        r = run_study(argv[argv.index("--study") + 1], nb)
        print(json.dumps({c: {k: v.get(k) for k in ("status", "nEvents", "primary")} for c, v in r["strata"].items()}, default=str)[:2500]); return
    if "--splice" in argv:
        sys.exit(do_splice("--dry-run" in argv))
    if "--sim" in argv:
        reps = int(argv[argv.index("--reps") + 1]) if "--reps" in argv else 500
        w = int(argv[argv.index("--workers") + 1]) if "--workers" in argv else 6
        print(json.dumps(run_sim(argv[argv.index("--sim") + 1], reps, w))[:3000]); return


if __name__ == "__main__":
    main(sys.argv[1:])
