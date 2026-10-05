#!/usr/bin/env python3
"""Read-only performance baseline (audit 2026-10-05 follow-up; spec analyses/audit_2026-10-05_feasibility.md).
Writes only analyses/perf_baseline.json. Never touches drive_master.csv, summary_*.json or raw/.
Sections:
  stageHistory  per-stage wall seconds of the latest full ingest run found in runs/*/status.json (historical, not re-run)
  loadDrive     recon_engine.load_drive on the first N fuel-instrumented drives of the M377c closure per-drive file
                (median of REPEATS wall times, sha256 fingerprint of every output column for old/new parity)
  throughputMC  energy_uncertainty_mc.build on a seeded SYNTHETIC precompute (510 drives x 7-point grid; the real
                energy_mc_precompute.json is not on disk): wall time, tracemalloc peak, fingerprint of the result
  closureBoot   day-clustered percentile bootstrap (seed 42, 4000 draws) of E_gen/km from the M377c per-drive file
Usage: XT_RAW_DIR=$PWD/raw python tools/perf_baseline.py [--n 24] [--repeats 3] [--out analyses/perf_baseline.json]"""
import argparse, glob, hashlib, json, os, platform, statistics, sys, time, tracemalloc
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
os.environ.setdefault("XT_RAW_DIR", os.path.join(ROOT, "raw"))
import numpy as np, pandas as pd


def stage_history():
    best = None
    for f in sorted(glob.glob("runs/*/status.json")):
        d = json.load(open(f, encoding="utf-8"))
        if len(d["stages"]) >= 20 and (best is None or len(d["stages"]) >= len(best[1]["stages"])):
            best = (f, d)
    if not best:
        return None
    f, d = best
    return {"run": f.replace("\\", "/"), "result": d["result"], "totalSeconds": round(sum(s["seconds"] for s in d["stages"]), 1),
            "stages": [{"id": s["id"], "seconds": s["seconds"], "status": s["status"]} for s in d["stages"]]}


def fingerprint_frame(g):
    h = hashlib.sha256()
    for c in g.columns:
        v = g[c].values
        h.update(c.encode())
        h.update((v.astype("int64") if np.issubdtype(v.dtype, np.datetime64) else v.astype("float64")).tobytes())
    return h.hexdigest()


def bench_load_drive(n, repeats):
    import recon_engine as RE
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from gtr_closure_diag import _raw_names
    names = _raw_names()
    files = pd.read_csv("analyses/M377c_closure_perdrive.csv")["file"].tolist()[:n]
    dm = pd.read_csv("drive_master.csv").set_index("file")
    times, fps = [], {}
    for r in range(repeats):
        t0 = time.perf_counter()
        for f in files:
            off = float(dm.loc[f].get("I_offset_A_applied", 0.0) or 0.0)
            g = RE.load_drive(names[f], off)
            if r == 0:
                fps[f] = fingerprint_frame(g) if g is not None else None
        times.append(time.perf_counter() - t0)
    return {"files": len(files), "repeats": repeats, "medianSeconds": round(statistics.median(times), 3),
            "allSeconds": [round(t, 3) for t in times], "fingerprints": fps}


def synthetic_precompute(n=510, seed=7):
    rng = np.random.default_rng(seed)
    grid = [500, 750, 1000, 1250, 1500, 1750, 2000]
    drives = []
    for i in range(n):
        base = float(rng.gamma(2.0, 1.5)); inc = np.cumsum(np.abs(rng.normal(0, 0.003 * base, len(grid))))
        thr = base + inc; dis = 0.5 * thr + rng.normal(0, 0.01); chg = thr - dis
        drives.append({"file": f"syn{i}", "grid": {str(t): {"discharge": float(dis[k]), "charge": float(chg[k]), "throughput": float(thr[k])}
                                                  for k, t in enumerate(grid)},
                       "quantSdThroughputKwh": float(0.002 * base), "possibleMissingKwh": float(0.01 * base),
                       "offsetSensitivity": {"dThroughputPerA": float(rng.normal(0.5, 0.05)), "dDischargePerA": float(rng.normal(0.3, 0.03)),
                                             "dChargePerA": float(rng.normal(0.2, 0.03))}})
    return {"meta": {"validation": {}, "independentIntegrationCheck": {}, "lsbCurrentA": 0.1, "lsbVoltageV": 0.1}, "drives": drives}


def bench_mc():
    import energy_uncertainty_mc as MCU
    pre = synthetic_precompute()
    tracemalloc.start()
    t0 = time.perf_counter()
    out = MCU.build(pre, rng=np.random.default_rng(MCU.SEED), offset_point_a=-0.38, ci95a=(-0.42, -0.35), net_correction_kwh=21.0)
    dt = time.perf_counter() - t0
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    fp = hashlib.sha256(json.dumps({k: out[k] for k in ("grossThroughputMC", "netDrawCorrMC") if k in out}, sort_keys=True, default=float).encode()).hexdigest()
    return {"drives": len(pre["drives"]), "draws": MCU.N_DRAWS, "seconds": round(dt, 3), "tracemallocPeakMB": round(peak / 1e6, 1), "fingerprint": fp}


def bench_boot():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from gtr_closure_diag import dayboot, ratio
    d = pd.read_csv("analyses/M377c_closure_perdrive.csv")
    t0 = time.perf_counter()
    ci = dayboot(d, lambda x: ratio(x, "E_gen"))
    return {"drives": int(len(d)), "days": int(d["date"].nunique()), "draws": 4000, "seconds": round(time.perf_counter() - t0, 3), "ci": ci}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", default="analyses/perf_baseline.json")
    a = ap.parse_args()
    res = {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "python": platform.python_version(), "numpy": np.__version__,
           "pandas": pd.__version__, "platform": platform.platform(),
           "masterMD5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(),
           "note": "pinned env is Python 3.11; record the interpreter above and re-run there before quoting speedups",
           "stageHistory": stage_history(), "throughputMC": bench_mc(), "closureBoot": bench_boot(),
           "loadDrive": bench_load_drive(a.n, a.repeats)}
    json.dump(res, open(a.out, "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k not in ("stageHistory", "loadDrive")}, indent=1)[:1500])
    print("loadDrive", res["loadDrive"]["files"], "files", res["loadDrive"]["medianSeconds"], "s")


if __name__ == "__main__":
    main()
