#!/usr/bin/env python3
"""M713b (spec analyses/M712_spec.md Rev 1.1, section 5): the pack-temperature state model parameters of the exposure scenario model, fitted from the M713a exposure frame (tools/exposure_frame.py).
Fresh code under tools/; nothing is imported from analyses/ (the prototype thermal_params.json may be read as comparison-only data).

Model (all temperatures are MODEL-DERIVED; parked pack temperature is never logged):
  PARK    the M709 one-state diurnal park model (tools/park_model.py park_T; tau_p and the one offset come from analyses/M709/park_model.json, hashed into the output; NOT refitted here).
  DRIVE   per slice  T_{k+1} = T_k + alpha fR(T_k) i2_k dt + (Tc - T_k)(1 - exp(-dt/tau_d)),  Tc = c0 + c1 A_drive,  fR(T) = exp(EaR/R (1/T - 1/Tref)).
          EaR from the reconstructed pulse-resistance proxy (ln R ~ 1 + 1/T + SoC + cadence regime; day-clustered bootstrap); (alpha, tau_d, c0, c1) by soft-L1 least squares on the slice trajectories and the end
          temperature of drives with a start temperature, >= 80 % current coverage and a vehicle ambient reading (day-clustered bootstrap).
  LIMIT   BMS charge-limit register ("input possible power", kW, reported by the BMS, not delivered power) ~ b0 + bT Tmin + bS (SoC - 60) below 20 C; extrapolated linearly (labelled).
  AMBIENT diurnal amplitude and peak hour per season (May-Aug summer, Sep-Nov autumn) with day fixed effects from the driver-read vehicle-sensor ambient (uncalibrated, heat-soaked after parking).
Usage: python tools/exposure_state.py [--dir analyses/M713] [--nboot-drive N]   writes <dir>/state_params.json"""
import argparse, hashlib, json, os, sys
import numpy as np
import pandas as pd
from scipy.optimize import least_squares

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import park_model as PM

W = 2 * np.pi / 24.0
RGAS = 8.314462618
SEED, NBOOT = 42, 4000
NB_DRIVE = 1000
CAP_AH_RATED = 5.0


def fR(Tc, EaR_kj, Tref=25.0):
    T = np.asarray(Tc, float) + 273.15
    return np.exp(EaR_kj * 1000 / RGAS * (1 / T - 1 / (Tref + 273.15)))


def drive_path(T0, i2, dt_h, A_drive, p, heat_mult=1.0):
    """Simulate slices. T0 [n], i2 [n,K] (A^2, NaN -> 0), dt_h [n], A_drive [n]. Returns T at slice midpoints [n,K] and T_end [n]."""
    n, K = i2.shape
    Tc = p["c0"] + p["c1"] * A_drive
    k = 1 - np.exp(-dt_h / p["tau_d"])
    T = np.array(T0, float)
    out = np.empty((n, K))
    for j in range(K):
        q = np.nan_to_num(i2[:, j])
        dT = p["alpha"] * heat_mult * fR(T, p["EaR"]) * q * dt_h + (Tc - T) * k
        out[:, j] = T + 0.5 * dT
        T = T + dT
    return out, T


def _weights(n, nboot, seed):
    return np.random.default_rng(seed).integers(0, n, size=(nboot, n))


# ---------------------------------------------------------------------------------- R(T) activation energy ---------------------------------------
def fit_EaR(D, regime, nboot=NBOOT, seed=SEED):
    """EaR (kJ/mol) of the pulse-resistance proxy: ln R = a + b (1/T - 1/298.15) + c (SoC - 60) + d slow; Ea = b R_gas. Day-clustered bootstrap."""
    P = D.merge(regime, on="key", how="left")
    P = P[(P["R_pulse_mohm"] > 20) & (P["R_pulse_mohm"] < 600) & P["T_pulse"].notna()].copy()
    P["invT"] = 1 / (P["T_pulse"] + 273.15) - 1 / 298.15
    P["soc_c"] = P["soc_pulse"] - 60
    P["slow"] = (P["regime"] == "slow").astype(float)
    X = np.column_stack([np.ones(len(P)), P["invT"].values, P["soc_c"].values, P["slow"].values])
    y = np.log(P["R_pulse_mohm"].values)
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    days = P["day"].unique()
    gi = {d: np.flatnonzero(P["day"].values == d) for d in days}
    rng = np.random.default_rng(seed)
    bs = np.empty(nboot)
    for i in range(nboot):
        ix = np.concatenate([gi[days[j]] for j in rng.integers(0, len(days), len(days))])
        bs[i] = np.linalg.lstsq(X[ix], y[ix], rcond=None)[0][1]
    ea = b[1] * RGAS / 1000
    eab = bs * RGAS / 1000
    ratio = lambda T, bb: float(np.exp(bb * (1 / (T + 273.15) - 1 / 298.15)))
    return {"EaR_kJmol": round(float(ea), 3), "EaR_ci": [round(float(np.percentile(eab, 2.5)), 3), round(float(np.percentile(eab, 97.5)), 3)], "n": int(len(P)), "nDays": int(len(days)),
            "R25_mohm": round(float(np.exp(b[0])), 2), "ratio_R_0C_vs_25C": round(ratio(0, b[1]), 3), "ratio_R_minus10C_vs_25C": round(ratio(-10, b[1]), 3),
            "label": "own pulse-resistance proxy (dV/dI slope, |dI| >= 20 A), reconstructed, not a DCIR measurement; extrapolation below the observed range assumes one activation energy"}


# ---------------------------------------------------------------------------------- drive heating model ------------------------------------------
def fit_drive(ix, T0, i2, dt_h, A_dr, Tobs, T_end_obs, EaR, x0=(0.002, 1.0, 25.0, 0.3)):
    K = i2.shape[1]

    def res(x, ix_):
        p = {"alpha": x[0], "tau_d": x[1], "c0": x[2], "c1": x[3], "EaR": EaR}
        path, Te = drive_path(T0[ix_], i2[ix_], dt_h[ix_], A_dr[ix_], p)
        return np.r_[(path - Tobs[ix_]).ravel() / np.sqrt(K), Te - T_end_obs[ix_]]
    return least_squares(res, x0, args=(ix,), loss="soft_l1", f_scale=1.5, bounds=([0, 0.05, -20, -1], [0.1, 20, 60, 2]), x_scale=[1e-3, 1, 10, 0.3]).x


def drive_inputs(D, Z, amb):
    """Arrays for the drive-heating fit (slices of the frame, ambient of the drive = mean of the start and end vehicle-sensor readings)."""
    K = int(Z["K"])
    A = amb.set_index("key")
    A_dr = ((D["key"].map(A["A0"]) + D["key"].map(A["A1"])) / 2).values
    Tobs = Z["Tobs"]
    ok = D["T_start"].notna().values & (Z["icov"] > 0.8) & np.isfinite(Tobs).all(axis=1) & np.isfinite(A_dr)
    return {"K": K, "ok": ok, "T0": D["T_start"].values, "T_end": D["T_end"].values, "i2": Z["i2"], "Tobs": Tobs, "dt_h": (D["dur_h"] / K).values, "A_dr": A_dr}


def fit_drive_params(D, Z, amb, EaR, nboot=NB_DRIVE, seed=SEED):
    inp = drive_inputs(D, Z, amb)
    args = (inp["T0"], inp["i2"], inp["dt_h"], inp["A_dr"], inp["Tobs"], inp["T_end"], EaR)
    ix = np.flatnonzero(inp["ok"])
    xd = fit_drive(ix, *args)
    dd = D["day"].values[ix]
    dl = np.unique(dd)
    gi = {d: ix[dd == d] for d in dl}
    rng = np.random.default_rng(seed)
    bs = np.empty((nboot, 4))
    for i in range(nboot):
        sel = np.concatenate([gi[dl[j]] for j in rng.integers(0, len(dl), len(dl))])
        bs[i] = fit_drive(sel, *args, x0=xd)
    p = {"alpha": xd[0], "tau_d": xd[1], "c0": xd[2], "c1": xd[3], "EaR": EaR}
    _, Te = drive_path(inp["T0"][ix], inp["i2"][ix], inp["dt_h"][ix], inp["A_dr"][ix], p)
    e = Te - inp["T_end"][ix]
    names = ["alpha_C_per_A2h", "tau_d_h", "c0_C", "c1"]
    out = {n: [round(float(xd[j]), 6), round(float(np.percentile(bs[:, j], 2.5)), 6), round(float(np.percentile(bs[:, j], 97.5)), 6)] for j, n in enumerate(names)}
    out.update({"n": int(len(ix)), "nDays": int(len(dl)), "bootDraws": int(nboot), "mae_Tend_C": round(float(np.abs(e).mean()), 3), "bias_Tend_C": round(float(e.mean()), 3),
                "mae_persistence_C": round(float(np.abs(inp["T_end"][ix] - inp["T0"][ix]).mean()), 3),
                "label": "in-drive pack thermal model per slice: I^2 heating x fR(T) plus relaxation to Tc = c0 + c1 x ambient (cabin-air side not logged: effective parameters)"})
    return out, xd


# ---------------------------------------------------------------------------------- BMS charge-limit map -----------------------------------------
def fit_limit_map(D, nboot=NBOOT, seed=SEED):
    """Pin ~ b0 + bT Tmin + bS (SoC - 60) below 20 C from the per-drive normal-equation statistics, day-clustered bootstrap on the per-day sums."""
    cols = ["pin_xtx_%d%d" % (i, j) for i in range(3) for j in range(3)] + ["pin_xty_%d" % i for i in range(3)]
    Q = D[D["pin_n"] > 0].copy()
    days = Q["day"].unique()
    S = {d: Q.loc[Q["day"] == d, cols].fillna(0).sum() for d in days}
    xtx = lambda s: np.array([[s["pin_xtx_%d%d" % (i, j)] for j in range(3)] for i in range(3)])
    xty = lambda s: np.array([s["pin_xty_%d" % i] for i in range(3)])
    tot = sum(S.values())
    b = np.linalg.solve(xtx(tot), xty(tot))
    rng = np.random.default_rng(seed)
    bs = np.empty((nboot, 3))
    for i in range(nboot):
        sel = [days[j] for j in rng.integers(0, len(days), len(days))]
        s = sum(S[d] for d in sel)
        bs[i] = np.linalg.solve(xtx(s), xty(s))
    ci = lambda j: [round(float(np.percentile(bs[:, j], 2.5)), 4), round(float(np.percentile(bs[:, j], 97.5)), 4)]
    return {"b0_kW_at_0C_soc60": [round(float(b[0]), 4)] + ci(0), "bT_kW_perC": [round(float(b[1]), 4)] + ci(1), "bS_kW_perSocPt": [round(float(b[2]), 4)] + ci(2),
            "n_s": int(Q["pin_n"].sum()), "nDays": int(len(days)), "zeroCrossing_C_soc60": round(float(-b[0] / b[1]), 2),
            "label": "BMS-reported charge-limit register (not delivered power) below 20 C; the logged range ends near the observed minimum, below that the map is a linear EXTRAPOLATION"}, b


# ---------------------------------------------------------------------------------- main -------------------------------------------------------------
def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(ROOT, "analyses", "M713"))
    ap.add_argument("--nboot-drive", type=int, default=NB_DRIVE)
    a = ap.parse_args(argv)
    D = pd.read_csv(os.path.join(a.dir, "exposure_drives.csv"), dtype={"key": str}, parse_dates=["start", "end"], low_memory=False)
    Z = np.load(os.path.join(a.dir, "exposure_slices.npz"), allow_pickle=True)
    assert list(Z["keys"]) == list(D["key"])
    reg = pd.read_csv(os.path.join(ROOT, "cadence_regime.csv"))
    reg["key"] = reg["file"].map(lambda f: "".join(c for c in str(f) if c.isdigit())[:14])
    regime = reg[["key", "regime"]]
    E = pd.DataFrame({"key": D["key"], "local0": D["start"], "day": D["day"], "dur_s": D["dur_h"] * 3600})
    amb = PM.ambient_samples(E)
    _, diur = PM.reconstruct_ambient(E)
    EaR = fit_EaR(D, regime)
    drv, xd = fit_drive_params(D, Z, amb, EaR["EaR_kJmol"], a.nboot_drive)
    lim, b = fit_limit_map(D)
    parkp = os.path.join(ROOT, "analyses", "M709", "park_model.json")
    pk = json.load(open(parkp, encoding="utf-8"))
    m2 = pk["M2_fullSample_nonFlagged"]
    out = {"milestone": "M713b", "spec": "analyses/M712_spec.md", "specSha256": sha(os.path.join(ROOT, "analyses", "M712_spec.md")),
           "frame": {"exposure_drives.csv": sha(os.path.join(a.dir, "exposure_drives.csv")), "exposure_slices.npz": sha(os.path.join(a.dir, "exposure_slices.npz"))},
           "scriptSha256": sha(os.path.abspath(__file__)), "masterMd5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest(),
           "R_T": EaR, "drive": drv, "limitMap": lim, "diurnalAmbient": diur,
           "park": {"source": "analyses/M709/park_model.json", "sha256": sha(parkp), "tau_h": m2["tau_h"], "tauCi": m2["tauCi"], "offset_C": m2["offset_C"], "offsetCi": m2["offsetCi"],
                    "offsetBracketForSensitivity": [0.0, 2.7], "nPairs": m2["nPairs"], "nDays": m2["nDays"]},
           "params_for_scenarios": {"EaR": EaR["EaR_kJmol"], "park": {"tau": m2["tau_h"], "off": m2["offset_C"]}, "drive": {"alpha": float(xd[0]), "tau_d": float(xd[1]), "c0": float(xd[2]), "c1": float(xd[3])},
                                    "diurnal": {k: [v["amp"], v["hpk"]] for k, v in diur.items()}, "pin": {"b0": float(b[0]), "bT": float(b[1]), "bS": float(b[2])}}}
    tp = os.path.join(ROOT, "analyses", "exposure_scenarios_2026-11-16", "results", "thermal_params.json")
    if os.path.exists(tp):
        P = json.load(open(tp, encoding="utf-8"))["params_for_scenarios"]
        out["prototypeComparison"] = {"note": "comparison-only against the untracked prototype thermal_params.json (park constants there are SUPERSEDED by M709)",
                                      "EaR": [P["EaR"], EaR["EaR_kJmol"]], "drive": {k: [P["drive"][k], float(v)] for k, v in zip(("alpha", "tau_d", "c0", "c1"), xd)},
                                      "pin": {k: [P["pin"][k], float(v)] for k, v in zip(("b0", "bT", "bS"), b)}, "diurnal": {k: [P["diurnal"][k], [diur[k]["amp"], diur[k]["hpk"]]] for k in ("summer", "autumn")}}
    json.dump(out, open(os.path.join(a.dir, "state_params.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: out[k] for k in ("R_T", "params_for_scenarios", "prototypeComparison") if k in out}, indent=1)[:3500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
