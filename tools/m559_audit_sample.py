#!/usr/bin/env python3
"""M559 audit sample (spec Rev 2 R6): windows for the blind audit, chosen from RAW conditions only (independent of tools/engine_context_fields.py), seed 42.
For every cadence stratum (fast / slow) and every condition category one 21 s window (centre +- 10 s) is drawn from the canonical-clean drives. Writes analyses/M559_audit_sample.json.
Usage: python tools/m559_audit_sample.py"""
import io, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
import compute_summary_arrays as C

RPM, BOOST, LOAD, CUR, SOC, SPD, FUEL = "Оберти двигуна (rpm)", "Розрахунковий наддув (bar)", "Розрахункове значення навантаження на двигун (%)", "[BMS] HV Battery Current (A)", "[BMS] HV State of charge (%)", "[VCM] Vehicle Speed (km/h)", "Витрати палива (L/h)"
COOL = "Температура охолодної рідини (℃)"
raw_dir = os.environ.get("XT_RAW_DIR", os.path.join(ROOT, "raw"))
dig = lambda s: "".join(ch for ch in s if ch.isdigit())[:14]
rawmap = {dig(f): f for f in os.listdir(raw_dir) if f.endswith(".csv")}
dm = pd.read_csv("drive_master.csv", low_memory=False)
cad = dict(zip(*pd.read_csv("cadence_regime.csv")[["file", "regime"]].T.values))
bad = C._canonical_bad(dm)
rng = np.random.default_rng(42)


def grid(f):
    df = pd.read_csv(os.path.join(raw_dir, rawmap[dig(f)]), usecols=lambda c: c in (RPM, BOOST, LOAD, CUR, SOC, SPD, FUEL, COOL, "time", C._SPEED_OBD_RAW), low_memory=False)
    df, _ = C._apply_speed_priority(df)
    t = C._ft(df["time"])
    g = df.set_index(t)[[c for c in (RPM, BOOST, LOAD, CUR, SOC, SPD, FUEL) if c in df.columns]].apply(pd.to_numeric, errors="coerce").resample("1s").mean().ffill(limit=3)
    cs = pd.to_numeric(df[COOL], errors="coerce") if COOL in df.columns else None
    age = None
    if cs is not None and cs.notna().any():
        s = pd.Series(cs.values, index=t)[cs.notna().values]
        last = s.index.to_series().reindex(g.index, method="ffill")
        age = (g.index.to_series() - last).dt.total_seconds()
        cv = s.reindex(g.index, method="ffill")
        g["cool"], g["coolAge"] = cv.values, age.values
    return g


# category -> boolean mask over a drive's grid (raw conditions only)
def cats(g):
    r = g.get(RPM); b = g.get(BOOST); l = g.get(LOAD); i = g.get(CUR); s = g.get(SOC); v = g.get(SPD); f = g.get(FUEL)
    out = {}
    if r is not None:
        on = r > 400
        out["engineStart"] = on & ~on.shift(1, fill_value=False)
        out["engineStop"] = ~on & on.shift(1, fill_value=False)
        if i is not None:
            out["brakingRpm0Charging"] = (r < 50) & (g[SPD].diff() < -1.5 if SPD in g else False) & (i > 2)
            out["flowDeadbandEdge"] = on & ((-i).abs().between(1.5, 2.5))
            if s is not None:
                out["highSocNeutralOrDischarging"] = on & (s >= 80) & (-i > -2)
            if f is not None and b is not None:
                out["genCharging"] = on & (b >= -0.55) & (f > 0) & (-i < -2)
                if SPD in g:
                    out["genDischargingMoving"] = on & (b >= -0.55) & (f > 0) & (-i > 2) & (g[SPD] > 5)
        if b is not None:
            out["boostEdge"] = (r > 2000) & b.between(-0.72, -0.68)
            if l is not None:
                out["loadEdge"] = (r > 2000) & (b < -0.7) & l.between(7.6, 8.4)
                out["motoredDissipation"] = (r > 2000) & (b < -0.7) & (l.fillna(0) < 8)
        if f is not None:
            out["fuelZeroRotating"] = on & (f.fillna(0) <= 0)
    if "cool" in g:
        out["coolant60"] = on.reindex(g.index, fill_value=False) & g["cool"].between(59, 61) if r is not None else None
        out["coolant80"] = on & g["cool"].between(79, 81) if r is not None else None
        out["coolantAge30"] = on & g["coolAge"].between(28, 32) if r is not None else None
        out["coldRotating"] = on & (g["cool"] <= 55) & (g["coolAge"] <= 30) if r is not None else None
    return {k: v for k, v in out.items() if v is not None}


files = {s: [f for f, c in zip(dm["file"], bad) if not c and cad.get(f) == s and dig(f) in rawmap] for s in ("fast", "slow")}
want = ["engineStart", "engineStop", "brakingRpm0Charging", "flowDeadbandEdge", "highSocNeutralOrDischarging", "genCharging", "genDischargingMoving", "boostEdge", "loadEdge", "motoredDissipation",
        "fuelZeroRotating", "coolant60", "coolant80", "coolantAge30", "coldRotating"]
windows, used = [], set()
for s in ("fast", "slow"):
    order = list(rng.permutation(files[s]))
    need = {k: 2 for k in want}
    for f in order:
        if not any(need.values()):
            break
        try:
            g = grid(f)
        except Exception:
            continue
        for k, m in cats(g).items():
            if need.get(k, 0) <= 0 or f in used:
                continue
            idx = np.flatnonzero(m.fillna(False).to_numpy())
            idx = idx[(idx >= 10) & (idx < len(g) - 10)]
            if not len(idx):
                continue
            c = int(rng.choice(idx))
            windows.append({"file": f, "stratum": s, "category": k, "startIndexS": c - 10, "endIndexS": c + 10, "startTime": str(g.index[c - 10]), "endTime": str(g.index[c + 10])})
            need[k] -= 1; used.add(f)
# special files: fuel channel all zero, a file without boost or load, one with no coolant (first found, deterministic order)
special = {}
for f in sorted(files["fast"] + files["slow"]):
    try:
        g = grid(f)
    except Exception:
        continue
    fu = g.get(FUEL)
    if "fuelAllZero" not in special and fu is not None and fu.fillna(0).max() <= 0 and (g[RPM] > 400).sum() > 60:
        special["fuelAllZero"] = f
    if "noBoost" not in special and (BOOST not in g.columns or not g[BOOST].notna().any()) and (g[RPM] > 400).sum() > 60:
        special["noBoost"] = f
    if len(special) == 2:
        break
for k, f in special.items():
    g = grid(f); on = np.flatnonzero((g[RPM] > 400).to_numpy()); on = on[(on >= 10) & (on < len(g) - 10)]
    if len(on):
        c = int(on[len(on) // 2]); windows.append({"file": f, "stratum": cad.get(f) if isinstance(cad.get(f), str) else "unknown", "category": k, "startIndexS": c - 10, "endIndexS": c + 10, "startTime": str(g.index[c - 10]), "endTime": str(g.index[c + 10])})
out = {"milestone": "M559", "seed": 42, "drawnBy": "tools/m559_audit_sample.py (raw conditions only; independent of the classifier)", "windowSeconds": 21, "windows": windows,
       "categories": {k: sum(1 for w in windows if w["category"] == k) for k in sorted({w["category"] for w in windows})}}
json.dump(out, open(os.path.join(ROOT, "analyses", "M559_audit_sample.json"), "w", encoding="utf-8"), indent=1)
print(len(windows), out["categories"])
