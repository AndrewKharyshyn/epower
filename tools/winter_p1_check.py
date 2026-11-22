#!/usr/bin/env python3
"""M732 (analyses/M732_spec.md Rev 2, C-P1b): fidelity of the P1 extractor on the FROZEN basis, no winter observation.
 (i) with the unrounded per-season amplitude / peak hour that the vendored `park_model.reconstruct_ambient` fits on the M709 endpoints, the extractor's pair table (vendored census pair builder) reproduces the vendored `park_model.model_frame` + `predict`
     pair by pair to 1e-9, and the eligible / flagged / model-pair counts equal the stored M709 summary (analyses/M709/park_model.json: 639 / 43 / 596);
 (ii) with the ROUNDED frozen amplitude / peak hour (M717 params.diurnalAmbient, summer and autumn) the model pairs are 596 and the bias near 15 C (logged start 12-18 C) equals the stored -0.269 within 5e-4;
 (iii) the maximum prediction difference rounded vs unrounded is reported (the effect of the rounded parameters);
 (iv) the drive path: the vendored frame (git blobs of the M717 commit: analyses/M731_frozen_engine/root/analyses/M713) with the frozen heating parameters gives the end-temperature MAE and bias of the FROZEN copy of state_params (0.73, -0.052, n 644).
Writes analyses/M732_fidelity_check.json (a log of runs; the registry hashes it). Usage: python tools/winter_p1_check.py [--run-label LABEL]"""
import hashlib, json, os, sys, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_p1 as W1

OUT = os.path.join(ROOT, "analyses", "M732_fidelity_check.json")
VR = os.path.join(ROOT, "analyses", "M731_frozen_engine", "root")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    label = argv[argv.index("--run-label") + 1] if "--run-label" in argv else "run 1"
    V = W1.vendored()
    RC, PM, ES = V["restart_census"], V["park_model"], V["exposure_state"]
    frozen = json.load(open(os.path.join(ROOT, "analyses", "M717_winter_predictions.json"), encoding="utf-8"))
    par = frozen["params"]
    stored = json.load(open(os.path.join(ROOT, "analyses", "M709", "park_model.json"), encoding="utf-8"))
    E = pd.read_csv(os.path.join(ROOT, "analyses", "M709", "restart_endpoints.csv"), dtype={"key": str}, low_memory=False)
    E["local0"] = pd.to_datetime(E["local0"], format="ISO8601")
    # vendored production route (its own ambient reading: the vendored mini-root summary_config)
    P = RC.build_pairs(E, RC.ambient_start_map())
    Dv, parv = PM.model_frame(E, P)
    A, parfit = PM.reconstruct_ambient(E)
    tau, off = par["park"]["tau_h"], par["park"]["offset_C"]
    predv = PM.predict(Dv, tau, off)
    # the sidecar view of the same drives
    sc = E.copy()
    sc["local0"] = sc["local0"].astype(str)
    Ai = PM.ambient_samples(E).set_index("key")
    sc["A0"], sc["A1"] = sc["key"].map(Ai["A0"]), sc["key"].map(Ai["A1"])
    for j in range(W1.K_SLICES):
        sc["i2_%d" % j] = 0.0
    sc["icov"] = 1.0
    sc = sc.sort_values("utc0").reset_index(drop=True)
    unr = {s: (float(A.loc[A["season"] == s, "amp"].iloc[0]), float(A.loc[A["season"] == s, "hpk"].iloc[0])) for s in ("summer", "autumn")}
    rnd = {"summer": (par["diurnalAmbient"]["summer"]["amp"], par["diurnalAmbient"]["summer"]["hpk"]), "autumn": (par["diurnalAmbient"]["autumn"]["amp"], par["diurnalAmbient"]["autumn"]["hpk"])}
    D1 = W1.build_pair_table(sc, par, seasonal=unr)
    D2 = W1.build_pair_table(sc, par, seasonal=rnd)
    m = (Dv["use"].values & D1["use"].values)
    d_unr = float(np.nanmax(np.abs(D1["pred"].values[m] - predv[m])))
    cnt = {"eligible": int(D1["elig"].sum()), "flaggedAmongEligible": int((D1["elig"] & D1["flagged"]).sum()), "modelPairs": int(D1["use"].sum())}
    cnt_s = {"eligible": stored["support"]["pairsEligible"], "flaggedAmongEligible": stored["support"]["flaggedUnloggedUseAmongEligible"], "modelPairs": stored["support"]["modelPairs"]}
    near = D2[D2["use"] & (D2["y"] >= 12) & (D2["y"] <= 18)]
    b15 = float(near["bias"].mean())
    rec = {"label": label, "unroundedSeasonal": unr, "roundedSeasonal": rnd,
           "C-P1b-i": {"maxAbsPredDiffVsVendored": d_unr, "sameUseMask": bool((Dv["use"].values == D1["use"].values).all()), "counts": cnt, "stored": cnt_s, "pass": bool(d_unr <= 1e-9 and cnt == cnt_s and (Dv["use"].values == D1["use"].values).all())},
           "C-P1b-ii": {"modelPairs": int(D2["use"].sum()), "biasNear15C": b15, "stored": stored["E4_coldStartCounts"]["biasNear15C_C"], "pass": bool(int(D2["use"].sum()) == cnt_s["modelPairs"] and abs(b15 - stored["E4_coldStartCounts"]["biasNear15C_C"]) <= 5e-4)},
           "C-P1b-iii": {"maxAbsPredDiffRoundedVsUnrounded": float(np.nanmax(np.abs(D2["pred"].values[m] - D1["pred"].values[m]))), "meanBiasShiftC": float(np.nanmean(D2["bias"].values[m] - D1["bias"].values[m]))}}
    # (iv) drive path on the frozen frame
    Dd = pd.read_csv(os.path.join(VR, "analyses", "M713", "exposure_drives.csv"), dtype={"key": str}, low_memory=False)
    Z = dict(np.load(os.path.join(VR, "analyses", "M713", "exposure_slices.npz"), allow_pickle=True))
    amb = PM.ambient_samples(E)
    dh, rt = par["driveHeating"], par["R_T"]
    p = {"c0": dh["c0_C"], "c1": dh["c1"], "tau_d": dh["tau_d_h"], "alpha": dh["alpha_C_per_A2h"], "EaR": rt["EaR_kJmol"]}
    Zk = {"K": int(Z["K"]) if "K" in Z else W1.K_SLICES, "icov": Z["icov"], "Tobs": Z["Tobs"], "i2": Z["i2"]}
    X = ES.drive_inputs(Dd, Zk, amb)
    ok = X["ok"]
    _, Tend = ES.drive_path(X["T0"][ok], X["i2"][ok], X["dt_h"][ok], X["A_dr"][ok], p)
    err = Tend - X["T_end"][ok]
    st = json.load(open(os.path.join(ROOT, "analyses", "M717_frozen_sources", "analyses__M713__state_params.json"), encoding="utf-8"))["drive"]
    rec["C-P1b-iv"] = {"n": int(ok.sum()), "mae": float(np.nanmean(np.abs(err))), "bias": float(np.nanmean(err)), "stored": {"n": st["n"], "mae": st["mae_Tend_C"], "bias": st["bias_Tend_C"]},
                       "pass": bool(int(ok.sum()) == st["n"] and round(float(np.nanmean(np.abs(err))), 2) == st["mae_Tend_C"] and round(float(np.nanmean(err)), 3) == st["bias_Tend_C"])}
    rec["inputs"] = {"restart_endpoints.csv": sha(os.path.join(ROOT, "analyses", "M709", "restart_endpoints.csv")), "park_model.json": sha(os.path.join(ROOT, "analyses", "M709", "park_model.json"))}
    rec["allCriteriaPassed"] = bool(rec["C-P1b-i"]["pass"] and rec["C-P1b-ii"]["pass"] and rec["C-P1b-iv"]["pass"])
    log = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {"spec": "analyses/M732_spec.md", "runs": []}
    log["runs"].append(rec)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(log, ensure_ascii=False, indent=1, default=float) + "\n")
    print(json.dumps(rec, indent=1, default=float)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
