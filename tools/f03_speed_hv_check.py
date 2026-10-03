#!/usr/bin/env python3
"""M347 (F03, owner-approved read-only check 2026-10-03): compare the SPEED, HV current, HV voltage, SoC and engine-rpm columns of the raw/ copies of the hash-failing canonical files with the
sha256-verified originals in ../../originals_recovered (outside the repo). Reads only; copies nothing into raw/; no re-anchoring.
Per file with the column in both copies (row counts must match): cell-level equality share and max absolute difference per column; then derived per-drive quantities computed identically
from each copy: speed integral km (dt capped at 5 s), share of time at speed <= 1 km/h, discharge and charge energy (sum of V*I over capped dt; raw BMS current is charge-positive).
Writes analyses/M347_f03_speed_hv_check.json. Usage: python tools/f03_speed_hv_check.py"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
import recon_engine as RE

ORIG = os.path.abspath(os.path.join(ROOT, "..", "..", "originals_recovered"))
RAW = os.path.join(ROOT, "raw")
COLS = {"speedVCM": "[VCM] Vehicle Speed (km/h)", "speedOBD": RE.CH["speed"], "hvCurrent": RE.CH["I"], "hvVoltage": RE.CH["V"], "soc": RE.CH["soc"], "rpm": RE.CH["rpm"]}


def key_of(n):
    d = "".join(ch for ch in n if ch.isdigit())
    return d[:8] + "_" + d[8:14] + ".csv" if len(d) >= 14 else None


def derived(df):
    t = pd.to_datetime(df["time"], errors="coerce", format="mixed")
    dt = t.diff().dt.total_seconds().clip(lower=0, upper=5).fillna(0.0).values
    out = {}
    spd = None
    for k in ("speedVCM", "speedOBD"):
        c = COLS[k]
        if c in df.columns and pd.to_numeric(df[c], errors="coerce").notna().sum() >= 20:
            spd = pd.to_numeric(df[c], errors="coerce").ffill(limit=15).values; out["speedSource"] = k; break
    if spd is not None:
        ok = np.isfinite(spd)
        out["km"] = float(np.nansum(np.nan_to_num(spd) / 3600.0 * dt))
        out["stationaryShare"] = float((dt[ok & (spd <= 1.0)].sum()) / max(dt[ok].sum(), 1e-9))
    if COLS["hvCurrent"] in df.columns and COLS["hvVoltage"] in df.columns:
        I = pd.to_numeric(df[COLS["hvCurrent"]], errors="coerce").ffill(limit=15).values
        V = pd.to_numeric(df[COLS["hvVoltage"]], errors="coerce").ffill(limit=15).values
        P = -I * V / 1000.0                         # discharge-positive kW (raw current is charge-positive)
        ok = np.isfinite(P)
        out["dischargeKwh"] = float(np.sum(np.maximum(P[ok], 0) * dt[ok]) / 3600.0)
        out["chargeKwh"] = float(np.sum(np.maximum(-P[ok], 0) * dt[ok]) / 3600.0)
    return out


def main():
    man = json.load(open(os.path.join(ROOT, "originals_manifest.json"), encoding="utf-8"))["records"]
    names = {key_of(n): n for n in os.listdir(RAW) if key_of(n)}
    onames = {key_of(n): n for n in os.listdir(ORIG) if key_of(n)} if os.path.isdir(ORIG) else {}
    rows, skipped = [], {"no_orig": 0, "no_raw": 0, "rows_differ": 0}
    colstats = {k: {"nFiles": 0, "filesAllCellsEqual": 0, "maxAbsDiff": 0.0, "minEqualShare": 1.0, "nanMismatchFiles": 0} for k in COLS}
    for rec in man:
        k = rec["record_id"]
        if k not in onames: skipped["no_orig"] += 1; continue
        if k not in names: skipped["no_raw"] += 1; continue
        a = pd.read_csv(os.path.join(RAW, names[k]), low_memory=False)
        b = pd.read_csv(os.path.join(ORIG, onames[k]), low_memory=False)
        if len(a) != len(b): skipped["rows_differ"] += 1; continue
        for nm, c in COLS.items():
            if c in a.columns and c in b.columns:
                x, y = pd.to_numeric(a[c], errors="coerce").values, pd.to_numeric(b[c], errors="coerce").values
                both = np.isfinite(x) & np.isfinite(y)
                if not both.any(): continue
                s = colstats[nm]; s["nFiles"] += 1
                eq = float(np.mean(x[both] == y[both]))
                s["filesAllCellsEqual"] += int(eq == 1.0); s["minEqualShare"] = min(s["minEqualShare"], eq)
                s["maxAbsDiff"] = max(s["maxAbsDiff"], float(np.max(np.abs(x[both] - y[both]))))
                s["nanMismatchFiles"] += int(np.sum(np.isfinite(x) != np.isfinite(y)) > 0)
        da, db = derived(a), derived(b)
        rows.append({"id": k, **{f"{q}_raw": da.get(q) for q in ("km", "stationaryShare", "dischargeKwh", "chargeKwh")}, **{f"{q}_orig": db.get(q) for q in ("km", "stationaryShare", "dischargeKwh", "chargeKwh")},
                     "speedSourceRaw": da.get("speedSource"), "speedSourceOrig": db.get("speedSource")})
    d = pd.DataFrame(rows)
    res = {"milestone": "M347", "check": "F03 speed/HV columns raw/ vs sha256-verified originals (read-only)", "originalsDir": "../../originals_recovered (outside repo)", "nManifestRecords": len(man),
           "nFilesCompared": int(len(d)), "skipped": skipped, "columns": colstats, "derived": {}}
    for q, unit in (("km", "km"), ("stationaryShare", "share"), ("dischargeKwh", "kWh"), ("chargeKwh", "kWh")):
        x = d.dropna(subset=[q + "_raw", q + "_orig"])
        if not len(x): continue
        sr, so = float(x[q + "_raw"].sum()), float(x[q + "_orig"].sum())
        diff = (x[q + "_raw"] - x[q + "_orig"]).abs()
        res["derived"][q] = {"unit": unit, "n": int(len(x)), "sumRaw": round(sr, 4), "sumOrig": round(so, 4), "aggRelDiff": round((sr - so) / so, 6) if so else None,
                             "maxAbsPerDriveDiff": round(float(diff.max()), 6), "p95AbsPerDriveDiff": round(float(diff.quantile(0.95)), 6),
                             "nDrivesDiffAbove1pct": int((diff / x[q + "_orig"].abs().replace(0, np.nan) > 0.01).sum())}
    res["speedSourceChanged"] = int((d.speedSourceRaw.fillna("none") != d.speedSourceOrig.fillna("none")).sum()) if len(d) else 0
    res["filesWithoutUsableSpeed"] = int(d.speedSourceRaw.isna().sum()) if len(d) else 0
    with open(os.path.join(ROOT, "analyses", "M347_f03_speed_hv_check.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, indent=1, ensure_ascii=False); fh.write("\n")
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
