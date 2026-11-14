#!/usr/bin/env python3
"""M649 (P-03, backlog self-audit 2026-11-11): ONE shared S1 fidelity check ahead of the temperature-specification stages (powerfade_temperature_specs, winter_temperature_controls and everything that
refits the powerFade S1 design). The design replicated by tools/m499_temp_spec.py (T0) must reproduce the published S1 reference: the point slope (on the M499 months scale, M578 conversion), n, number of days
and the temperature coefficient. This is the point-estimate part only (no bootstrap, seconds not minutes): the day-interval comparison stays inside the stages that compute intervals. A mismatch stops the
ingestion here, with one message, before the long stages run. Needs the density sidecar powerfade_density.csv written by powerfade_equivalence (so it runs after that stage).
Writes analyses/s1_fidelity.json. Exit 0 pass, 1 fail. Library: evaluate(chk) -> (ok, reasons), point_check(root) -> chk."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)


def evaluate(chk):
    """chk: slopeUnrounded, publishedSlopeConverted, n, publishedN, nDays, publishedNDays, bT, publishedBT, tol. -> (ok, [reasons])"""
    why = []
    if abs(chk["slopeUnrounded"] - chk["publishedSlopeConverted"]) > chk["tol"]:
        why.append("slope %.5f != published %.5f (tolerance %g)" % (chk["slopeUnrounded"], chk["publishedSlopeConverted"], chk["tol"]))
    if chk["n"] != chk["publishedN"]:
        why.append("n %s != published %s" % (chk["n"], chk["publishedN"]))
    if chk["nDays"] != chk["publishedNDays"]:
        why.append("nDays %s != published %s" % (chk["nDays"], chk["publishedNDays"]))
    if round(chk["bT"], 3) != round(chk["publishedBT"], 3):
        why.append("temperature coefficient %.3f != published %.3f" % (chk["bT"], chk["publishedBT"]))
    return (not why), why


def point_check(root=ROOT):
    import numpy as np, pandas as pd
    os.chdir(root)
    import m499_temp_spec as M
    PE = M.PE
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False)[["file", "pack_temp_start_c", "ambient_time_mean_c"]]
    side = PE._read(PE.SIDECAR)
    dens = {r["file"]: (float(r["eff_dt_s"]) if pd.notna(r["eff_dt_s"]) else np.nan, float(r["coverage_frac"]) if pd.notna(r["coverage_frac"]) else np.nan) for r in side.to_dict("records")}
    cc, have_d = PE.s1_rows(dm, dens)
    t0 = pd.to_datetime(cc["date"]).min()
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    pf, pe = A["powerFade"], A["powerFadeEquivalence"]
    d = have_d.merge(sdm, on="file", how="left")
    knots = tuple(np.quantile(d[M.TREF].values.astype(float), [1 / 3, 2 / 3]))
    t = ((pd.to_datetime(d["date"]) - t0).dt.days / M.MONTH_DAYS).values
    X, _ = M.design(d, "T0", t, knots)
    y = d[PE.RCOL].values.astype(float)
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    return {"slopeUnrounded": float(b[1]), "publishedSlopeConverted": pe["s1"]["slope"] * M.SCALE_K, "tol": M.TOL_UNROUNDED, "n": int(len(d)), "publishedN": pf["nClean"],
            "nDays": int(d["date"].nunique()), "publishedNDays": pe["s1"]["nDays"], "bT": float(b[2]), "publishedBT": pf["bTMohmPerDegC"]}


def main():
    chk = point_check()
    ok, why = evaluate(chk)
    out = {"spec": "analyses/M649_spec.md", "check": chk, "passed": ok, "reasons": why}
    with open(os.path.join(ROOT, "analyses", "s1_fidelity.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, indent=1) + "\n")
    print(json.dumps({"passed": ok, "reasons": why}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
