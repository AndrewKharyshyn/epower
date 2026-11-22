#!/usr/bin/env python3
"""M732 (analyses/M732_spec.md Rev 2, C-P1c/K3 input): runs the P1 extractor on a REPLAY window of the frozen basis (Oct-Nov 2026 drives of the M709 endpoints with the frozen-basis slices), no winter observation. The window months are (10, 11) instead of (12, 1, 2); everything else is the frozen extractor.
Writes the replay sidecar analyses/M732/p1_basis_replay_sidecar.csv (the blind auditor's input) and analyses/M732_replay_check.json (the extractor's cells). Usage: python tools/winter_p1_replay.py"""
import json, os, sys, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_p1 as W1

VR = os.path.join(ROOT, "analyses", "M731_frozen_engine", "root")


def replay_sidecar():
    V = W1.vendored()
    PM = V["park_model"]
    E = pd.read_csv(os.path.join(ROOT, "analyses", "M709", "restart_endpoints.csv"), dtype={"key": str}, low_memory=False)
    E["local0"] = pd.to_datetime(E["local0"], format="ISO8601")
    Ai = PM.ambient_samples(E).set_index("key")
    Dd = pd.read_csv(os.path.join(VR, "analyses", "M713", "exposure_drives.csv"), dtype={"key": str}, low_memory=False)
    Z = np.load(os.path.join(VR, "analyses", "M713", "exposure_slices.npz"), allow_pickle=True)
    ix = {k: i for i, k in enumerate(Dd["key"])}
    sc = E[E["day"] >= "2026-10-01"].copy()
    sc["local0"] = sc["local0"].astype(str)
    sc["A0"], sc["A1"] = sc["key"].map(Ai["A0"]), sc["key"].map(Ai["A1"])
    i2 = np.full((len(sc), W1.K_SLICES), np.nan)
    icov = np.full(len(sc), np.nan)
    for r, k in enumerate(sc["key"]):
        if k in ix:
            i2[r], icov[r] = Z["i2"][ix[k]], Z["icov"][ix[k]]
    for j in range(W1.K_SLICES):
        sc["i2_%d" % j] = i2[:, j]
    sc["icov"] = icov
    cols = [c for c in W1.COLUMNS["P1"] if c in sc.columns]
    return sc.sort_values("utc0")[cols].reset_index(drop=True)


def main(argv=None):
    sc = replay_sidecar()
    os.makedirs(os.path.join(ROOT, "analyses", "M732"), exist_ok=True)
    sc.to_csv(os.path.join(ROOT, "analyses", "M732", "p1_basis_replay_sidecar.csv"), index=False, lineterminator="\n")
    par = json.load(open(os.path.join(ROOT, "analyses", "M717_winter_predictions.json"), encoding="utf-8"))["params"]
    out = W1.extract_p1(sc, par, months=(10, 11))
    rec = {"milestone": "M732", "window": "replay of the frozen basis, months 10 and 11, drives from 2026-10-01 (NOT a winter observation)", "nSidecarRows": int(len(sc)), "result": out}
    with open(os.path.join(ROOT, "analyses", "M732_replay_check.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False, indent=1, default=float) + "\n")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk in ("status", "n", "nDays", "bias", "mae")} for k, v in out["cells"].items()}, default=float, indent=1))
    print(out["status"], out["reanchors"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
