#!/usr/bin/env python3
"""M713d (spec analyses/M712_spec.md Rev 1.1, sections 4, 6 and 8): validation, attribution, influence and expected-exposure runs of the scenario engine (tools/scenario_engine.py).

consistency   G-S2 (IN-SAMPLE consistency check, not a validation): the observed eligible day sequence replayed with simulated pack temperature (full-sample parameters) against the observed binned exposure:
              cycle Arrhenius factor (Ea 50) within 5 %, starts with pack < 15 C within +-15 % of the logged count.
holdout       G-S2b (validation, month-blocked): drive heating (alpha, tau_d, c0, c1) refitted on May-August drives, the park model fitted May-August (M709 `validation_fitMayAug_testSepNov`), then the engine chain
              is run over the September-November eligible days and scored: |simulated - observed| <= 8 percentage points for the Ah share at or above 35 C (pack mean) AND <= 15 % relative for starts below 15 C;
              relative errors are reported beside the absolute ones; the hot-share bracket takes its bias bound from THIS hold-out. Not a clean hold-out (spec section 3): ambient amplitude / peak hour were fitted on
              the whole corpus; the split is confounded with slow polling and the battery software update.
attribution   G-S3 delta by input: S2 with (V0) the prototype inputs, (V1) + the data pool rule, (V2) + the M709 park model, (V3) + the production ambient reconstruction.
lodo          leave-one-day-out influence of every pool day on the headline metrics of S2 (common random numbers); a day moving a metric by more than the half-width of its E-exp interval is listed.
expected      E-exp intervals (day-pool bootstrap of the mean of N_INNER replayed years per pool) for the scenario grid.
Usage: python tools/scenario_validation.py --what consistency,holdout,attribution,lodo,expected [--dir analyses/M713] [--scenarios S2,...]"""
import argparse, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import scenario_engine as SE
import scenario_frame as SF
import exposure_state as ES
import scenario_gates as SG

HEADLINE = SG.HEADLINE
PROTO_PARK = {"tau": 7.553961890995577, "off_s": 1.1632995967688304, "off_a": 3.4050103071067173}


def observed_bins(M, days):
    Dk = M.D[M.D["day"].isin(set(days))]
    b = np.array([Dk["ahc_T_%s" % l].sum() + Dk["ahd_T_%s" % l].sum() for l in SF.TLAB])
    return Dk, b


def _replay(M, par, day_mask):
    """Replay the eligible days selected by day_mask (calendar order) padded to 365 with an empty pool day, no transform; returns the engine accumulators and the number of replayed days."""
    seq = np.flatnonzero(M.ok & day_mask)[None, :]
    pad = np.zeros((1, 365), int)
    n_ = min(seq.shape[1], 365)
    pad[0, :n_] = seq[0, :n_]
    empty = np.flatnonzero((M.P["valid"].sum(axis=1) == 0) & M.ok)
    pad[0, n_:] = empty[0] if len(empty) else seq[0, 0]
    acc = SE.simulate(M, pad, 0.0, dict(par, f_s=1.0, f_a=1.0), M.SRC_SUMMER[pad], use_transform=False)
    return acc, n_, M.cal.loc[M.ok & day_mask, "day"].values[:n_]


def _scores(M, acc, days):
    o = SE.summarise(acc)
    Dk, bins = observed_bins(M, days)
    tot = bins.sum()
    sim_ge35 = float(o["ahShare_T_ge35"][0])
    obs_ge35 = float(bins[8:].sum() / tot)
    sim_lt15 = float(acc["ahT"][0, :4].sum() / acc["ahT"][0].sum())
    obs_lt15 = float(bins[:4].sum() / tot)
    af_obs = float(Dk["afah_50"].sum() / (Dk["ah"] - Dk["ah_noT"]).sum())
    st_sim = float(o["warmups_Tstart_lt15"][0])
    st_obs = int((Dk["T_start"] < 15).sum())
    return {"nDays": int(len(days)), "ahShare_ge35": {"sim": round(sim_ge35, 4), "obs": round(obs_ge35, 4), "diffPoints": round(100 * (sim_ge35 - obs_ge35), 2), "relError": round((sim_ge35 - obs_ge35) / obs_ge35, 4) if obs_ge35 > 0 else None},
            "ahShare_lt15": {"sim": round(sim_lt15, 4), "obs": round(obs_lt15, 4)},
            "arrCycleAF_Ea50": {"sim": round(float(o["arrCycleAF_Ea50"][0]), 4), "obs": round(af_obs, 4), "relError": round(float(o["arrCycleAF_Ea50"][0]) / af_obs - 1, 4)},
            "startsBelow15C": {"sim": round(st_sim, 1), "obs": st_obs, "relError": round(st_sim / st_obs - 1, 4) if st_obs else None},
            "ahByTbin": {"sim": [round(float(v), 2) for v in acc["ahT"][0]], "obs": [round(float(v), 2) for v in bins]}}


def consistency(M):
    acc, n_, days = _replay(M, M.params, np.ones(M.nd, bool))
    sc = _scores(M, acc, days)
    sc["gate"] = {"name": "G-S2 consistency check (in-sample)", "pass": bool(abs(sc["arrCycleAF_Ea50"]["relError"]) <= 0.05 and sc["startsBelow15C"]["relError"] is not None and abs(sc["startsBelow15C"]["relError"]) <= 0.15)}
    return sc


def holdout(M):
    month = M.cal["month"].values
    summer_days = set(M.cal.loc[(month <= 8), "day"])
    amb = M.D[["key", "A0", "A1"]]
    inp = ES.drive_inputs(M.D, M.Z, amb)
    is_summer = M.D["day"].isin(summer_days).values
    ix = np.flatnonzero(inp["ok"] & is_summer)
    xs = ES.fit_drive(ix, inp["T0"], inp["i2"], inp["dt_h"], inp["A_dr"], inp["Tobs"], inp["T_end"], M.params["EaR"])
    pk = json.load(open(os.path.join(ROOT, "analyses", "M709", "park_model.json"), encoding="utf-8"))["validation_fitMayAug_testSepNov"]
    par = dict(M.params, alpha=float(xs[0]), tau_d=float(xs[1]), c0=float(xs[2]), c1=float(xs[3]), tau_p=pk["tau_h"], off_s=pk["offset_C"], off_a=pk["offset_C"], off_w=pk["offset_C"])
    acc, n_, days = _replay(M, par, month >= 9)
    sc = _scores(M, acc, days)
    ge = sc["ahShare_ge35"]
    sc["fit"] = {"driveParams_MayAug": {"alpha": round(float(xs[0]), 6), "tau_d": round(float(xs[1]), 4), "c0": round(float(xs[2]), 3), "c1": round(float(xs[3]), 4), "nDrives": int(len(ix))},
                 "park_MayAug": {"tau_h": pk["tau_h"], "offset_C": pk["offset_C"], "source": "analyses/M709/park_model.json validation_fitMayAug_testSepNov"}}
    sc["hotShareBracket"] = {"holdoutBiasPoints": ge["diffPoints"], "note": "the hot-share bias bound is taken from this hold-out (spec Rev 1.1 R5), not from the in-sample 6 points"}
    # parameter check (Director M713 ruling): the hold-out scores really use the May-August parameters; the same autumn replay with the full-sample, drive-only and park-only parameter sets gives different counts
    chk = {}
    for lab, ov in (("fullSample", M.params), ("driveParamsMayAugOnly", dict(M.params, alpha=float(xs[0]), tau_d=float(xs[1]), c0=float(xs[2]), c1=float(xs[3]))),
                    ("parkMayAugOnly", dict(M.params, tau_p=pk["tau_h"], off_s=pk["offset_C"], off_a=pk["offset_C"], off_w=pk["offset_C"])), ("allMayAug", par)):
        a_, n2, d2 = _replay(M, ov, month >= 9)
        s2 = _scores(M, a_, d2)
        chk[lab] = {"startsBelow15C_sim": s2["startsBelow15C"]["sim"], "ahShare_ge35_sim": s2["ahShare_ge35"]["sim"]}
    sc["parameterCheck"] = chk
    st = sc["startsBelow15C"]["relError"]
    sc["gate"] = {"name": "G-S2b month-blocked hold-out", "pass": bool(abs(ge["diffPoints"]) <= 8.0 and st is not None and abs(st) <= 0.15), "tolerance": "|hot share diff| <= 8 points and |starts below 15 C relative error| <= 15 %",
                  "relativeHotShareError": ge["relError"], "cleanHoldout": False}
    return sc


def _s2(M, draws, seed=SE.SEED, par_override=None):
    sc = SE.scenarios(M.ODO_KM)["S2_balanced_owner_expected"]
    o, tilt = SE.run_scenario(M, sc, draws, seed=seed, par_override=par_override)
    return {k: SE.ci(o[k]) for k in HEADLINE if k in o}, float(tilt)


def attribution(dir_, draws=SE.NBOOT):
    ambp = os.path.join(ROOT, "analyses", "exposure_scenarios_2026-11-16", "results", "drive_ambient_recon.csv")
    out = {}
    p0 = os.path.join(dir_, "scenario_gs3_identical_S2.json")
    out["V0_prototype_inputs"] = {k: v for k, v in json.load(open(p0, encoding="utf-8"))["S2_balanced_owner_expected"]["E_real"].items() if k in HEADLINE}
    M1 = SE.load_model(dir_, "production", ambient_csv=ambp, prototype_park=PROTO_PARK)
    out["V1_plus_data_pool_rule"], _ = _s2(M1, draws)
    M2 = SE.load_model(dir_, "production", ambient_csv=ambp)
    out["V2_plus_M709_park"], _ = _s2(M2, draws)
    p3 = os.path.join(dir_, "scenario_results_production.json")
    out["V3_plus_production_ambient"] = {k: v for k, v in json.load(open(p3, encoding="utf-8"))["S2_balanced_owner_expected"]["E_real"].items() if k in HEADLINE}
    steps = ["V0_prototype_inputs", "V1_plus_data_pool_rule", "V2_plus_M709_park", "V3_plus_production_ambient"]
    out["stepDeltas"] = {k: [round((out[b][k][0] - out[a][k][0]) / max(abs(out[a][k][0]), 1e-12), 4) for a, b in zip(steps[:-1], steps[1:])] for k in HEADLINE if k in out[steps[0]]}
    out["stepNames"] = ["data pool rule", "M709 park model (one offset, tau about 9.1 h)", "production ambient reconstruction"]
    return out


def lodo(M, draws=120):
    sc = SE.scenarios(M.ODO_KM)["S2_balanced_owner_expected"]
    pools = sc.get("pools", ("summer", "autumn"))
    ones = {nm: np.ones((draws, len(M.POOL[nm]))) for nm in pools}
    base, _ = SE.run_scenario(M, sc, draws, counts=ones)
    out = {"draws": draws, "days": {}}
    for nm in pools:
        for i, d in enumerate(M.POOL[nm]):
            c = {k: v.copy() for k, v in ones.items()}
            c[nm][:, i] = 0.0
            o, _ = SE.run_scenario(M, sc, draws, counts=c)
            out["days"][M.cal["day"].values[d]] = {k: float(np.mean(o[k]) / np.mean(base[k]) - 1) for k in HEADLINE if k in o and np.mean(base[k]) != 0}
    out["baseline"] = {k: float(np.mean(base[k])) for k in HEADLINE if k in base}
    return out


def expected(M, names, n_pool=500, n_inner=SE.N_INNER):
    sc_all = SE.scenarios(M.ODO_KM)
    res = {}
    for nm in names:
        o, tilt = SE.run_expected(M, sc_all[nm], n_pool, n_inner)
        res[nm] = {"E_exp": {k: SE.ci(v) for k, v in o.items()}, "nPools": n_pool, "nInner": n_inner, "tilt_per100km": round(float(tilt), 4)}
        print(nm, "E-exp km", res[nm]["E_exp"]["annual_km"], "gtc5", res[nm]["E_exp"]["gtc_5Ah_rated"], flush=True)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(ROOT, "analyses", "M713"))
    ap.add_argument("--what", default="consistency,holdout")
    ap.add_argument("--scenarios", default="")
    ap.add_argument("--integration", default="zoh", choices=["zoh", "project"])
    a = ap.parse_args(argv)
    what = a.what.split(",")
    M = SE.load_model(a.dir, "production", integration=a.integration)
    names = [n for n in SE.scenarios(M.ODO_KM) if not a.scenarios or any(n.startswith(x) for x in a.scenarios.split(","))]
    out_dir = a.dir
    if "consistency" in what or "holdout" in what:
        r = {}
        if "consistency" in what:
            r["G-S2"] = consistency(M)
        if "holdout" in what:
            r["G-S2b"] = holdout(M)
        json.dump(r, open(os.path.join(out_dir, "scenario_validation.json"), "w", encoding="utf-8"), indent=1)
        print({k: v["gate"]["pass"] for k, v in r.items()})
    if "attribution" in what:
        json.dump(attribution(a.dir), open(os.path.join(out_dir, "scenario_attribution.json"), "w", encoding="utf-8"), indent=1)
    if "lodo" in what:
        json.dump(lodo(M), open(os.path.join(out_dir, "scenario_lodo.json"), "w", encoding="utf-8"), indent=1)
    if "expected" in what:
        json.dump(expected(M, names), open(os.path.join(out_dir, "scenario_expected%s.json" % ("_project" if a.integration == "project" else "")), "w", encoding="utf-8"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
