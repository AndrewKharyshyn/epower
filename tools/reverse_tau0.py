"""M698 step 1 (spec analyses/M695_spec.md Rev 1.1 section 11 item 1): the standstill torque noise floor tau0, computed in a SEPARATE run, before any episode code exists.

Samples: canonical-clean drives, target-torque sample times; speed (VCM column only) == 0 on the aligned speed (nearest-previous within 1500 ms, no interpolation),
engine rpm < 300 on the aligned rpm (same alignment; a sample without an aligned rpm is excluded and counted), excluding the 5 s before any speed > 0 transition.
tau0 = max(99th percentile of |target torque| over those samples, the resolution of the torque register).
Per-drive histograms of |torque| are cached by raw sha256 (reverse_tau0_cache/); no episode quantity is computed here.
"""
import hashlib, json, os, sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
CACHE_DIR = os.path.join(ROOT, "reverse_tau0_cache")
VERSION = 1
TOL_MS = 1500
PRE_S = 5.0
RPM_OFF = 300.0
SPEC = "analyses/M695_spec.md"
OUT = os.path.join(ROOT, "analyses", "M698_tau0.json")


def aligned(csv_bytes, source="vcm"):
    """DataFrame at the target-torque sample times: t (s from the first timestamp), torque, speed, rpm (nearest-previous within 1500 ms, NaN otherwise), plus the speed>0 transition times."""
    import compute_drive_summary_v6 as D
    df, t = D._prep_bytes(csv_bytes)
    tq = D._series(df, t, "target_torque")
    sp = D._series(df, t, "speed", lo=0, hi=260)
    if source == "obd":          # per-source descriptive run (Rev 1.2): only drives WITHOUT the VCM speed PID, with the standard OBD vehicle speed
        sp = D._series(df, t, "speed_obd", lo=0, hi=260) if sp is None else None
    en = D._series(df, t, "eng_rpm", lo=0)
    if tq is None or sp is None:
        return None, []
    t0 = min(tq["t"].min(), sp["t"].min())
    base = pd.DataFrame({"t": tq["t"].values, "torque": tq["v"].values}).sort_values("t")
    tol = pd.Timedelta(milliseconds=TOL_MS)
    base = pd.merge_asof(base, pd.DataFrame({"t": sp["t"].values, "speed": sp["v"].values}).sort_values("t"), on="t", direction="backward", tolerance=tol)
    if en is not None:
        base = pd.merge_asof(base, pd.DataFrame({"t": en["t"].values, "rpm": en["v"].values}).sort_values("t"), on="t", direction="backward", tolerance=tol)
    else:
        base["rpm"] = np.nan
    base["ts"] = (base["t"] - t0).dt.total_seconds()
    v = sp["v"].to_numpy(float)
    ts = (sp["t"] - t0).dt.total_seconds().to_numpy(float)
    prev = np.concatenate([[0.0], v[:-1]])               # the drive start counts as standstill
    trans = ts[(v > 0) & (prev == 0)]
    return base, trans


def drive_hist(csv_bytes, source="vcm"):
    base, trans = aligned(csv_bytes, source)
    if base is None:
        return {"nRows": 0, "hist": {}, "nNoRpm": 0, "nNotStandstill": 0, "nPreTransition": 0}
    standstill = (base["speed"] == 0).to_numpy()
    has_rpm = base["rpm"].notna().to_numpy()
    eng_off = (base["rpm"] < RPM_OFF).to_numpy()
    ts = base["ts"].to_numpy(float)
    pre = np.zeros(len(base), dtype=bool)
    for tr in trans:
        pre |= (ts >= tr - PRE_S) & (ts <= tr)
    ok = standstill & has_rpm & eng_off & ~pre
    a = np.abs(base["torque"].to_numpy(float))
    vals, cnt = np.unique(np.round(a[ok], 6), return_counts=True)
    allv = np.unique(np.round(np.abs(base["torque"].to_numpy(float)), 6))
    d = np.diff(allv)
    d = d[d > 1e-9]
    return {"nRows": int(len(base)), "hist": {repr(float(x)): int(c) for x, c in zip(vals, cnt)}, "nStandstill": int(standstill.sum()), "nNoRpm": int((standstill & ~has_rpm).sum()),
            "nEngineOn": int((standstill & has_rpm & ~eng_off).sum()), "nPreTransition": int((standstill & has_rpm & eng_off & pre).sum()), "nUsed": int(ok.sum()),
            "torqueStep": float(d.min()) if len(d) else None}


def corpus(source="vcm"):
    import ah_throughput as AH
    m = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), usecols=["file", "date", "ens_outlier_v2", "ens_invalid"], low_memory=False)
    clean = ~(m["ens_outlier_v2"].map(lambda x: x is True or x == "True") | m["ens_invalid"].map(lambda x: x is True or x == "True"))
    m = m[clean].reset_index(drop=True)
    cad = pd.read_csv(os.path.join(ROOT, "cadence_regime.csv"))
    reg = {r.file: (r.regime if isinstance(r.regime, str) else "unknown") for r in cad.itertuples()}
    sha_by, loader = AH.manifest_sha_lookup(), AH.raw_loader(os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    os.makedirs(CACHE_DIR if source == "vcm" else CACHE_DIR + "_obd", exist_ok=True)
    code = hashlib.sha256(open(__file__, "rb").read()).hexdigest()[:8]
    rows = []
    for _, r in m.iterrows():
        b = loader(r["file"])
        if b is None:
            continue
        sha = sha_by(r["file"]) or hashlib.sha256(b).hexdigest()
        cp = os.path.join(CACHE_DIR if source == "vcm" else CACHE_DIR + "_obd", "%s_v%d_%s.json" % (sha, VERSION, code))
        if os.path.isfile(cp):
            h = json.load(open(cp, encoding="utf-8"))
        else:
            h = drive_hist(b, source)
            h["sha"] = sha
            json.dump(h, open(cp, "w", encoding="utf-8"), separators=(",", ":"))
        rows.append({**h, "file": r["file"], "date": str(r["date"])[:10], "regime": reg.get(r["file"], "unknown")})
    return rows


def pooled_percentile(rows, q):
    vals, cnt = [], []
    for r in rows:
        for k, c in r["hist"].items():
            vals.append(float(k)); cnt.append(c)
    if not vals:
        return None, 0
    v = np.array(vals); c = np.array(cnt)
    o = np.argsort(v)
    v, c = v[o], c[o]
    cs = np.cumsum(c)
    return float(v[int(np.searchsorted(cs, q / 100.0 * cs[-1]))]), int(cs[-1])


def main(argv=()):
    source = "obd" if "--source-obd" in argv else "vcm"
    rows = corpus(source)
    used = [r for r in rows if r.get("nUsed", 0) > 0]
    p99, n = pooled_percentile(used, 99.0)
    steps = [r["torqueStep"] for r in rows if r.get("torqueStep")]
    step = float(np.median(steps)) if steps else None
    tau0 = max(p99, step) if (p99 is not None and step is not None) else p99
    by = {}
    for reg in ("fast", "slow", "unknown"):
        rr = [r for r in used if r["regime"] == reg]
        if rr:
            q, nn = pooled_percentile(rr, 99.0)
            by[reg] = {"nDrives": len(rr), "nSamples": nn, "p99AbsTorque": q}
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    out = {"spec": SPEC + " Rev 1.1 section 11 item 1", "purpose": "standstill torque noise floor tau0, computed before any episode code exists",
           "population": {"canonicalCleanDrives": len(rows), "drivesWithUsedSamples": len(used), "nDays": len({r["date"] for r in used}), "nSamplesUsed": n,
                          "excluded": {"standstillWithoutAlignedRpm": int(sum(r.get("nNoRpm", 0) for r in rows)), "standstillEngineOn": int(sum(r.get("nEngineOn", 0) for r in rows)), "standstillWithin5sBeforeATransition": int(sum(r.get("nPreTransition", 0) for r in rows))}},
           "rule": "speed == 0 (aligned, nearest-previous within 1500 ms), engine rpm < 300 (aligned the same way), excluding the 5 s before any speed > 0 transition; the drive start counts as standstill",
           "p99AbsTorqueNm": p99, "torqueRegisterStepNm": step, "tau0Nm": tau0, "byCadenceDescriptive": by,
           "masterMd5": md5, "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest()}
    if source == "obd":
        out["purpose"] = "per-source DESCRIPTIVE tau0 for the OBD-speed drives (Rev 1.2 condition 3); never substituted for the frozen 45.77 N.m"
        out["speedSource"] = "standard OBD vehicle speed (ECU-reported, integer km/h, not GPS), drives without the VCM speed PID"
    json.dump(out, open(OUT if source == "vcm" else OUT.replace("M698_tau0.json", "M698_tau0_obd.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps(out)[:1500])


if __name__ == "__main__":
    main(sys.argv[1:])
