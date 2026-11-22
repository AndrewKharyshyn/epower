#!/usr/bin/env python3
"""M728 (analyses/M728_spec.md Rev 2, pre-registered): extractor of the observed quantity of the M717 winter prediction P4 (BMS charge-limit register at the coldest probe, SoC 60 %).
Pure function on the per-drive exposure frame (analyses/M713/exposure_drives.csv joined as in winter_extractors.load_frame): the per-drive normal-equation sufficient statistics of the BMS-reported register (input possible power, kW) on [1, Tmin, SoC - 60] over the seconds with
Tmin below 20 C (`pin_n`, `pin_xty_0..2`, `pin_xtx_00..22`). BMS-reported register, not delivered power; the re-fitted intercept is model-derived, not the logged register at 0 C. Every number and rule below is frozen by the spec.
The module winter_extractors.py of M727 is NOT edited; this module is new."""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SEED, NB = 42, 4000
VERSION = 1
CELL_PROBE_MIN_BELOW_C = 5.0                          # cell: scoring drives with a probe minimum below 5 C and pin_n > 0
EVAL_0C_COLDEST_AT_MOST = 3.0                         # the 0 C statement needs the coldest Tlo_min of the cell at most 3 C
EVAL_M10C_COLDEST_AT_MOST = -5.0                      # the -10 C statement needs at most -5 C
COND_MAX = 1e8
COLUMNS = {"P4": ["Tlo_min", "pin_n", "pin_xty_0", "pin_xty_1", "pin_xty_2", "pin_xtx_00", "pin_xtx_01", "pin_xtx_02", "pin_xtx_10", "pin_xtx_11", "pin_xtx_12", "pin_xtx_20", "pin_xtx_21", "pin_xtx_22"]}
XTX = ["pin_xtx_%d%d" % (i, j) for i in range(3) for j in range(3)]
XTY = ["pin_xty_%d" % i for i in range(3)]


def _solve(xtx9, xty3):
    A = np.asarray(xtx9, float).reshape(3, 3)
    b = np.asarray(xty3, float)
    c = float(np.linalg.cond(A))
    if not np.isfinite(c) or c > COND_MAX:
        return None, c
    return np.linalg.solve(A, b), c


def extract_p4(df, nb=NB, seed=SEED, restrict_to_cold=True):
    """P4 observed quantity on a frame (the caller passes the scoring set; the frame needs the columns of COLUMNS plus `day`). Returns a dict: cell counts, the fitted plane (b0 = model-derived register at 0 C and SoC 60 kW, bT kW per C, bS kW per SoC point),
    b0 and the -10 C value (b0 - 10 bT) with day-clustered intervals, the evaluability of each statement, the coldest probe minimum of the cell, the pin-weighted mean Tmin and the number of regression seconds."""
    d = df[(df["pin_n"] > 0) & ((df["Tlo_min"] < CELL_PROBE_MIN_BELOW_C) if restrict_to_cold else True)].copy()      # restrict_to_cold=False only for the frozen-basis fidelity check (every drive with register statistics)
    if len(d) == 0:
        return {"nDrives": 0, "nDays": 0, "status": "not evaluable", "reason": "no drive with a probe minimum below 5 C and register statistics"}
    day_ids = sorted(d["day"].unique())                                        # fixed ascending order: deterministic endpoints
    g = d.groupby("day")[XTX + XTY + ["pin_n"]].sum().loc[day_ids]
    X9, Y3 = g[XTX].values, g[XTY].values
    beta, cond = _solve(X9.sum(axis=0), Y3.sum(axis=0))
    out = {"nDrives": int(len(d)), "nDays": int(len(day_ids)), "regressionSeconds": int(d["pin_n"].sum()), "conditionNumber": cond,
           "coldestProbeMinC": float(d["Tlo_min"].min()), "pinWeightedMeanTminC": float(g["pin_xtx_01"].sum() / g["pin_xtx_00"].sum()),
           "kind": "BMS-reported register (input possible power), re-fitted plane; model-derived intercept, not the logged register at 0 C"}
    if beta is None:
        out.update(status="not evaluable", reason="condition number %.3g above the limit" % cond)
        return out
    rng = np.random.default_rng(seed)
    k = len(day_ids)
    idx = rng.integers(0, k, size=(nb, k))
    counts = np.zeros((nb, k))
    for i in range(nb):
        counts[i] = np.bincount(idx[i], minlength=k)
    SX, SY = counts @ X9, counts @ Y3
    b0s, m10s, bts, bss, bad = [], [], [], [], 0
    for i in range(nb):
        bi, ci = _solve(SX[i], SY[i])
        if bi is None:
            bad += 1
            continue
        b0s.append(bi[0]); m10s.append(bi[0] - 10.0 * bi[1]); bts.append(bi[1]); bss.append(bi[2])
    if bad > 0.01 * nb:
        out.update(status="not evaluable", reason="%d of %d bootstrap draws singular (> 1 %%)" % (bad, nb))
        return out
    q = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
    coldest = out["coldestProbeMinC"]
    out.update(status="fitted", bootstrapSingularDraws=int(bad), b0KwAt0CSoc60=float(beta[0]), b0Ci95=q(b0s), bTKwPerC=float(beta[1]), bTCi95=q(bts), bSKwPerSocPoint=float(beta[2]), bSCi95=q(bss),
               kwAtMinus10C=float(beta[0] - 10.0 * beta[1]), kwAtMinus10CCi95=q(m10s),
               evaluable0C=bool(coldest <= EVAL_0C_COLDEST_AT_MOST), evaluableMinus10C=bool(coldest <= EVAL_M10C_COLDEST_AT_MOST))
    return out
