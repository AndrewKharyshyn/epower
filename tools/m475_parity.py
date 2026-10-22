#!/usr/bin/env python3
"""M475 parity and convergence study (spec analyses/M475_spec.md, checks E2, E3, E5). For each drive the SAME frame is extracted with the exact piecewise kernel (regen-v2.3) and with the former slice kernel at
h = 0.05 s (the regen-v2.2 standard path), plus (E2, sample only) h = 0.025, 0.0125, 0.00625 s. Writes analyses/M475_parity.json (never the payload). Reporting only: no threshold here decides anything; the gates are E4 (aggregated
blocks, tools/m475_cells.py) and the Director.
Usage: python tools/m475_parity.py [--all | --sample N] [--workers W]"""
import json, os, sys, time
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import regen_v2 as R
import regen_v2_cache as RC

OUT = "analyses/M475_parity.json"
HS = (0.05, 0.025, 0.0125, 0.00625)
_FL = None


def run_slice(df, i_off, h, kw=None):
    """Former standard path: the slice kernel at slice length h (touch = any slice)."""
    exact = R._exact_energy
    R._exact_energy = lambda t0, dt, v0, v1, it, iv, vt, vv, off: R._slice_energy(t0, dt, v0, v1, it, iv, vt, vv, off, h)
    try:
        t = time.perf_counter()
        r = R.extract_drive(df, i_off=i_off, **(kw or {}))
        return r, time.perf_counter() - t
    finally:
        R._exact_energy = exact


def summarize(r):
    iv, b = r["intervals"], r["bins"]
    if iv is None:
        return None
    return {"n": int(len(iv["t0"])), "charge": float(iv["charge"].sum()), "chargeOff": float(iv["chargeOff"].sum()) if "chargeOff" in iv else None, "dv2": float(iv["dv2"].sum())}


def one(args):
    global _FL
    fn, i_off, convergence = args[:3]
    variant = args[3] if len(args) > 3 else "base"
    kw = RC.variant_kwargs(variant)
    import drive_raw_cache as drc
    if _FL is None:
        _FL = drc.make_frame_loader(raw_dir=RC.raw_dir())
    df = _FL(fn)
    if df is None:
        return {"file": fn, "status": "noFrame"}
    R.extract_drive(df, i_off=i_off, **kw)           # untimed warm-up (the first call imports compute_summary_arrays)
    t = time.perf_counter(); rn = R.extract_drive(df, i_off=i_off, **kw); t_new = time.perf_counter() - t
    ro, t_old = run_slice(df, i_off, 0.05, kw)
    if rn["intervals"] is None or ro["intervals"] is None:
        return {"file": fn, "status": "noIntervals", "nNew": None if rn["intervals"] is None else int(len(rn["intervals"]["t0"])), "nOld": None if ro["intervals"] is None else int(len(ro["intervals"]["t0"]))}
    ivn, ivo, bn, bo = rn["intervals"], ro["intervals"], rn["bins"], ro["bins"]
    assert len(ivn["t0"]) == len(ivo["t0"]) and np.array_equal(ivn["t0"], ivo["t0"]), "interval sets differ"
    rel = lambda a, b_: float((a - b_) / b_) if b_ else None
    ch_n, ch_o = float(ivn["charge"].sum()), float(ivo["charge"].sum())
    co_n, co_o = float(ivn["chargeOff"].sum()), float(ivo["chargeOff"].sum())
    # bin assignment: intervals whose set of charge-bearing / KE-bearing bins differs
    kn = (bn["dv2"] > 1e-9); ko = (bo["dv2"] > 1e-9)
    out = {"file": fn, "status": "ok", "nIntervals": int(len(ivn["t0"])), "chargeNew": ch_n, "chargeOld": ch_o, "relCharge": rel(ch_n, ch_o), "relChargeOff": rel(co_n, co_o),
           "dv2MaxAbsDiff": float(np.max(np.abs(ivn["dv2"] - ivo["dv2"]))), "binKEsetDiffers": int((kn != ko).any(axis=1).sum()), "touchFlips": int((bn["touch"] != bo["touch"]).sum()),
           "touchOldOnly": int(((bo["touch"] == 1) & (bn["touch"] == 0)).sum()), "touchNewOnly": int(((bo["touch"] == 0) & (bn["touch"] == 1)).sum()),
           "binDv2MaxAbsDiff": float(np.max(np.abs(bn["dv2"] - bo["dv2"]))), "binChargeMaxAbsDiffKwh": float(np.max(np.abs(bn["charge"] - bo["charge"]))),
           "perIntervalMaxAbsKwh": float(np.max(np.abs(ivn["charge"] - ivo["charge"]))),
           "tNewS": t_new, "tOldS": t_old, "cadence": rn["cadence"]}
    if convergence:
        out["conv"] = {str(h): float(run_slice(df, i_off, h, kw)[0]["intervals"]["charge"].sum()) for h in HS[1:]}
        out["conv"]["0.05"] = ch_o
    return out


def main(argv):
    from concurrent.futures import ProcessPoolExecutor
    dm = pd.read_csv("drive_master.csv", usecols=["file"], low_memory=False)
    files = list(dm["file"])
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    i_off = float(A["offsetUncertainty"]["pointEstimateA"])
    workers = int(argv[argv.index("--workers") + 1]) if "--workers" in argv else 4
    variant = argv[argv.index("--variant") + 1] if "--variant" in argv else "base"
    if "--sample" in argv:
        n = int(argv[argv.index("--sample") + 1])
        rng = np.random.default_rng(475)
        files = sorted(rng.choice(files, size=min(n, len(files)), replace=False).tolist())
    conv = "--sample" in argv
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(one, [(f, i_off, conv, variant) for f in files], chunksize=2))
    ok = [r for r in res if r["status"] == "ok"]
    arr = lambda k: np.array([r[k] for r in ok if r.get(k) is not None], float)
    tot_n, tot_o = sum(r["chargeNew"] for r in ok), sum(r["chargeOld"] for r in ok)
    summ = {"variant": variant, "nFiles": len(files), "nOk": len(ok), "iOffA": i_off, "totalChargeNewKwh": tot_n, "totalChargeOldKwh": tot_o, "corpusRelDiff": (tot_n - tot_o) / tot_o,
            "perDriveRelCharge": {k: float(v) for k, v in zip(("min", "p05", "median", "p95", "max"), np.percentile(arr("relCharge"), [0, 5, 50, 95, 100]))},
            "perDriveRelChargeAbsMax": float(np.max(np.abs(arr("relCharge")))), "perIntervalMaxAbsKwhMax": float(arr("perIntervalMaxAbsKwh").max()),
            "dv2MaxAbsDiffMax": float(arr("dv2MaxAbsDiff").max()), "intervalsWithDifferentBinKEset": int(arr("binKEsetDiffers").sum()), "nIntervals": int(arr("nIntervals").sum()),
            "touchFlips": int(arr("touchFlips").sum()), "touchOldOnly": int(arr("touchOldOnly").sum()), "touchNewOnly": int(arr("touchNewOnly").sum()),
            "timing": {"newS": float(arr("tNewS").sum()), "oldS": float(arr("tOldS").sum()), "ratioOldOverNew": float(arr("tOldS").sum() / arr("tNewS").sum()), "note": "extract_drive wall time per drive excluding the frame load, summed over the drives, this machine, 1 process per drive"},
            "wallS": time.time() - t0}
    if conv:
        hs = ("0.05", "0.025", "0.0125", "0.00625")
        err = {h: float(sum(abs(r["conv"][h] - r["chargeNew"]) for r in ok)) for h in hs}
        summ["convergence"] = {"sumAbsErrVsExactKwh": err, "ratioPerHalving": [err[hs[i]] / err[hs[i + 1]] if err[hs[i + 1]] else None for i in range(3)]}
    if "--out" in argv:
        OUT_ = argv[argv.index("--out") + 1]
    else:
        OUT_ = OUT
    json.dump({"summary": summ, "perDrive": res if variant == "base" else None, "_provenance": "GENERATED by tools/m475_parity.py (M475 spec analyses/M475_spec.md); reporting only"}, open(OUT_, "w", encoding="utf-8", newline="\n"), indent=1)
    print(json.dumps(summ, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
