#!/usr/bin/env python3
"""M347: script-written block fuelStates.f03SpeedHvCheck from analyses/M347_f03_speed_hv_check.json (tools/f03_speed_hv_check.py). Used by tools/fuel_analytics2.py and by the
one-off leaf splice tools/m347_f03_splice.py. No number is typed here."""
import hashlib, json, os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "analyses", "M347_f03_speed_hv_check.json")
NOTE_F03 = "not a paired test: date-confounded; speed, SoC and engine-speed columns of the hash-failing raw/ files are cell-identical to the sha256-verified originals; HV current and voltage in raw/ are rounded (effect computed in the read-only comparison, f03SpeedHvCheck)"
NOTE_CHG = ("fuel consumed during net pack charging: a temporal state, not a fuel-source allocation; battery offset is estimated; hash-passing trips are the primary basis; hash-failing trips have "
            "rounded raw/ current (effect on pack energy computed in the read-only comparison, f03SpeedHvCheck)")


def build():
    r = json.load(open(SRC, encoding="utf-8"))
    c, d = r["columns"], r["derived"]
    return {"source": "analyses/M347_f03_speed_hv_check.json", "sourceSha256": hashlib.sha256(open(SRC, "rb").read()).hexdigest(),
            "scope": f"{r['nFilesCompared']} hash-failing canonical files, raw/ copy vs sha256-verified original, read-only (owner-approved 2026-10-03); nothing copied into raw/",
            "nFilesCompared": r["nFilesCompared"], "filesWithoutUsableSpeed": r.get("filesWithoutUsableSpeed"),
            "cellIdentical": {k: {"nFiles": c[k]["nFiles"], "filesAllCellsEqual": c[k]["filesAllCellsEqual"], "maxAbsDiff": c[k]["maxAbsDiff"]} for k in ("speedVCM", "speedOBD", "soc", "rpm")},
            "rounded": {k: {"nFiles": c[k]["nFiles"], "filesAllCellsEqual": c[k]["filesAllCellsEqual"], "maxAbsDiff": c[k]["maxAbsDiff"]} for k in ("hvCurrent", "hvVoltage")},
            "derived": {k: {"n": d[k]["n"], "aggRelDiff": d[k]["aggRelDiff"], "maxAbsPerDriveDiff": d[k]["maxAbsPerDriveDiff"], "nDrivesDiffAbove1pct": d[k]["nDrivesDiffAbove1pct"], "unit": d[k]["unit"]}
                        for k in ("km", "stationaryShare", "dischargeKwh", "chargeKwh")}}
