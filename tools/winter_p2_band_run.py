#!/usr/bin/env python3
"""M731 (analyses/M731_spec.md Rev 2.1, section 4): the runner of the realised-ambient P2 band. It runs in a FRESH interpreter (called by winter_p2_band.py) and imports the replay engine ONLY from the vendored git blobs
(analyses/M731_frozen_engine/root/tools); every engine module's file path is asserted to lie there, so no live module is used. The engine is not edited.
Input JSON: {"scenario": name, "shifts": [[12 values]] or [[12] x B] (C per calendar month, one row or one row per draw), "windowMonths": [1..12] or null, "draws": B, "out": npy path}.
It replays run_scenario (same rng, tilt, draw_days, simulate) and, when windowMonths is given, points every synthetic day outside those months at a calendar day without drives (a null day), so the engine's own
`ahShare_T_lt10` is the share over the window months only. Output: the per-draw ahShare_T_lt10 array (npy) and a JSON line with the engine's ci() interval. Model-derived exposure index; never an ageing or end-of-life estimate."""
import json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
VROOT = os.path.join(ROOT, "analyses", "M731_frozen_engine", "root")
VT = os.path.join(VROOT, "tools")
sys.path.insert(0, VT)
import scenario_engine as SE
import exposure_state as ES
import park_model as PM
import scenario_frame as SF
for m in (SE, ES, PM, SF):
    assert os.path.dirname(os.path.abspath(m.__file__)) == os.path.abspath(VT), "live module imported: " + m.__file__


def run(args):
    M = SE.load_model(os.path.join(VROOT, "analyses", "M713"))
    sc = SE.scenarios(M.ODO_KM)[args["scenario"]]
    Bn = int(args["draws"])
    rng = np.random.default_rng(SE.SEED)
    par = dict(M.params)
    par.update(sc.get("par", {}))
    w_sum = sc.get("w_sum", SE.W_SUM_BAL)
    tilt = SE.solve_tilt(M, sc["km"], w_sum, par["f_s"], par["f_a"]) if "km" in sc else 0.0
    src, iss = SE.draw_days(M, Bn, w_sum, rng, tilt=tilt, pools=sc.get("pools", ("summer", "autumn")))
    sh = np.asarray(args["shifts"], float)
    if sh.shape[0] == 1:
        sh = np.repeat(sh, Bn, axis=0)
    tgt = np.repeat(sh, SE.DIM, axis=1)                       # [B, 365]
    wm = args.get("windowMonths")
    if wm:
        mo = SE.month_of_doy()
        outside = ~np.isin(mo + 1, np.asarray(wm))
        nulls = np.flatnonzero(M.P["valid"].sum(axis=1) == 0)
        assert len(nulls), "no calendar day without drives to use as the null day"
        src[:, outside] = nulls[0]
    acc = SE.simulate(M, src, tgt, par, iss, use_transform=sc.get("transform", True))
    o = SE.summarise(acc)
    x = np.asarray(o["ahShare_T_lt10"], float)
    np.save(args["out"], x)
    return {"scenario": args["scenario"], "draws": Bn, "ci": SE.ci(x), "bias": float(M.BIAS), "normals": [float(v) for v in M.KYIV], "modules": sorted(os.path.basename(m.__file__) for m in (SE, ES, PM, SF))}


if __name__ == "__main__":
    a = json.load(open(sys.argv[1], encoding="utf-8"))
    print("RESULT " + json.dumps(run(a)))
